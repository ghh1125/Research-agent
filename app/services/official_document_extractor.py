from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.listing_status_service import _LISTED_COMPANY_ALIASES, get_known_entity_aliases

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
        re.compile(r"(?:total\s+)?revenue\s*(?::|was|of|reached)?\s*(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
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
        re.compile(r"adjusted\s+EBITA\s*(?::|was|of)?\s*(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "net_income",
        ["net income", "净利润"],
        re.compile(r"net income\s*(?::|was|of)?\s*(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "operating_income",
        ["operating income", "经营利润"],
        re.compile(r"operating income\s*(?::|was|of)?\s*(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "operating_cash_flow",
        ["operating cash flow", "net cash provided by operating activities", "经营活动产生的现金流量净额"],
        re.compile(r"(net cash provided by operating activities|operating cash flow|经营活动产生的现金流量净额)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "free_cash_flow",
        ["free cash flow", "FCF", "自由现金流"],
        re.compile(r"(free cash flow|FCF|自由现金流)[^.。；;]{0,80}?(declined|increased|decreased|grew|增长|下降)?[^.\d。；;]{0,30}([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "capex",
        ["capital expenditures", "capex", "资本开支"],
        re.compile(r"(capital expenditures|capex|资本开支)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "margin",
        ["margin", "毛利率", "净利率"],
        re.compile(r"(gross margin|net margin|operating margin|毛利率|净利率)[^.。；;]{0,60}?([\d,]+(?:\.\d+)?)\s*%", re.I),
    ),
    (
        "diluted_eps",
        ["diluted EPS", "摊薄每股收益"],
        re.compile(r"(diluted EPS|摊薄每股收益)[^.。；;]{0,40}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)", re.I),
    ),
    (
        "cash_balance",
        ["cash and cash equivalents", "现金及现金等价物", "现金余额"],
        re.compile(r"(cash and cash equivalents|现金及现金等价物|现金余额)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "total_liabilities",
        ["total liabilities", "liabilities", "负债合计"],
        re.compile(r"(total liabilities|liabilities|负债合计)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "share_repurchase",
        ["share repurchases", "share repurchase", "股份回购"],
        re.compile(r"(share repurchases?|股份回购|回购)[^.。；;]{0,80}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "cloud_revenue",
        ["cloud revenue", "Cloud Intelligence Group revenue", "云业务收入"],
        re.compile(r"(Cloud Intelligence Group revenue|cloud revenue|云业务收入)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "aidc_revenue",
        ["AIDC revenue", "International Digital Commerce revenue"],
        re.compile(r"(AIDC revenue|International Digital Commerce[^.。；;]{0,30}revenue)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "local_services_revenue",
        ["local services revenue", "本地生活收入"],
        re.compile(r"(local services revenue|本地生活收入)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "cainiao_revenue",
        ["Cainiao revenue", "菜鸟收入"],
        re.compile(r"(Cainiao revenue|菜鸟收入)[^.。；;]{0,60}?(?:RMB|CNY|US\$|USD|HK\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|亿元|万元)?", re.I),
    ),
    (
        "order_volume",
        ["order volume", "orders", "订单量"],
        re.compile(r"(order volume|orders|订单量)[^.。；;]{0,60}?([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "monthly_active_users",
        ["monthly active users", "MAU", "月活跃用户"],
        re.compile(r"(monthly active users|MAU|月活跃用户)[^.。；;]{0,60}?([\d,]+(?:\.\d+)?)\s*(%|million|billion|亿元|万元)?", re.I),
    ),
    (
        "take_rate",
        ["take rate", "货币化率"],
        re.compile(r"(take rate|货币化率)[^.。；;]{0,60}?([\d,]+(?:\.\d+)?)\s*%", re.I),
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
    framework = "credit" if metric_name in {"operating_cash_flow", "free_cash_flow", "capex", "cash_balance", "total_liabilities"} else "financial"
    for question in questions:
        if question.framework_type == framework:
            return question.id
    for question in questions:
        if question.framework_type in {"financial", "valuation"}:
            return question.id
    return questions[0].id if questions else None


def _metric_value(match: re.Match, metric_name: str) -> tuple[float | str, str | None]:
    groups = [item for item in match.groups() if item]
    numeric = next((item for item in groups if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", item)), None)
    unit = next((item for item in reversed(groups) if item.lower() in {"%", "million", "billion", "亿元", "万元"}), None)
    if numeric is None:
        return "", unit
    try:
        value: float | str = round(float(numeric.replace(",", "")), 4)
    except Exception:
        value = numeric
    return value, unit


def _currency(raw_text: str) -> str | None:
    if re.search(r"RMB|CNY|人民幣|人民币", raw_text, flags=re.I):
        return "RMB"
    if re.search(r"US\$|USD", raw_text, flags=re.I):
        return "USD"
    if re.search(r"HK\$", raw_text, flags=re.I):
        return "HKD"
    return None


def _comparison_value(raw_text: str) -> float | str | None:
    match = re.search(r"(?:up|increased|grew|down|declined|decreased|增长|下降)[^\d]{0,20}([\d,]+(?:\.\d+)?)\s*%", raw_text, flags=re.I)
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", "")), 4)
    except Exception:
        return match.group(1)


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
    fy_quarter = re.search(r"Q([1-4])\s*FY\s*(20\d{2})", text, flags=re.I)
    if fy_quarter:
        return f"FY{fy_quarter.group(2)}Q{fy_quarter.group(1)}"
    year_quarter = re.search(r"(?:FY\s*)?(20\d{2})\s*Q([1-4])", text, flags=re.I)
    if year_quarter:
        prefix = "FY" if re.search(r"FY\s*" + year_quarter.group(1), text, flags=re.I) else ""
        return f"{prefix}{year_quarter.group(1)}Q{year_quarter.group(2)}"
    fiscal_year = re.search(r"FY\s*(20\d{2})", raw_text, flags=re.I)
    if fiscal_year:
        return f"FY{fiscal_year.group(1)}"
    match = re.search(r"(20\d{2})(?:\s|[-/年])?(?:Q([1-4])|quarter|季度|年)?", text, flags=re.I)
    if match:
        return f"{match.group(1)}Q{match.group(2)}" if match.group(2) else match.group(1)
    return None


def _raw_excerpt(text: str, match: re.Match) -> str:
    sentence_start = max(text.rfind(".", 0, match.start()), text.rfind("。", 0, match.start()), text.rfind("；", 0, match.start()), text.rfind(";", 0, match.start()))
    start = sentence_start + 1 if sentence_start >= 0 else max(0, match.start() - 24)
    sentence_end_candidates = [index for index in [text.find(".", match.end()), text.find("。", match.end()), text.find("；", match.end()), text.find(";", match.end())] if index >= 0]
    end = min(sentence_end_candidates) + 1 if sentence_end_candidates else min(len(text), match.end() + 80)
    return re.sub(r"\s+", " ", text[start:end]).strip(" .。；;")


def _format_metric_content(
    metric_name: str,
    value: float | str,
    unit: str | None,
    period: str | None,
    comparison_type: str | None,
    currency: str | None,
    raw_text: str,
) -> str:
    label = metric_name.replace("_", " ")
    value_text = f"{value:g}" if isinstance(value, float) else str(value)
    prefix = f"{currency}" if currency and unit != "%" else ""
    unit_text = unit or ""
    period_text = f" in {period}" if period else ""
    comparison_text = f" {comparison_type.upper()}" if comparison_type else ""
    if unit == "%" and comparison_type:
        return f"{label} changed {value_text}% {comparison_type.upper()}{period_text}."
    if "grew" in raw_text.lower() or "increased" in raw_text.lower() or "增长" in raw_text:
        verb = "grew"
    elif "declined" in raw_text.lower() or "decreased" in raw_text.lower() or "下降" in raw_text:
        verb = "declined"
    else:
        verb = "was"
    if verb == "was":
        return f"{label} was {prefix}{value_text} {unit_text}{comparison_text}{period_text}.".replace("  ", " ").strip()
    return f"{label} {verb} {prefix}{value_text} {unit_text}{comparison_text}{period_text}.".replace("  ", " ").strip()


def _aliases_for_entity(entity: str | None) -> set[str]:
    if not entity:
        return set()
    aliases = set(get_known_entity_aliases(entity))
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
    if "eps" in stripped.lower() or "每股收益" in stripped:
        return False
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
            period = _period(source, raw_text)
            comparison_type = _comparison_type(raw_text)
            currency = _currency(raw_text)
            quality, notes = _quality_for_metric(metric_name, raw_text, value, unit)
            is_truncated, contaminated, can_enter_main_chain, guard_notes = _main_chain_guards(raw_text, topic, value, unit)
            if not can_enter_main_chain:
                quality = min(quality, 0.2)
            content = _format_metric_content(metric_name, value, unit, period, comparison_type, currency, raw_text)
            evidence.append(
                Evidence(
                    id=f"e{start_index + len(evidence)}",
                    topic_id=topic.id,
                    question_id=_question_for_metric(metric_name, questions),
                    source_id=source.id,
                    flow_type=source.flow_type,
                    content=content[:120],
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
                    period=period,
                    segment=_SEGMENT_BY_METRIC.get(metric_name),
                    comparison_type=comparison_type,
                    yoy_qoq_flag=comparison_type,
                    comparison_value=_comparison_value(raw_text),
                    currency=currency,
                    entity=topic.entity or topic.topic,
                    source_type="official",
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
