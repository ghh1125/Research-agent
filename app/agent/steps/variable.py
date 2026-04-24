from __future__ import annotations

import re
from collections import defaultdict

from app.models.evidence import Evidence
from app.models.variable import ResearchVariable
from app.services.evidence_registry import build_evidence_registry

METRIC_TO_VARIABLE: dict[str, tuple[str, str]] = {
    "revenue": ("收入增长", "financial"),
    "revenue_growth": ("收入增长", "financial"),
    "revenue_yoy": ("收入增长", "financial"),
    "segment_revenue": ("收入增长", "financial"),
    "customer_management_revenue": ("收入增长", "financial"),
    "cmr": ("收入增长", "financial"),
    "gmv": ("收入增长", "financial"),
    "order_growth": ("收入增长", "financial"),
    "gross_margin": ("盈利能力", "financial"),
    "net_margin": ("盈利能力", "financial"),
    "net_income": ("盈利能力", "financial"),
    "operating_income": ("盈利能力", "financial"),
    "adjusted_ebita": ("盈利能力", "financial"),
    "ebita_margin": ("盈利能力", "financial"),
    "operating_margin": ("盈利能力", "financial"),
    "roe": ("盈利能力", "financial"),
    "roic": ("盈利能力", "financial"),
    "diluted_eps": ("盈利能力", "financial"),
    "operating_cash_flow": ("现金流质量", "financial"),
    "ocf": ("现金流质量", "financial"),
    "free_cash_flow": ("现金流质量", "financial"),
    "fcf": ("现金流质量", "financial"),
    "cash_conversion_rate": ("现金流质量", "financial"),
    "capex": ("资本开支强度", "financial"),
    "capital_expenditure": ("资本开支强度", "financial"),
    "capex_intensity": ("资本开支强度", "financial"),
    "cloud_revenue": ("云业务增长", "financial"),
    "cloud_growth": ("云业务增长", "financial"),
    "aidc_revenue": ("收入增长", "financial"),
    "market_share": ("行业竞争", "industry"),
    "peer_comparison": ("行业竞争", "industry"),
    "customer_structure": ("行业竞争", "industry"),
    "peer_rank": ("行业竞争", "industry"),
    "retention": ("护城河", "industry"),
    "mau": ("护城河", "industry"),
    "dau": ("护城河", "industry"),
    "merchant_count": ("护城河", "industry"),
    "take_rate": ("护城河", "industry"),
    "pe": ("估值锚点", "valuation"),
    "pb": ("估值锚点", "valuation"),
    "ev_ebitda": ("估值锚点", "valuation"),
    "fcf_yield": ("估值锚点", "valuation"),
    "debt_to_asset_ratio": ("负债压力", "financial"),
    "asset_liability_ratio": ("负债压力", "financial"),
    "interest_bearing_debt": ("负债压力", "financial"),
    "current_ratio": ("负债压力", "financial"),
    "cash_balance": ("负债压力", "financial"),
    "total_liabilities": ("负债压力", "financial"),
    "regulatory_risk": ("治理合规", "governance"),
}

_NEGATIVE_TOKENS = ["下降", "下滑", "减少", "承压", "恶化", "亏损", "declined", "decreased", "fell", "loss", "slowed"]
_POSITIVE_TOKENS = ["增长", "增加", "提升", "改善", "转正", "grew", "increased", "improved", "up"]
_MIXED_TOKENS = ["但是", "但", "however", "while", "mixed", "but"]

_VARIABLE_LABELS = {
    "收入增长": {
        "improving": "局部改善",
        "deteriorating": "待验证",
        "mixed": "结构分化",
        "stable": "待验证",
        "unknown": "待验证",
    },
    "盈利能力": {
        "improving": "局部改善",
        "deteriorating": "短期承压",
        "mixed": "结构分化",
        "stable": "待验证",
        "unknown": "待验证",
    },
    "现金流质量": {
        "improving": "暂稳",
        "deteriorating": "承压",
        "mixed": "结构分化",
        "stable": "暂稳",
        "unknown": "待验证",
    },
    "资本开支强度": {
        "improving": "上升",
        "deteriorating": "待验证",
        "mixed": "高位",
        "stable": "高位",
        "unknown": "待验证",
    },
    "负债压力": {
        "improving": "偏高",
        "deteriorating": "稳定",
        "mixed": "结构分化",
        "stable": "稳定",
        "unknown": "待验证",
    },
    "行业竞争": {
        "improving": "局部改善",
        "deteriorating": "短期承压",
        "mixed": "结构分化",
        "stable": "待验证",
        "unknown": "待验证",
    },
}


def _normalize_metric_name(metric_name: str | None) -> str | None:
    if not metric_name:
        return None
    normalized = re.sub(r"[\s\-/]+", "_", metric_name.strip())
    aliases = {
        "pe_ttm": "pe",
        "p_e": "pe",
        "pb_ratio": "pb",
        "ev/ebitda": "ev_ebitda",
        "ev_to_ebitda": "ev_ebitda",
        "customer_management_revenue_growth": "customer_management_revenue",
        "capital_expenditures": "capital_expenditure",
    }
    lowered = normalized.lower()
    return aliases.get(lowered, lowered)


def _can_drive_variable(item: Evidence) -> bool:
    if item.evidence_type != "data":
        return False
    metric_name = _normalize_metric_name(item.metric_name)
    if metric_name not in METRIC_TO_VARIABLE:
        return False
    return item.metric_value is not None


def _period_sort_key(period: str | None) -> tuple[int, str]:
    if not period:
        return (99, "")
    text = str(period).upper()
    match = re.search(r"FY(\d{4})(?:Q(\d))?", text)
    if not match:
        return (99, text)
    year = int(match.group(1))
    quarter = int(match.group(2) or 5)
    return (year * 10 + quarter, text)


def _comparable_period_count(items: list[Evidence]) -> int:
    periods = {str(item.period).strip() for item in items if item.period}
    return len(periods)


def _normalize_numeric(value: str | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _infer_direction(items: list[Evidence]) -> tuple[str, list[str]]:
    positive = 0
    negative = 0
    notes: list[str] = []
    comparable_periods = _comparable_period_count(items)
    ordered = sorted(items, key=lambda item: _period_sort_key(item.period))
    numeric_values = [_normalize_numeric(item.metric_value) for item in ordered]
    comparable_values = [value for value in numeric_values if value is not None]

    yoy_or_qoq_values = [
        _normalize_numeric(item.metric_value)
        for item in items
        if (item.comparison_type or item.yoy_qoq_flag or "").lower() in {"yoy", "qoq"}
        and _normalize_numeric(item.metric_value) is not None
    ]
    if comparable_periods >= 2 and len(comparable_values) >= 2:
        deltas = [
            current - previous
            for previous, current in zip(comparable_values, comparable_values[1:])
        ]
        if all(delta > 0 for delta in deltas):
            positive += 1
        elif all(delta < 0 for delta in deltas):
            negative += 1
        elif any(delta != 0 for delta in deltas):
            positive += 1
            negative += 1
    elif yoy_or_qoq_values:
        if all(value > 0 for value in yoy_or_qoq_values):
            positive += 1
            notes.append("仅基于单期同比/环比结构化字段，方向标签已降级为弱判断。")
        elif all(value < 0 for value in yoy_or_qoq_values):
            negative += 1
            notes.append("仅基于单期同比/环比结构化字段，方向标签已降级为弱判断。")
        else:
            positive += 1
            negative += 1
            notes.append("同比/环比结构化字段出现正反混合，按结构分化处理。")
    else:
        text = " ".join(item.content.lower() for item in items)
        if any(token.lower() in text for token in _POSITIVE_TOKENS):
            positive += 1
            notes.append("缺少序列数据，使用结构化证据文本中的弱正向信号生成解释标签。")
        if any(token.lower() in text for token in _NEGATIVE_TOKENS):
            negative += 1
            notes.append("缺少序列数据，使用结构化证据文本中的弱负向信号生成解释标签。")
        if not positive and not negative:
            notes.append("缺少可比期间或趋势序列，方向仅保留为待验证。")

    if positive and negative:
        notes.append("结构化指标出现正反混合，需在判断层保留边界。")
        return "mixed", notes
    if positive:
        return "improving", notes
    if negative:
        return "deteriorating", notes
    return "unknown", notes


def _direction_label(variable_name: str, direction: str) -> str:
    mapping = _VARIABLE_LABELS.get(variable_name, _VARIABLE_LABELS["行业竞争"])
    return mapping.get(direction, mapping["unknown"])


def _summarize_variable(items: list[Evidence]) -> str:
    return "；".join(item.content for item in items[:3])


def normalize_variables(evidence: list[Evidence]) -> list[ResearchVariable]:
    """Create variables only from structured metric evidence.

    Narrative evidence, long summaries and keyword-only text no longer drive variables.
    """

    registry = build_evidence_registry(evidence)
    grouped: dict[tuple[str, str], list[Evidence]] = defaultdict(list)
    variable_slots: dict[str, set[str]] = defaultdict(set)
    for item in registry.evidence:
        if not _can_drive_variable(item):
            continue
        metric_name = _normalize_metric_name(item.metric_name)
        if metric_name is None:
            continue
        name, category = METRIC_TO_VARIABLE[metric_name]
        if len(variable_slots[item.id]) >= 2 or name in variable_slots[item.id]:
            continue
        variable_slots[item.id].add(name)
        grouped[(name, category)].append(item)

    order = {"financial": 0, "industry": 1, "governance": 2, "valuation": 3}
    variables: list[ResearchVariable] = []
    for (name, category), items in grouped.items():
        evidence_ids = list(dict.fromkeys(item.id for item in items))[:6]
        direction, direction_notes = _infer_direction(items)
        variables.append(
            ResearchVariable(
                name=name,
                category=category,
                value_summary=_summarize_variable(items),
                direction=direction,
                direction_label=_direction_label(name, direction),
                evidence_ids=evidence_ids,
                direction_notes=direction_notes,
            )
        )
    return sorted(variables, key=lambda item: (order.get(item.category, 99), item.name))[:8]
