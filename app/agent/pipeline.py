from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone

from app.agent.steps.action import generate_research_actions
from app.agent.steps.auto_research import auto_research_loop
from app.agent.steps.define import define_problem
from app.agent.steps.decompose import decompose_problem
from app.agent.steps.extract import extract_evidence
from app.agent.steps.investment import apply_investment_layer
from app.agent.steps.report import generate_report
from app.agent.steps.reason import reason_and_generate
from app.agent.steps.retrieve import retrieve_information
from app.agent.steps.role import synthesize_role_outputs
from app.agent.steps.summary import build_executive_summary
from app.agent.steps.variable import normalize_variables
from app.db.repository import InMemoryResearchRepository
from app.models.evidence import Evidence
from app.models.financial import FinancialSnapshot
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.content_fetcher import enrich_sources_content
from app.services.evidence_engine import rank_sources
from app.services.financial_data_service import fetch_financial_snapshot
from app.services.official_source_injector import inject_official_sources
from app.services.pdf_service import enrich_pdf_sources
from app.services.storage_service import (
    save_evidence,
    save_judgment,
    save_questions,
    save_report,
    save_roles,
    save_sources,
    save_topic,
    save_variables,
)

ProgressCallback = Callable[[str, str, object | None], None]

FINANCIAL_SOURCE_STATUSES = {"SUCCESS", "PARTIAL_SUCCESS", "FALLBACK_USED", "ok", "fallback_from_search"}

_SNAPSHOT_METRIC_LABELS = {
    "market_cap": ("市值", "valuation"),
    "latest_price": ("最新价格", "valuation"),
    "previous_close": ("前收盘价", "valuation"),
    "previous_open": ("前开盘价", "valuation"),
    "previous_high": ("前一交易日最高价", "valuation"),
    "previous_low": ("前一交易日最低价", "valuation"),
    "previous_volume": ("前一交易日成交量", "valuation"),
    "previous_vwap": ("前一交易日 VWAP", "valuation"),
    "trailing_pe": ("PE", "valuation"),
    "forward_pe": ("远期 PE", "valuation"),
    "pe_ttm": ("PE", "valuation"),
    "pb": ("PB", "valuation"),
    "price_to_book": ("PB", "valuation"),
    "profit_margins": ("净利率", "financial"),
    "net_profit_margin": ("净利率", "financial"),
    "gross_margins": ("毛利率", "financial"),
    "revenue_growth": ("营收同比增速", "financial"),
    "return_on_equity": ("ROE", "financial"),
    "roe": ("ROE", "financial"),
    "debt_to_equity": ("负债权益比", "credit"),
    "share_outstanding": ("流通股本", "valuation"),
    "share_class_shares_outstanding": ("流通股本", "valuation"),
    "weighted_shares_outstanding": ("加权流通股本", "valuation"),
    "营业收入": ("营业收入", "financial"),
    "revenue": ("营业收入", "financial"),
    "net_income": ("净利润", "financial"),
    "operating_cash_flow": ("经营现金流", "credit"),
}

_CURRENCY_UNIT_LABELS = {
    "USD": "美元",
    "HKD": "港元",
    "CNY": "人民币",
    "RMB": "人民币",
}


def _emit_progress(
    callback: ProgressCallback | None,
    step: str,
    message: str,
    payload: object | None = None,
) -> None:
    if callback is not None:
        callback(step, message, payload)


def _financial_snapshot_to_source(
    snapshot: FinancialSnapshot,
    topic: Topic,
    questions: list[Question],
    source_index: int,
) -> Source | None:
    if snapshot.status not in FINANCIAL_SOURCE_STATUSES or not snapshot.metrics:
        return None

    metric_texts = []
    for metric in snapshot.metrics[:24]:
        if metric.value is None:
            continue
        unit = metric.unit or ""
        period = metric.period or "latest"
        metric_texts.append(f"{metric.name}={metric.value}{unit}（{period}）")
    if not metric_texts:
        return None

    question_id = next(
        (
            question.id
            for question in questions
            if any(token in question.content for token in ["财务", "现金流", "增长", "关键数据", "同行"])
        ),
        questions[0].id if questions else "q0",
    )
    peer_text = f"；可比公司代码：{', '.join(snapshot.peer_symbols)}" if snapshot.peer_symbols else ""
    peer_table_text = f"；同行对比表行数：{len(snapshot.peer_comparison)}" if snapshot.peer_comparison else ""
    content = (
        f"{snapshot.entity}结构化金融数据快照："
        f"{'；'.join(metric_texts)}{peer_text}{peer_table_text}。"
        f"数据来源：{snapshot.provider}。"
        "该数据用于内部初筛的市场维度辅助，不替代公司公告、财报或审计口径数据。"
    )
    return Source(
        id=f"s{source_index}",
        question_id=question_id,
        flow_type="fact",
        search_query=f"{snapshot.entity} structured financial data {snapshot.symbol or ''}".strip(),
        title=f"{snapshot.entity} 结构化金融数据快照",
        url=f"https://finance.yahoo.com/quote/{snapshot.symbol}" if snapshot.symbol else None,
        source_type="other",
        provider=snapshot.provider,
        source_origin_type="research_media" if snapshot.status in {"SUCCESS", "PARTIAL_SUCCESS", "ok"} else "professional_media",
        credibility_tier="tier2",
        tier=SourceTier.TIER2,
        source_score=0.72 if snapshot.status in {"SUCCESS", "PARTIAL_SUCCESS", "ok"} else 0.48,
        source_rank_reason="structured_financial_api" if snapshot.status in {"SUCCESS", "PARTIAL_SUCCESS", "ok"} else "financial_search_fallback",
        contains_entity=True,
        is_recent=True,
        content=content,
    )


def _append_financial_source(
    sources: list[Source],
    snapshot: FinancialSnapshot,
    topic: Topic,
    questions: list[Question],
) -> list[Source]:
    structured_source = _financial_snapshot_to_source(snapshot, topic, questions, len(sources) + 1)
    if structured_source is None:
        return sources
    return [*sources, structured_source]


def _question_id_for_snapshot_metric(metric_name: str, questions: list[Question]) -> str | None:
    _, category = _SNAPSHOT_METRIC_LABELS.get(metric_name, (metric_name, "financial"))
    preferred_frameworks = {
        "financial": ["financial"],
        "credit": ["credit", "financial"],
        "valuation": ["valuation", "financial"],
    }.get(category, ["financial"])
    for framework in preferred_frameworks:
        for question in questions:
            if question.framework_type == framework:
                return question.id
    return questions[0].id if questions else None


def _format_snapshot_metric_value(value: object, unit: str | None) -> str:
    unit_label = _CURRENCY_UNIT_LABELS.get(unit or "", unit or "")
    return f"{value}{unit_label}"


def _snapshot_metric_content(snapshot: FinancialSnapshot, metric) -> str:
    label, _ = _SNAPSHOT_METRIC_LABELS.get(metric.name, (metric.name, "financial"))
    value = _format_snapshot_metric_value(metric.value, metric.unit)
    period = metric.period or "latest"
    trend_hint = "，用于观察趋势" if metric.name in {"revenue_growth", "gross_margins", "profit_margins", "net_profit_margin"} else ""
    return (
        f"{snapshot.entity}实时金融快照显示，{label}为{value}，期间为{period}，"
        f"来源为{snapshot.provider}（{metric.source}）{trend_hint}。"
    )


def _snapshot_to_evidence(
    snapshot: FinancialSnapshot,
    topic: Topic,
    questions: list[Question],
    sources: list[Source],
    existing_evidence: list[Evidence],
) -> list[Evidence]:
    """Turn structured provider metrics into first-class evidence for coverage and variables."""

    if snapshot.status not in FINANCIAL_SOURCE_STATUSES or not snapshot.metrics:
        return []
    source = next(
        (
            item
            for item in sources
            if item.provider == snapshot.provider and "结构化金融数据快照" in item.title
        ),
        None,
    )
    if source is None:
        return []

    max_existing_id = 0
    for item in existing_evidence:
        match = re.match(r"e(\d+)$", item.id)
        if match:
            max_existing_id = max(max_existing_id, int(match.group(1)))

    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot_evidence: list[Evidence] = []
    seen_metrics: set[str] = set()
    for metric in snapshot.metrics:
        if metric.value is None or metric.name in seen_metrics:
            continue
        content = _snapshot_metric_content(snapshot, metric)
        if not content.strip():
            continue
        seen_metrics.add(metric.name)
        evidence_index = max_existing_id + len(snapshot_evidence) + 1
        source_score = source.source_score if source.source_score is not None else 0.72
        snapshot_evidence.append(
            Evidence(
                id=f"e{evidence_index}",
                topic_id=topic.id,
                question_id=_question_id_for_snapshot_metric(metric.name, questions),
                source_id=source.id,
                flow_type="fact",
                content=content,
                evidence_type="data",
                stance="neutral",
                grounded=True,
                is_noise=False,
                is_truncated=False,
                quality_score=0.88,
                quality_notes=["structured_financial_snapshot", f"provider={snapshot.provider}", f"metric={metric.name}"],
                source_tier=source.tier.value,
                source_score=source_score,
                relevance_score=0.88,
                clarity_score=0.9,
                recency_score=1.0,
                evidence_score=0.9,
                timestamp=timestamp,
            )
        )

    return snapshot_evidence[:16]


def _dedupe_sources(sources: list[Source]) -> list[Source]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[Source] = []
    for source in sources:
        url_key = (source.url or "").strip().lower()
        title_key = source.title.strip().lower()
        if url_key and url_key in seen_urls:
            continue
        if not url_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        seen_titles.add(title_key)
        deduped.append(source)
    return deduped


def _enrich_and_rank_sources(sources: list[Source], topic: Topic) -> list[Source]:
    pdf_enriched = enrich_pdf_sources(sources)
    pre_ranked = rank_sources(pdf_enriched, topic, len(pdf_enriched))
    enriched = enrich_sources_content(pre_ranked)
    return rank_sources(enriched, topic, len(enriched))


def _attach_peer_comparison_to_judgment(judgment, snapshot: FinancialSnapshot):
    if not snapshot.peer_comparison or judgment.peer_context is None:
        return judgment
    peer_context = judgment.peer_context.model_copy(
        update={
            "comparison_rows": snapshot.peer_comparison,
            "peer_entities": snapshot.peer_symbols or judgment.peer_context.peer_entities,
            "status": "covered",
            "note": f"{judgment.peer_context.note} 已补充 {snapshot.provider} 同行对比表。",
        }
    )
    return judgment.model_copy(update={"peer_context": peer_context})


_RELATIVE_CONTEXT_TOKENS = ["同行", "行业平均", "对比", "竞争对手", "市占率", "市场份额", "相对位置", "peer", "competitor"]


def _effective_evidence_count(evidence: list) -> int:
    return len([item for item in evidence if (item.evidence_score or item.quality_score or 0) >= 0.35])


def _has_relative_context(evidence: list, financial_snapshot: FinancialSnapshot | None = None) -> bool:
    if financial_snapshot is not None and financial_snapshot.peer_comparison:
        return True
    return any(
        any(token.lower() in item.content.lower() for token in _RELATIVE_CONTEXT_TOKENS)
        for item in evidence
    )


def _mark_question_coverage(
    questions: list,
    evidence: list,
    topic: Topic | None = None,
    financial_snapshot: FinancialSnapshot | None = None,
) -> list:
    relative_context_ready = _has_relative_context(evidence, financial_snapshot)
    requires_relative_context = (
        topic is not None
        and getattr(topic, "research_object_type", "unknown") == "listed_company"
    )
    evidence_by_question = {
        question.id: [item for item in evidence if item.question_id == question.id]
        for question in questions
    }

    def _has_complete_number(text: str, tokens: list[str]) -> bool:
        if not any(token in text for token in tokens):
            return False
        return bool(re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|百万|千元|美元|人民币|港元|%|百分点|倍)", text))

    def _coverage_level(question, items: list) -> str:
        if not items:
            return "uncovered"
        texts = [item.content for item in items if (item.evidence_score or item.quality_score or 0) >= 0.35]
        if not texts:
            return "uncovered"
        joined = " ".join(texts)
        framework = getattr(question, "framework_type", "general")
        if framework == "financial":
            has_revenue = _has_complete_number(joined, ["营业收入", "营收", "收入"])
            has_profit = _has_complete_number(joined, ["净利润", "归母净利润", "扣非净利润"])
            has_margin = _has_complete_number(joined, ["毛利率", "净利率"])
            has_trend = any(token in joined for token in ["同比", "三年", "趋势", "上年同期", "较上年"])
            strong = has_revenue and has_profit and has_margin and has_trend
            return "covered" if strong else "partial"
        if framework == "credit":
            has_cashflow = _has_complete_number(joined, ["经营现金流", "经营活动现金流", "经营活动产生的现金流量净额"])
            has_capex = _has_complete_number(joined, ["资本开支", "CAPEX", "购建固定资产"])
            has_debt = any(_has_complete_number(joined, [token]) for token in ["有息负债", "债务结构", "短债", "资产负债率", "流动比率"])
            strong = has_cashflow and has_capex and has_debt
            return "covered" if strong else "partial"
        if framework == "industry":
            has_share = any(token in joined for token in ["市场份额", "市占率", "份额"])
            has_peer = relative_context_ready or any(token in joined for token in ["同行对比", "同业对比", "同行排名", "竞争对手"])
            has_competition = any(token in joined for token in ["竞争格局", "价格竞争", "客户结构", "技术路线", "产能份额"])
            strong = has_share and has_peer and has_competition
            return "covered" if strong else "partial"
        if framework == "valuation":
            has_multiple = any(token in joined for token in ["PE", "PB", "EV/EBITDA", "EVEBITDA", "市盈率", "市净率", "估值倍数"])
            return "covered" if has_multiple and relative_context_ready else "uncovered"
        return "covered"

    marked = []
    for question in questions:
        coverage_level = _coverage_level(question, evidence_by_question.get(question.id, []))
        covered = coverage_level == "covered"
        if (
            covered
            and requires_relative_context
            and question.framework_type in {"industry", "valuation"}
            and not relative_context_ready
        ):
            covered = False
            coverage_level = "partial"
        marked.append(question.model_copy(update={"covered": covered, "coverage_level": coverage_level}))
    return marked


def research_pipeline(
    query: str,
    repository: InMemoryResearchRepository | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    """Run the fixed research pipeline from query to user-facing report."""

    clean_query = query.strip()
    if not clean_query:
        raise ValueError("query must not be empty")

    repo = repository or InMemoryResearchRepository()

    topic = define_problem(clean_query)
    listing_text = f"；上市状态：{topic.listing_status}" if topic.listing_status != "unknown" else ""
    _emit_progress(progress_callback, "define", f"研究主题：{topic.topic}；对象：{topic.entity or '未识别'}{listing_text}", topic)
    questions = decompose_problem(topic)
    _emit_progress(progress_callback, "decompose", f"已生成 {len(questions)} 个研究问题。", questions)
    financial_snapshot = fetch_financial_snapshot(topic)
    _emit_progress(progress_callback, "financial_snapshot", f"金融快照状态：{financial_snapshot.status}", financial_snapshot)
    official_sources = inject_official_sources(topic, questions)
    retrieved_sources = retrieve_information(questions, topic)
    sources = _dedupe_sources([*official_sources, *retrieved_sources])
    sources = _append_financial_source(sources, financial_snapshot, topic, questions)
    sources = _enrich_and_rank_sources(sources, topic)
    _emit_progress(progress_callback, "retrieve", f"已获得 {len(sources)} 个来源。", sources)
    snapshot_has_data = financial_snapshot.status in FINANCIAL_SOURCE_STATUSES and bool(financial_snapshot.metrics)
    if len(sources) == 0 and not snapshot_has_data:
        early_stop_reason = "未获得有效来源且金融快照不可用，当前检索结果不足以支撑本次研究。"
        evidence = []
        variables = []
        questions = _mark_question_coverage(questions, evidence, topic, financial_snapshot)
        judgment = reason_and_generate(topic, evidence, questions, variables)
        actions = generate_research_actions(judgment)
        judgment = judgment.model_copy(update={"research_actions": actions})
        judgment = apply_investment_layer(topic, questions, evidence, judgment, variables)
        judgment = _attach_peer_comparison_to_judgment(judgment, financial_snapshot)
        roles = synthesize_role_outputs(topic, sources, evidence, variables, judgment)
        report = generate_report(topic, questions, sources, evidence, variables, roles, judgment)
        executive_summary = build_executive_summary(judgment, early_stop_reason)
        _emit_progress(progress_callback, "early_stop", early_stop_reason, judgment)
        _emit_progress(progress_callback, "report", "已生成早停报告。", report)
        save_topic(repo, topic)
        save_questions(repo, questions)
        save_sources(repo, sources)
        save_evidence(repo, evidence)
        save_variables(repo, variables)
        save_judgment(repo, judgment)
        save_roles(repo, roles)
        save_report(repo, report)
        return {
            "topic": topic,
            "questions": questions,
            "sources": sources,
            "evidence": evidence,
            "variables": variables,
            "roles": roles,
            "judgment": judgment,
            "auto_research_trace": [],
            "executive_summary": executive_summary,
            "financial_snapshot": financial_snapshot,
            "early_stop_reason": early_stop_reason,
            "report": report,
        }
    evidence = extract_evidence(topic, questions, sources)
    evidence = [*evidence, *_snapshot_to_evidence(financial_snapshot, topic, questions, sources, evidence)]
    _emit_progress(progress_callback, "extract", f"已提取 {len(evidence)} 条证据。", evidence)
    variables = normalize_variables(evidence)
    _emit_progress(progress_callback, "variable", f"已形成 {len(variables)} 个关键变量。", variables)
    questions = _mark_question_coverage(questions, evidence, topic, financial_snapshot)
    judgment = reason_and_generate(topic, evidence, questions, variables)
    _emit_progress(progress_callback, "reason", f"初步判断：{judgment.conclusion}", judgment)
    actions = generate_research_actions(judgment)
    judgment = judgment.model_copy(update={"research_actions": actions})
    _emit_progress(progress_callback, "action", f"已生成 {len(actions)} 个补证任务。", actions)
    auto_result = auto_research_loop(topic, questions, sources, evidence, variables, judgment, actions)
    _emit_progress(progress_callback, "auto_research", f"自动补证轮次：{len(auto_result.trace)}。", auto_result.trace)
    sources = auto_result.sources
    evidence = auto_result.evidence
    variables = auto_result.variables
    questions = _mark_question_coverage(questions, evidence, topic, financial_snapshot)
    judgment = auto_result.judgment.model_copy(update={"research_actions": auto_result.actions})
    judgment = apply_investment_layer(topic, questions, evidence, judgment, variables)
    judgment = _attach_peer_comparison_to_judgment(judgment, financial_snapshot)
    _emit_progress(progress_callback, "investment", "已生成研究流程层面的处理建议。", judgment.investment_decision)
    insufficient_after_auto_research = _effective_evidence_count(evidence) < 3
    early_stop_reason = (
        "自动补证后有效证据仍少于3条，当前只能生成低置信度研究不足报告。"
        if insufficient_after_auto_research
        else None
    )
    if early_stop_reason:
        _emit_progress(progress_callback, "early_stop", early_stop_reason, judgment)
    roles = synthesize_role_outputs(topic, sources, evidence, variables, judgment)
    _emit_progress(progress_callback, "roles", f"已生成 {len(roles)} 个角色视角。", roles)
    report = generate_report(topic, questions, sources, evidence, variables, roles, judgment)
    executive_summary = build_executive_summary(judgment, early_stop_reason)
    _emit_progress(progress_callback, "report", "已生成最终报告。", report)

    save_topic(repo, topic)
    save_questions(repo, questions)
    save_sources(repo, sources)
    save_evidence(repo, evidence)
    save_variables(repo, variables)
    save_judgment(repo, judgment)
    save_roles(repo, roles)
    save_report(repo, report)
    return {
        "topic": topic,
        "questions": questions,
        "sources": sources,
        "evidence": evidence,
        "variables": variables,
        "roles": roles,
        "judgment": judgment,
        "auto_research_trace": auto_result.trace,
        "executive_summary": executive_summary,
        "financial_snapshot": financial_snapshot,
        "early_stop_reason": early_stop_reason,
        "report": report,
    }
