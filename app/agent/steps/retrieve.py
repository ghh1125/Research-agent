from __future__ import annotations

from dataclasses import dataclass

from app.agent.utils.query_builder import (
    build_counter_queries,
    build_english_queries,
    build_fact_queries,
    build_risk_queries,
    is_us_stock,
    split_directed_queries,
)
from app.config import get_settings
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.evidence_engine import (
    classify_source_origin,
    classify_tier_from_origin,
    compute_is_recent,
    contains_target_entity,
    is_recent_source,
    rank_sources,
    resolve_source_date,
)
from app.services.pdf_service import enrich_pdf_sources
from app.services.search_providers.supplemental import search_supplemental_sources
from app.services.search_service import search


@dataclass(frozen=True)
class _SearchTask:
    question_id: str
    query: str
    flow_type: str


def _is_pdf_url(url: str | None, title: str) -> bool:
    text = f"{url or ''} {title}".lower()
    return ".pdf" in text or "pdf" in text


def _pick_question_id(questions: list[Question], keywords: list[str]) -> str:
    for question in questions:
        if any(keyword in question.content for keyword in keywords):
            return question.id
    return questions[0].id if questions else "q0"


def _build_workflow_tasks(questions: list[Question], topic: Topic | None) -> tuple[list[_SearchTask], list[_SearchTask]]:
    if topic is None:
        return [], []

    subject = topic.entity or topic.topic
    if not subject:
        return [], []

    risk_question_id = _pick_question_id(questions, ["风险", "财务", "现金流", "负债", "合规", "治理", "监管"])
    counter_question_id = _pick_question_id(questions, ["改善", "增长", "机会", "竞争", "相对位置", "继续研究", "关键数据"])

    risk_queries = build_risk_queries(topic)
    counter_queries = build_counter_queries(topic)

    risk_tasks = [
        _SearchTask(question_id=risk_question_id, query=query, flow_type="risk")
        for query in risk_queries
    ]
    counter_tasks = [
        _SearchTask(question_id=counter_question_id, query=query, flow_type="counter")
        for query in counter_queries
    ]
    return risk_tasks, counter_tasks


def _build_fact_priority_tasks(questions: list[Question], topic: Topic | None) -> list[_SearchTask]:
    if topic is None:
        return []

    subject = topic.entity or topic.topic
    object_type = getattr(topic, "research_object_type", "unknown")
    question_id = _pick_question_id(questions, ["财务", "现金流", "利润", "收入", "关键数据", "官方", "评级", "行业"])
    if object_type == "listed_company":
        queries = [
            f"{subject} investor relations annual report financial results",
            f"{subject} 官方 年报 季报 财报 公告",
            f"{subject} site:sec.gov annual report 20-F",
            f"{subject} site:hkexnews.hk 公告 年报",
            f"{subject} site:cninfo.com.cn 年报 季报 公告",
        ]
        if subject == "拼多多":
            queries.extend(
                [
                    "PDD Holdings annual report revenue net income operating cash flow",
                    "PDD Holdings quarterly results revenue net income Temu",
                ]
            )
    elif object_type == "private_company":
        queries = [
            f"{subject} 官方 网站 年报 经营数据",
            f"{subject} 融资 新闻 估值 投资方 latest",
            f"{subject} 产品 生态 合作伙伴 商业模式",
        ]
    elif object_type == "credit_issuer":
        queries = [
            f"{subject} 募集说明书 债券 年报 评级报告",
            f"{subject} 债务 到期 再融资 担保 违约",
            f"{subject} 评级 司法 处罚 公告",
        ]
    elif object_type in {"industry_theme", "macro_theme", "event"}:
        queries = [
            f"{subject} 政策 文件 官方 数据 latest",
            f"{subject} 行业协会 市场规模 研究报告",
            f"{subject} 龙头 公司 财报 行业 表述",
        ]
    elif object_type in {"concept_theme", "fund_etf", "commodity"}:
        queries = [
            f"{subject} 官方 数据 价格 持仓 latest",
            f"{subject} 产业链 受益 标的 ETF",
            f"{subject} 风险 供需 政策 价格",
        ]
    else:
        queries = [f"{subject} 官方 数据 报告 latest", f"{subject} 专业财经 研究 风险"]
    return [_SearchTask(question_id=question_id, query=query, flow_type="fact") for query in queries]


def _interleave_tasks(*task_groups: list[_SearchTask]) -> list[_SearchTask]:
    interleaved: list[_SearchTask] = []
    max_len = max((len(group) for group in task_groups), default=0)
    for index in range(max_len):
        for group in task_groups:
            if index < len(group):
                interleaved.append(group[index])
    return interleaved


def _tasks_from_queries(question_id: str, queries: list[str], flow_type: str) -> list[_SearchTask]:
    return [_SearchTask(question_id=question_id, query=query, flow_type=flow_type) for query in queries]


def _should_use_supplemental_sources(topic: Topic | None) -> bool:
    if topic is None:
        return False
    return (
        getattr(topic, "research_object_type", "unknown") == "listed_company"
        or getattr(topic, "market_type", "other") in {"A_share", "HK", "US"}
    )


def _source_from_result(
    result: dict,
    *,
    question_id: str,
    flow_type: str,
    query: str,
    source_id: str,
    topic: Topic | None,
) -> Source:
    origin = result.get("source_origin_type") or classify_source_origin(
        url=(result.get("url") or "").strip() or None,
        title=result["title"],
        source_type=result["source_type"],
        content=result["content"],
    )
    tier = classify_tier_from_origin(origin)
    draft_source = Source(
        id=source_id,
        question_id=question_id,
        flow_type=flow_type,
        search_query=query,
        url=(result.get("url") or "").strip() or None,
        title=result["title"],
        source_type=result["source_type"],
        provider=result.get("provider", "unknown"),
        source_origin_type=origin,
        credibility_tier={
            "official": "tier1",
            "professional": "tier2",
            "content": "tier3",
        }[tier.value],
        tier=tier,
        published_at=result.get("published_at"),
        is_pdf=_is_pdf_url(result.get("url"), result["title"]),
        pdf_parse_status="not_attempted" if _is_pdf_url(result.get("url"), result["title"]) else "not_pdf",
        content=result["content"],
    )
    resolved_date, date_source = resolve_source_date(draft_source)
    return draft_source.model_copy(
        update={
            "contains_entity": contains_target_entity(
                f"{draft_source.title} {draft_source.content[:1200]}",
                topic,
            )
            if topic
            else False,
            "is_recent": compute_is_recent(resolved_date) if resolved_date is not None else is_recent_source(draft_source),
            "date_source": date_source,
        }
    )


def retrieve_information(questions: list[Question], topic: Topic | None = None) -> list[Source]:
    """Retrieve and normalize sources for each question."""

    settings = get_settings()
    sources: list[Source] = []
    seen_urls: set[str] = set()
    source_counter = 1
    per_question_limit = settings.retrieve_per_question_limit
    candidate_limit = max(settings.retrieve_max_sources * 2, settings.retrieve_max_sources)

    fact_tasks = []
    directed_fact_tasks = []
    if topic is not None:
        for question in questions:
            main_queries, directed_queries = split_directed_queries(build_fact_queries(question, topic))
            fact_tasks.extend(_tasks_from_queries(question.id, main_queries, "fact"))
            directed_fact_tasks.extend(_tasks_from_queries(question.id, directed_queries, "fact"))
        if is_us_stock(topic):
            question_id = _pick_question_id(questions, ["财务", "利润", "现金流", "收入", "关键数据"])
            fact_tasks.extend(
                _SearchTask(question_id=question_id, query=query, flow_type="fact")
                for query in build_english_queries(topic)
            )
    priority_main_queries, priority_directed_queries = split_directed_queries(
        [task.query for task in _build_fact_priority_tasks(questions, topic)]
    )
    priority_question_id = _pick_question_id(questions, ["财务", "现金流", "利润", "收入", "关键数据", "官方", "评级", "行业"])
    fact_tasks.extend(_tasks_from_queries(priority_question_id, priority_main_queries, "fact"))
    directed_fact_tasks.extend(_tasks_from_queries(priority_question_id, priority_directed_queries, "fact"))
    risk_tasks, counter_tasks = _build_workflow_tasks(questions, topic)

    if _should_use_supplemental_sources(topic) and fact_tasks:
        supplemental_results, _attempts = search_supplemental_sources(fact_tasks[0].query, topic)
        for result in supplemental_results:
            url = (result.get("url") or "").strip() or None
            dedupe_key = url or f"{result.get('provider', 'unknown')}::{result.get('title', '')}"
            if dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)
            sources.append(
                _source_from_result(
                    result,
                    question_id=fact_tasks[0].question_id,
                    flow_type="fact",
                    query=fact_tasks[0].query,
                    source_id=f"s{source_counter}",
                    topic=topic,
                )
            )
            source_counter += 1

    for task in [*_interleave_tasks(fact_tasks, risk_tasks, counter_tasks), *directed_fact_tasks]:
        try:
            results = search(task.query)
        except RuntimeError:
            continue
        if not results:
            continue
        task_collected = 0
        task_limit = (
            max(1, min(per_question_limit, 2))
            if task.flow_type in {"risk", "counter"}
            else max(1, per_question_limit)
        )
        for result in results:
            url = (result.get("url") or "").strip() or None
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            sources.append(
                _source_from_result(
                    result,
                    question_id=task.question_id,
                    flow_type=task.flow_type,
                    query=task.query,
                    source_id=f"s{source_counter}",
                    topic=topic,
                )
            )
            source_counter += 1
            task_collected += 1

            if len(sources) >= candidate_limit:
                enriched_sources = enrich_pdf_sources(sources)
                return rank_sources(enriched_sources, topic, settings.retrieve_max_sources) if topic else enriched_sources[: settings.retrieve_max_sources]
            if task_collected >= task_limit:
                break
    enriched_sources = enrich_pdf_sources(sources)
    return rank_sources(enriched_sources, topic, settings.retrieve_max_sources) if topic else enriched_sources[: settings.retrieve_max_sources]
