from __future__ import annotations

import re


STATUS_LABELS = {
    "Under Review": "仍需补证",
    "Improving": "有改善迹象，但仍需验证",
    "Stable": "暂稳",
    "Healthy": "结构较健康",
    "Observed": "已观察到",
    "Tightening": "边际承压",
    "Unsustainable": "难以持续",
    "Missing": "待补证",
}

TIER_LABELS = {
    "official": "官方来源",
    "professional": "专业来源",
    "content": "普通内容来源",
}

SOURCE_TYPE_LABELS = {
    "official_disclosure": "官方披露",
    "company_ir": "公司投资者关系",
    "regulatory": "监管披露",
    "professional_media": "专业财经来源",
    "research_media": "研究与资料库来源",
    "aggregator": "聚合转载",
    "community": "社区讨论",
    "self_media": "内容站点",
    "unknown": "未知来源",
}

_CURRENCY_UNITS = {
    "cny million": ("亿元人民币", 1 / 100),
    "rmb million": ("亿元人民币", 1 / 100),
    "million cny": ("亿元人民币", 1 / 100),
    "million rmb": ("亿元人民币", 1 / 100),
    "cny bn": ("亿元人民币", 10),
    "rmb bn": ("亿元人民币", 10),
    "cny billion": ("亿元人民币", 10),
    "rmb billion": ("亿元人民币", 10),
    "usd million": ("亿美元", 1 / 100),
    "million usd": ("亿美元", 1 / 100),
    "usd bn": ("亿美元", 10),
    "usd billion": ("亿美元", 10),
}


def _safe_float(value: object) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def humanize_status(value: object) -> str:
    raw = str(value or "").strip()
    return STATUS_LABELS.get(raw, raw)


def humanize_tier(value: object) -> str:
    raw = str(value or "").strip().lower()
    return TIER_LABELS.get(raw, raw or "未知")


def humanize_source_type(value: object) -> str:
    raw = str(value or "").strip()
    return SOURCE_TYPE_LABELS.get(raw, raw or "未知来源")


def humanize_unit(unit: object) -> str:
    normalized_unit = re.sub(r"\s+", " ", str(unit or "").strip().lower())
    if normalized_unit in {"cny million", "rmb million", "million cny", "million rmb", "cny bn", "rmb bn", "cny billion", "rmb billion"}:
        return "亿元人民币"
    if normalized_unit in {"usd million", "million usd", "usd bn", "usd billion"}:
        return "亿美元"
    if normalized_unit in {"%", "percent", "percentage"}:
        return "%"
    if normalized_unit in {"x", "times"}:
        return "x"
    if normalized_unit in {"b", "bn", "billion"}:
        return "亿"
    return str(unit or "")


def format_display_value(value: object, unit: str | None = None) -> str:
    if value is None or value == "":
        return "待补证"
    numeric = _safe_float(value)
    normalized_unit = re.sub(r"\s+", " ", (unit or "").strip().lower())
    if numeric is None:
        return str(value)
    if normalized_unit in {"%", "percent", "percentage"}:
        return f"{numeric:.1f}%"
    if normalized_unit in {"x", "times"}:
        return f"{numeric:.1f}x"
    if normalized_unit in _CURRENCY_UNITS:
        label, factor = _CURRENCY_UNITS[normalized_unit]
        scaled = numeric * factor
        return f"约 {scaled:,.0f} {label}"
    if normalized_unit in {"b", "bn", "billion"}:
        return f"约 {numeric * 10:,.0f} 亿"
    if normalized_unit in {"million", "mn", "m"}:
        return f"约 {numeric / 100:,.0f} 亿"
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.1f}"


def sanitize_display_text(text: object) -> str:
    output = str(text or "")
    replacements = {
        "Under Review": "仍需补证",
        "Improving": "有改善迹象，但仍需验证",
        "Stable": "暂稳",
        "Healthy": "结构较健康",
        "Observed": "已观察到",
        "Tightening": "边际承压",
        "Unsustainable": "难以持续",
        "Weak moat despite cheap valuation": "估值和护城河仍需验证",
        "weak moat": "护城河强度仍需验证",
        "cheap valuation": "估值仍需验证",
        "broken refs": "断裂引用",
    }
    for raw, label in replacements.items():
        output = output.replace(raw, label)
    output = re.sub(r"\bN/A\b", "待补证", output)
    output = re.sub(r"\blogic_gap\b|\bpt[123]\b|\bregistry\b|\bbroken refs\b", "", output, flags=re.IGNORECASE)
    output = re.sub(r"\s{2,}", " ", output).strip()
    return output
