from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_ESTIMATE_TOKENS = [
    "consensus",
    "target",
    "expects",
    "expected",
    "forecast",
    "guidance",
    "outlook",
    "预计",
    "预期",
    "目标价",
    "一致预期",
]

_DIRTY_QUOTE_TOKENS = ["登录", "注册", "menu", "首页", "copyright"]


class EvidenceQAResult(BaseModel):
    keep: bool
    fixed_metric_name: str | None = None
    fixed_metric_value: str | float | int | None = None
    fixed_unit: str | None = None
    fixed_period: str | None = None
    is_estimate: bool = False
    grounding_score: float = 0.0
    reason: str = ""


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _matches_target(text: str, aliases: list[str]) -> bool:
    compact_text = _compact(text)
    return bool(compact_text and any(_compact(alias) and _compact(alias) in compact_text for alias in aliases))


def _value_in_text(value: str | float | int | None, text: str) -> bool:
    if value is None:
        return True
    raw = str(value)
    normalized_text = text.replace(",", "")
    candidates = {raw, raw.replace(",", ""), raw.replace(".0", "")}
    try:
        candidates.add(f"{float(value):g}")
    except (TypeError, ValueError):
        pass
    return any(candidate and (candidate in text or candidate in normalized_text) for candidate in candidates)


def _period_in_text(period: str | None, text: str) -> bool:
    if not period:
        return True
    normalized_period = str(period).strip()
    if normalized_period in text:
        return True
    upper = normalized_period.upper()
    year_match = re.match(r"(?:FY)?(20\d{2})(?:Q([1-4]))?$", upper)
    if year_match:
        year = year_match.group(1)
        quarter = year_match.group(2)
        candidates = {year, f"{year}年", f"FY{year}"}
        if quarter:
            candidates.update({f"{year}Q{quarter}", f"{year}年Q{quarter}", f"FY{year}Q{quarter}"})
        return any(candidate in text for candidate in candidates)
    return False


def _quote_is_dirty(quote: str) -> bool:
    cleaned = (quote or "").strip().lower()
    if len(cleaned) < 8:
        return True
    return any(token.lower() in cleaned for token in _DIRTY_QUOTE_TOKENS)


def _metric_matches_quote(metric_name: str | None, quote: str) -> bool:
    if not metric_name:
        return True
    mapping = {
        "revenue": ["revenue", "营收", "营业收入", "收入"],
        "operating_cash_flow": ["operating cash flow", "经营现金流"],
        "free_cash_flow": ["free cash flow", "自由现金流"],
        "pe": ["pe", "市盈率"],
        "market_share": ["market share", "市占率", "市场份额"],
    }
    keywords = mapping.get(metric_name.lower())
    if not keywords:
        return True
    lowered = (quote or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def qa_candidate_evidence(
    source_metadata: dict[str, object],
    raw_chunk: str,
    candidate_evidence: Any,
    target_profile: dict[str, object] | None = None,
) -> EvidenceQAResult:
    quote = (candidate_evidence.quote or "").strip()
    chunk = raw_chunk or ""
    joined = f"{quote}\n{chunk}"
    is_estimate = any(token in joined.lower() for token in _ESTIMATE_TOKENS)
    aliases = [str(item) for item in (target_profile or {}).get("aliases", []) if str(item).strip()]
    if not aliases and (target_profile or {}).get("entity"):
        aliases = [str((target_profile or {}).get("entity"))]

    if aliases:
        source_text = "\n".join(str(source_metadata.get(key) or "") for key in ["title", "url"])
        candidate_entity = str(candidate_evidence.entity or "")
        if candidate_entity and not _matches_target(candidate_entity, aliases):
            return EvidenceQAResult(keep=False, grounding_score=0.0, reason="entity_mismatch", is_estimate=is_estimate)
        if source_text and any(token in source_text.lower() for token in ["annual report", "年度报告", "financial highlights"]) and not _matches_target(source_text, aliases):
            return EvidenceQAResult(keep=False, grounding_score=0.0, reason="entity_mismatch", is_estimate=is_estimate)

    if _quote_is_dirty(quote):
        return EvidenceQAResult(keep=False, grounding_score=0.0, reason="quote_dirty_or_too_short", is_estimate=is_estimate)
    if not _value_in_text(candidate_evidence.metric_value, joined):
        return EvidenceQAResult(keep=False, grounding_score=0.2, reason="metric_value_not_grounded", is_estimate=is_estimate)
    if not _period_in_text(candidate_evidence.period, joined):
        return EvidenceQAResult(keep=False, grounding_score=0.25, reason="period_not_grounded", is_estimate=is_estimate)
    if not _metric_matches_quote(candidate_evidence.metric_name, quote):
        return EvidenceQAResult(keep=False, grounding_score=0.3, reason="metric_semantics_mismatch", is_estimate=is_estimate)
    if re.search(r"(?:consensus|target|预计|预期)", joined, flags=re.I):
        is_estimate = True

    return EvidenceQAResult(
        keep=True,
        fixed_metric_name=candidate_evidence.metric_name,
        fixed_metric_value=candidate_evidence.metric_value,
        fixed_unit=candidate_evidence.unit,
        fixed_period=candidate_evidence.period,
        is_estimate=is_estimate,
        grounding_score=0.9 if not is_estimate else 0.75,
        reason="grounded",
    )
