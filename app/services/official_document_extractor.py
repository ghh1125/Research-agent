from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.listing_status_service import _LISTED_COMPANY_ALIASES

_OFFICIAL_ORIGINS = {"company_ir", "official_disclosure", "regulatory"}

_PAGE_CLASSIFIERS = {
    "results_release": ["quarterly results", "financial results", "results announcement", "业绩公告", "季度业绩"],
    "financial_summary": ["revenue", "adjusted ebita", "operating income", "free cash flow", "营业收入", "主要会计数据"],
    "segment_table": ["cloud", "aidc", "cainiao", "local services", "segment", "分部"],
    "cashflow": ["operating cash flow", "free cash flow", "capital expenditures", "经营现金流", "自由现金流"],
    "share_repurchase": ["share repurchase", "repurchases", "回购"],
    "guidance": ["guidance", "outlook", "指引", "展望"],
    "risk": ["risk", "uncertainty", "风险"],
}

_METRIC_PATTERNS = [
    (
        "revenue",
        ["revenue", "total revenue", "营业收入", "总收入"],
        re.compile(r"(?:total\s+)?revenue\s+(?:was|of|reached)?\s*(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "cmr",
        ["customer management revenue", "CMR", "客户管理收入"],
        re.compile(r"(customer management revenue|CMR|客户管理收入)[^.。；;]{0,80}?(increased|decreased|grew|declined|增长|下降)?[^.\d。；;]{0,30}([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "gmv_signal",
        ["GMV", "gross merchandise volume"],
        re.compile(r"(GMV|gross merchandise volume)[^.。；;]{0,80}?([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "adjusted_ebita",
        ["adjusted EBITA", "经调整 EBITA"],
        re.compile(r"adjusted\s+EBITA\s+(?:was|of)?\s*(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "operating_income",
        ["operating income", "经营利润"],
        re.compile(r"operating income\s+(?:was|of)?\s*(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "operating_cash_flow",
        ["operating cash flow", "net cash provided by operating activities", "经营活动产生的现金流量净额"],
        re.compile(r"(net cash provided by operating activities|operating cash flow|经营活动产生的现金流量净额)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "free_cash_flow",
        ["free cash flow", "FCF", "自由现金流"],
        re.compile(r"(free cash flow|FCF|自由现金流)[^.。；;]{0,80}?(declined|increased|decreased|grew|增长|下降)?[^.\d。；;]{0,30}([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "capex",
        ["capital expenditures", "capex", "资本开支"],
        re.compile(r"(capital expenditures|capex|资本开支)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "share_repurchase",
        ["share repurchases", "share repurchase", "股份回购"],
        re.compile(r"(share repurchases?|股份回购|回购)[^.。；;]{0,80}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "cloud_revenue",
        ["cloud revenue", "Cloud Intelligence Group revenue", "云业务收入"],
        re.compile(r"(Cloud Intelligence Group revenue|cloud revenue|云业务收入)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "aidc_revenue",
        ["AIDC revenue", "International Digital Commerce revenue"],
        re.compile(r"(AIDC revenue|International Digital Commerce[^.。；;]{0,30}revenue)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "local_services_revenue",
        ["local services revenue", "本地生活收入"],
        re.compile(r"(local services revenue|本地生活收入)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "cainiao_revenue",
        ["Cainiao revenue", "菜鸟收入"],
        re.compile(r"(Cainiao revenue|菜鸟收入)[^.。；;]{0,60}?(?:RMB|US\$|USD|HK\$)?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
]

_SEGMENT_BY_METRIC = {
    "cloud_revenue": "Cloud Intelligence Group",
    "aidc_revenue": "AIDC",
    "local_services_revenue": "Local Services",
    "cainiao_revenue": "Cainiao",
}

_PEER_CONTEXT_TOKENS = [
    "peer",
    "peers",
    "competitor",
    "competitors",
    "同行",
    "可比公司",
    "竞争对手",
    "peer comparison",
]

_TRUNCATED_OFFICIAL_PATTERNS = [
    re.compile(r"(?:to|至)\s*(?:RMB|人民幣|人民币|US\$|USD|HK\$)\s*\d{1,3}\s*$", re.I),
    re.compile(r"^(?:ent|ment|venue|come|flow)\s+", re.I),
]


def is_official_financial_source(source: Source) -> bool:
    return bool(source.is_official_pdf or source.source_origin_type in _OFFICIAL_ORIGINS or source.tier.value == "official")


def classify_official_document_page(text: str) -> str:
    lowered = (text or "").lower()
    best_type = "financial_summary"
    best_hits = 0
    for page_type, tokens in _PAGE_CLASSIFIERS.items():
        hits = sum(1 for token in tokens if token.lower() in lowered)
        if hits > best_hits:
            best_type = page_type
            best_hits = hits
    return best_type


def _source_text(source: Source) -> str:
    return source.enriched_content or source.fetched_content or source.content


def _question_for_metric(metric_name: str, questions: list[Question]) -> str | None:
    framework = "credit" if metric_name in {"operating_cash_flow", "free_cash_flow", "capex"} else "financial"
    for question in questions:
        if question.framework_type == framework:
            return question.id
    for question in questions:
        if question.framework_type in {"financial", "valuation"}:
            return question.id
    return questions[0].id if questions else None


def _metric_value(match: re.Match, metric_name: str) -> tuple[float | str, str | None]:
    groups = [item for item in match.groups() if item]
    numeric = next((item for item in groups if re.fullmatch(r"[\d,]+(?:\.\d+)?", item)), None)
    unit = next((item for item in reversed(groups) if item.lower() in {"%", "million", "billion", "亿元", "万元"}), None)
    if numeric is None:
        return "", unit
    try:
        value: float | str = round(float(numeric.replace(",", "")), 4)
    except Exception:
        value = numeric
    return value, unit


def _comparison_type(raw_text: str) -> str | None:
    lowered = raw_text.lower()
    if "year-over-year" in lowered or "yoy" in lowered or "同比" in raw_text:
        return "yoy"
    if "quarter-over-quarter" in lowered or "qoq" in lowered or "环比" in raw_text:
        return "qoq"
    if "ttm" in lowered:
        return "ttm"
    return None


def _period(source: Source, raw_text: str) -> str | None:
    text = f"{source.title} {source.published_at or ''} {raw_text}"
    match = re.search(r"(20\d{2})(?:\s|[-/年])?(?:Q([1-4])|quarter|季度|年)?", text, flags=re.I)
    if match:
        return f"{match.group(1)}Q{match.group(2)}" if match.group(2) else match.group(1)
    return None


def _raw_excerpt(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 24)
    end = min(len(text), match.end() + 80)
    return re.sub(r"\s+", " ", text[start:end]).strip(" .。；;")


def _aliases_for_entity(entity: str | None) -> set[str]:
    if not entity:
        return set()
    aliases = {entity}
    aliases.update(_LISTED_COMPANY_ALIASES.get(entity, []))
    lowered_entity = entity.lower()
    for canonical, candidate_aliases in _LISTED_COMPANY_ALIASES.items():
        if canonical == entity or any(alias.lower() == lowered_entity for alias in candidate_aliases):
            aliases.add(canonical)
            aliases.update(candidate_aliases)
    return {alias for alias in aliases if alias}


def _contains_peer_context(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered or token in text for token in _PEER_CONTEXT_TOKENS)


def _cross_entity_contamination(raw_text: str, topic: Topic) -> bool:
    if _contains_peer_context(raw_text):
        return False
    target_aliases = _aliases_for_entity(topic.entity or topic.topic)
    lowered = raw_text.lower()
    target_hit = any(alias.lower() in lowered for alias in target_aliases)
    if not target_hit and target_aliases:
        # If a row does not name the target, do not flag solely on that basis; table rows often omit company name.
        target_hit = True
    for canonical, aliases in _LISTED_COMPANY_ALIASES.items():
        if canonical in target_aliases:
            continue
        if any(alias and alias.lower() in lowered for alias in aliases):
            return target_hit
    return False


def _is_truncated_official_metric(raw_text: str, value: float | str, unit: str | None) -> bool:
    stripped = re.sub(r"\s+", " ", raw_text or "").strip()
    if not stripped:
        return True
    if any(pattern.search(stripped) for pattern in _TRUNCATED_OFFICIAL_PATTERNS):
        return True
    if value == "":
        return True
    if unit is None and re.search(r"(RMB|人民幣|人民币|US\$|USD|HK\$)\s*\d{1,3}(?:\D|$)", stripped, flags=re.I):
        return True
    return False


def _quality_for_metric(metric_name: str, raw_text: str, value: float | str, unit: str | None) -> tuple[float, list[str]]:
    notes = ["official_structured_financial", f"metric={metric_name}"]
    complete_value = bool(value != "" and unit and unit != "%")
    if complete_value:
        return 0.9, [*notes, "complete_official_metric"]
    if unit == "%" or _comparison_type(raw_text):
        return 0.7, [*notes, "semi_structured_official_metric", "requires_cross_check"]
    return 0.55, [*notes, "partial_official_metric", "requires_cross_check"]


def _main_chain_guards(raw_text: str, topic: Topic, value: float | str, unit: str | None) -> tuple[bool, bool, bool, list[str]]:
    notes: list[str] = []
    is_truncated = _is_truncated_official_metric(raw_text, value, unit)
    contaminated = _cross_entity_contamination(raw_text, topic)
    can_enter = not is_truncated and not contaminated
    if is_truncated:
        notes.append("official_metric_truncated_or_fragmented")
    if contaminated:
        notes.append("cross_entity_contamination")
    if not can_enter:
        notes.append("excluded_from_main_chain")
    return is_truncated, contaminated, can_enter, notes


def extract_official_financial_evidence(
    source: Source,
    topic: Topic,
    questions: list[Question],
    start_index: int = 1,
) -> list[Evidence]:
    if not is_official_financial_source(source):
        return []

    text = _source_text(source)
    if not text.strip():
        return []

    timestamp = datetime.now(timezone.utc).isoformat()
    page_type = classify_official_document_page(text)
    evidence: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    for metric_name, _aliases, pattern in _METRIC_PATTERNS:
        for match in pattern.finditer(text):
            raw_text = _raw_excerpt(text, match)
            key = (metric_name, raw_text.lower())
            if key in seen:
                continue
            seen.add(key)
            value, unit = _metric_value(match, metric_name)
            quality, notes = _quality_for_metric(metric_name, raw_text, value, unit)
            is_truncated, contaminated, can_enter_main_chain, guard_notes = _main_chain_guards(raw_text, topic, value, unit)
            if not can_enter_main_chain:
                quality = min(quality, 0.2)
            evidence.append(
                Evidence(
                    id=f"e{start_index + len(evidence)}",
                    topic_id=topic.id,
                    question_id=_question_for_metric(metric_name, questions),
                    source_id=source.id,
                    flow_type=source.flow_type,
                    content=raw_text,
                    evidence_type="data",
                    stance="neutral",
                    grounded=True,
                    is_noise=False,
                    is_truncated=is_truncated,
                    cross_entity_contamination=contaminated,
                    can_enter_main_chain=can_enter_main_chain,
                    quality_score=quality,
                    quality_notes=[*notes, *guard_notes, f"page_type={page_type}"],
                    source_tier=source.tier.value,
                    source_score=source.source_score,
                    relevance_score=0.9,
                    clarity_score=0.9,
                    recency_score=1.0,
                    evidence_score=quality,
                    metric_name=metric_name,
                    metric_value=value,
                    unit=unit,
                    period=_period(source, raw_text),
                    segment=_SEGMENT_BY_METRIC.get(metric_name),
                    comparison_type=_comparison_type(raw_text),
                    source_page=source.parsed_pages[0].get("page_number") if source.parsed_pages else None,
                    source_table_id=f"{source.id}:{page_type}:{metric_name}",
                    extraction_confidence=quality,
                    timestamp=timestamp,
                )
            )
    return evidence


def official_parse_metrics(sources: list[Source], evidence: list[Evidence]) -> dict[str, float]:
    official_sources = [source for source in sources if is_official_financial_source(source)]
    if not official_sources:
        return {
            "official_source_parse_rate": 0.0,
            "official_source_to_evidence_rate": 0.0,
            "official_evidence_used_in_judgment_rate": 0.0,
        }
    parsed_sources = [source for source in official_sources if source.pdf_parse_status == "parsed" or source.fetched_content or source.enriched_content or source.content]
    evidence_source_ids = {item.source_id for item in evidence if "official_structured_financial" in item.quality_notes}
    return {
        "official_source_parse_rate": round(len(parsed_sources) / len(official_sources), 3),
        "official_source_to_evidence_rate": round(len(evidence_source_ids) / len(official_sources), 3),
        "official_evidence_used_in_judgment_rate": 0.0,
    }
