from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from app.agent.steps.extract import extract_evidence
from app.agent.steps.reason import reason_and_generate
from app.agent.steps.variable import normalize_variables
from app.agent.utils.query_builder import ENGLISH_ENTITY_ALIASES
from app.config import get_settings
from app.models.evidence import Evidence
from app.models.judgment import AutoResearchTrace, Judgment, ResearchAction
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.models.variable import ResearchVariable
from app.services.content_fetcher import enrich_sources_content
from app.services.evidence_engine import (
    classify_source_origin,
    classify_tier_from_origin,
    contains_target_entity,
    is_recent_source,
    rank_sources,
)
from app.services.pdf_service import enrich_pdf_sources
from app.services.search_service import search


@dataclass(frozen=True)
class AutoResearchResult:
    sources: list[Source]
    evidence: list[Evidence]
    variables: list[ResearchVariable]
    judgment: Judgment
    actions: list[ResearchAction]
    trace: list[AutoResearchTrace]


def _priority_rank(action: ResearchAction) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(action.priority, 9)


def choose_top_actions(actions: list[ResearchAction], limit: int = 2) -> list[ResearchAction]:
    """Pick bounded补证 tasks, preferring high-priority actions."""

    actionable = [item for item in actions if item.status in {"pending", "running"}]
    high_priority = [item for item in actionable if item.priority == "high"]
    pool = high_priority or [item for item in actionable if item.priority == "medium"] or actionable
    return sorted(pool, key=lambda item: (_priority_rank(item), item.id))[:limit]


def _render_query(template: str, topic: Topic) -> str:
    entity = topic.entity or topic.topic
    return template.format(entity=entity, topic=topic.topic).strip()


def _existing_urls(sources: list[Source]) -> set[str]:
    return {item.url for item in sources if item.url}


def _is_pdf_url(url: str | None, title: str) -> bool:
    text = f"{url or ''} {title}".lower()
    return ".pdf" in text or "pdf" in text


def _official_target_requested(action: ResearchAction) -> bool:
    target_text = " ".join(action.source_targets + action.target_sources + action.required_data).lower()
    return any(
        token in target_text
        for token in ["official", "filing", "investor", "regulatory", "annual report", "财报", "公告"]
    )


def _entity_name_candidates(topic: Topic) -> list[str]:
    entity = topic.entity or topic.topic
    candidates = [entity]
    english_alias = ENGLISH_ENTITY_ALIASES.get(entity)
    if english_alias:
        candidates.insert(0, english_alias)
    symbol = getattr(topic, "symbol", None)
    if symbol:
        candidates.append(str(symbol).split(".")[0])
    deduped: list[str] = []
    for item in candidates:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _domain_slug_candidates(topic: Topic) -> list[str]:
    slugs: list[str] = []
    for name in _entity_name_candidates(topic):
        ascii_name = "".join(char.lower() if char.isalnum() and ord(char) < 128 else " " for char in name)
        tokens = [token for token in ascii_name.split() if token not in {"group", "holdings", "holding", "inc", "corp", "corporation", "limited", "ltd", "com"}]
        if not tokens:
            continue
        base = "".join(tokens)
        spaced = "-".join(tokens)
        for candidate in [base, spaced, f"{base}group", f"{base}holdings"]:
            if len(candidate) >= 3 and candidate not in slugs:
                slugs.append(candidate)
    return slugs[:6]


def build_official_target_candidates(
    topic: Topic,
    questions: list[Question],
    action: ResearchAction,
    start_index: int = 1,
) -> list[Source]:
    """Generate generic issuer/regulatory target URLs without company-specific whitelists."""

    if not _official_target_requested(action):
        return []

    question_id = action.question_id or (questions[0].id if questions else "q_auto")
    entity_names = _entity_name_candidates(topic)
    search_name = entity_names[0] if entity_names else topic.topic
    quoted_name = quote_plus(search_name)
    market_type = getattr(topic, "market_type", "other")
    candidates: list[tuple[str, str, str, str]] = []

    if market_type in {"US", "other"}:
        candidates.append(
            (
                "SEC EDGAR company filings",
                f"https://www.sec.gov/edgar/search/#/q={quoted_name}",
                "regulatory",
                "sec_filing_search",
            )
        )
    if market_type in {"HK", "other"}:
        candidates.append(
            (
                "HKEXnews issuer filings",
                f"https://www.hkexnews.hk/search/titlesearch.xhtml?lang=en&keyword={quoted_name}",
                "regulatory",
                "hkex_filing_search",
            )
        )

    for slug in _domain_slug_candidates(topic):
        candidates.extend(
            [
                (f"{search_name} investor relations", f"https://ir.{slug}.com", "company_ir", "ir_subdomain"),
                (f"{search_name} investors", f"https://investors.{slug}.com", "company_ir", "investors_subdomain"),
                (f"{search_name} investor relations", f"https://www.{slug}.com/investor-relations", "company_ir", "investor_path"),
                (f"{search_name} financial reports", f"https://www.{slug}.com/investors", "company_ir", "investors_path"),
                (f"{search_name} newsroom", f"https://www.{slug}.com/newsroom", "company_ir", "corporate_newsroom"),
            ]
        )

    sources: list[Source] = []
    seen_urls: set[str] = set()
    for title, url, origin, reason in candidates:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(
            Source(
                id=f"s{start_index + len(sources)}",
                question_id=question_id,
                flow_type="fact",
                search_query=action.search_query or (action.query_templates[0] if action.query_templates else None),
                title=title,
                url=url,
                source_type="regulatory" if origin == "regulatory" else "company",
                provider="official_target_discovery",
                source_origin_type=origin,
                credibility_tier="tier1",
                tier=SourceTier.TIER1,
                source_score=0.82 if origin == "company_ir" else 0.9,
                source_rank_reason=reason,
                contains_entity=True,
                is_recent=True,
                is_official_target_source=True,
                target_reason=reason,
                content=(
                    f"{search_name} official target source candidate for investor relations, "
                    "annual report, quarterly results, earnings release, filing, revenue, "
                    "operating cash flow, free cash flow, capex, and presentation documents."
                ),
            )
        )
    return sources


def mark_official_target_sources(
    sources: list[Source],
    topic: Topic,
    action: ResearchAction,
) -> tuple[list[Source], dict[str, int]]:
    """Mark which retrieved sources are eligible official targets for an action."""

    marked: list[Source] = []
    stats = {"official_candidates": len(sources), "targetable": 0, "rejected": 0}
    wants_official = _official_target_requested(action)
    for source in sources:
        origin = source.source_origin_type
        if origin == "unknown":
            origin = classify_source_origin(
                url=source.url,
                title=source.title,
                source_type=source.source_type,
                content=source.content,
                entity=topic.entity,
            )
        blocked_role = origin in {"aggregator", "professional_media", "research_media", "community", "self_media"}
        is_targetable = bool(
            wants_official
            and not blocked_role
            and (
                source.is_official_target_source
                or source.is_official_pdf
                or origin in {"company_ir", "official_disclosure", "regulatory"}
                or source.tier == SourceTier.TIER1
            )
        )
        if is_targetable:
            stats["targetable"] += 1
            marked.append(
                source.model_copy(
                    update={
                        "is_official_target_source": True,
                        "target_reason": source.target_reason or origin,
                        "rejected_reason": None,
                    }
                )
            )
        else:
            rejected_reason = "not_official_action_target" if not wants_official else "site_role_not_official"
            stats["rejected"] += 1
            marked.append(
                source.model_copy(
                    update={
                        "is_official_target_source": False,
                        "rejected_reason": source.rejected_reason or rejected_reason,
                    }
                )
            )
    return marked, stats


def _official_target_stats(sources: list[Source]) -> dict[str, int]:
    return {
        "OFFICIAL_SOURCES_FOUND": len(
            [
                item
                for item in sources
                if item.source_origin_type in {"company_ir", "official_disclosure", "regulatory"}
                or item.is_official_pdf
                or item.is_official_target_source
            ]
        ),
        "OFFICIAL_SOURCES_ACCEPTED": len([item for item in sources if item.is_official_target_source]),
        "OFFICIAL_SOURCES_REJECTED": len([item for item in sources if item.rejected_reason]),
    }


def _official_evidence_stats(evidence: list[Evidence]) -> dict[str, int]:
    official_items = [
        item
        for item in evidence
        if item.source_tier == "official" or "official_structured_financial" in (item.quality_notes or [])
    ]
    return {
        "OFFICIAL_EVIDENCE_EXTRACTED": len([item for item in official_items if item.can_enter_main_chain]),
        "OFFICIAL_EVIDENCE_REJECTED": len([item for item in official_items if not item.can_enter_main_chain]),
    }


def _variable_stats(evidence: list[Evidence], variables: list[ResearchVariable]) -> dict[str, int | str]:
    accepted_ids = {evidence_id for variable in variables for evidence_id in variable.evidence_ids}
    rejected = len([item for item in evidence if item.id not in accepted_ids])
    return {
        "VARIABLE_INPUT_COUNT": len(evidence),
        "VARIABLE_ACCEPTED_COUNT": len(accepted_ids),
        "VARIABLE_REJECTED_REASON": f"not_strict_variable_input={rejected}",
    }


def retrieve_from_action(
    topic: Topic,
    questions: list[Question],
    action: ResearchAction,
    existing_sources: list[Source],
    start_index: int,
    max_sources: int = 4,
    search_fn=search,
) -> tuple[list[Source], list[str]]:
    """Run real search queries generated by one structured research action."""

    question_id = action.question_id or (questions[0].id if questions else "q_auto")
    seen_urls = _existing_urls(existing_sources)
    sources: list[Source] = []
    executed_queries: list[str] = []
    source_counter = start_index
    per_query_limit = max(1, min(get_settings().retrieve_per_question_limit, 3))

    for template in action.query_templates:
        query = _render_query(template, topic)
        if not query or query in executed_queries:
            continue
        executed_queries.append(query)
        try:
            results = search_fn(query)
        except RuntimeError:
            continue
        collected_for_query = 0
        for result in results:
            url = (result.get("url") or "").strip() or None
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            origin = classify_source_origin(
                url=url,
                title=result["title"],
                source_type=result["source_type"],
                content=result["content"],
                entity=topic.entity,
            )
            tier = classify_tier_from_origin(origin)
            draft = Source(
                id=f"s{source_counter}",
                question_id=question_id,
                flow_type="fact" if "official" in " ".join(action.source_targets).lower() else "risk",
                search_query=query,
                url=url,
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
                is_pdf=_is_pdf_url(url, result["title"]),
                pdf_parse_status="not_attempted" if _is_pdf_url(url, result["title"]) else "not_pdf",
                content=result["content"],
            )
            sources.append(
                draft.model_copy(
                    update={
                        "contains_entity": contains_target_entity(
                            f"{draft.title} {draft.content[:1200]}",
                            topic,
                        ),
                        "is_recent": is_recent_source(draft),
                    }
                )
            )
            source_counter += 1
            collected_for_query += 1
            if len(sources) >= max_sources or collected_for_query >= per_query_limit:
                break
        if len(sources) >= max_sources:
            break

    sources, _target_stats = mark_official_target_sources(sources, topic, action)
    if _official_target_requested(action) and not any(item.is_official_target_source for item in sources):
        remaining_slots = max(max_sources - len(sources), 2)
        target_candidates = build_official_target_candidates(
            topic,
            questions,
            action,
            start_index=source_counter,
        )[:remaining_slots]
        sources.extend(target_candidates)

    ranked_sources = rank_sources(enrich_pdf_sources(sources), topic, max_sources)
    enriched_sources = enrich_sources_content(ranked_sources)
    ranked_enriched = rank_sources(enriched_sources, topic, max_sources)
    return ranked_enriched, executed_queries


def _renumber_new_evidence(new_evidence: list[Evidence], start_index: int) -> list[Evidence]:
    return [
        item.model_copy(update={"id": f"e{index}"})
        for index, item in enumerate(new_evidence, start=start_index)
    ]


def _merge_evidence(existing: list[Evidence], new_items: list[Evidence]) -> list[Evidence]:
    seen = {(item.source_id, item.content) for item in existing}
    merged = list(existing)
    for item in new_items:
        key = (item.source_id, item.content)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _mark_action_status(
    actions: list[ResearchAction],
    selected: list[ResearchAction],
    status: str,
    status_reason: str | None = None,
) -> list[ResearchAction]:
    selected_ids = {item.id for item in selected}
    return [
        item.model_copy(update={"status": status, "status_reason": status_reason})
        if item.id in selected_ids
        else item
        for item in actions
    ]


def _no_source_status(selected_actions: list[ResearchAction], executed_queries: list[str]) -> tuple[str, str]:
    if not executed_queries:
        return "skipped_duplicate_query", "因与已执行查询高度重复，未重复检索。"
    target_text = " ".join(target for action in selected_actions for target in action.source_targets + action.target_sources).lower()
    if "official" in target_text or "investor relations" in target_text or "filing" in target_text:
        return "skipped_no_official_target_source", "缺少可用官方目标源，暂未形成新增来源。"
    return "attempted_no_new_evidence", "已执行检索，但没有新增可用来源或证据。"


def auto_research_loop(
    topic: Topic,
    questions: list[Question],
    sources: list[Source],
    evidence: list[Evidence],
    variables: list[ResearchVariable],
    judgment: Judgment,
    actions: list[ResearchAction],
    max_rounds: int = 1,
    action_limit: int = 2,
    retrieve_fn=retrieve_from_action,
) -> AutoResearchResult:
    """Bounded automatic补证 loop for low-confidence judgments."""

    trace: list[AutoResearchTrace] = []
    current_sources = list(sources)
    current_evidence = list(evidence)
    current_variables = list(variables)
    current_judgment = judgment
    current_actions = list(actions)

    for round_index in range(1, max_rounds + 1):
        if current_judgment.confidence != "low":
            trace.append(
                AutoResearchTrace(
                    round_index=round_index,
                    triggered=False,
                    effectiveness_status="not_triggered",
                    stop_reason=f"confidence={current_judgment.confidence}，无需自动补证",
                )
            )
            break

        selected_actions = choose_top_actions(current_actions, limit=action_limit)
        if not selected_actions:
            trace.append(
                AutoResearchTrace(
                    round_index=round_index,
                    triggered=False,
                    effectiveness_status="not_triggered",
                    stop_reason="没有可执行的结构化研究任务",
                )
            )
            break

        current_actions = _mark_action_status(current_actions, selected_actions, "running")
        round_sources: list[Source] = []
        executed_queries: list[str] = []
        for action in selected_actions:
            new_sources, queries = retrieve_fn(
                topic,
                questions,
                action,
                current_sources + round_sources,
                start_index=len(current_sources) + len(round_sources) + 1,
            )
            round_sources.extend(new_sources)
            executed_queries.extend(queries)

        if not round_sources:
            action_status, action_reason = _no_source_status(selected_actions, executed_queries)
            current_actions = _mark_action_status(current_actions, selected_actions, action_status, action_reason)
            trace.append(
                AutoResearchTrace(
                    round_index=round_index,
                    triggered=True,
                    selected_action_ids=[item.id for item in selected_actions],
                    executed_queries=executed_queries,
                    effectiveness_status="no_new_data",
                    stop_reason="自动补证未检索到新增可用来源",
                    debug_observability={
                        **_official_target_stats([]),
                        **_official_evidence_stats([]),
                        **_variable_stats(current_evidence, current_variables),
                    },
                )
            )
            break

        extracted = extract_evidence(topic, questions, round_sources)
        renumbered = _renumber_new_evidence(extracted, len(current_evidence) + 1)
        if not renumbered:
            current_actions = _mark_action_status(
                current_actions,
                selected_actions,
                "attempted_low_quality_only",
                "已检索但仅新增低质量证据，未纳入判断。",
            )
            current_sources.extend(round_sources)
            trace.append(
                AutoResearchTrace(
                    round_index=round_index,
                    triggered=True,
                    selected_action_ids=[item.id for item in selected_actions],
                    executed_queries=executed_queries,
                    new_source_ids=[item.id for item in round_sources],
                    effectiveness_status="no_new_data",
                    stop_reason="新增来源未提取出有效证据",
                    debug_observability={
                        **_official_target_stats(round_sources),
                        **_official_evidence_stats([]),
                        **_variable_stats(current_evidence, current_variables),
                    },
                )
            )
            break

        target_gap_question_ids = {
            item.question_id
            for item in selected_actions
            if item.question_id
        }
        covered_gap_question_ids = sorted(
            {
                item.question_id
                for item in renumbered
                if item.question_id and item.question_id in target_gap_question_ids
            }
        )
        is_effective = not target_gap_question_ids or bool(covered_gap_question_ids)
        current_sources.extend(round_sources)
        current_evidence = _merge_evidence(current_evidence, renumbered)
        if is_effective:
            current_variables = normalize_variables(current_evidence)
            current_judgment = reason_and_generate(topic, current_evidence, questions, current_variables)
            current_actions = current_judgment.research_actions
        else:
            current_actions = _mark_action_status(
                current_actions,
                selected_actions,
                "attempted_but_not_covering_gap",
                "已执行，但未覆盖目标证据缺口。",
            )
        trace.append(
            AutoResearchTrace(
                round_index=round_index,
                triggered=True,
                selected_action_ids=[item.id for item in selected_actions],
                executed_queries=executed_queries,
                new_source_ids=[item.id for item in round_sources],
                new_evidence_ids=[item.id for item in renumbered],
                covered_gap_question_ids=covered_gap_question_ids,
                effectiveness_status="effective" if is_effective else "ineffective",
                stop_reason=(
                    f"完成本轮补证，final_confidence={current_judgment.confidence}"
                    if is_effective
                    else "新增证据未覆盖本轮目标证据缺口，保持原判断置信度"
                ),
                debug_observability={
                    **_official_target_stats(round_sources),
                    **_official_evidence_stats(renumbered),
                    **_variable_stats(current_evidence, current_variables),
                },
            )
        )

        if not is_effective:
            break

        if current_judgment.confidence != "low":
            break

    return AutoResearchResult(
        sources=current_sources,
        evidence=current_evidence,
        variables=current_variables,
        judgment=current_judgment,
        actions=current_actions,
        trace=trace,
    )
