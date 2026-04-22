from __future__ import annotations

import re
from collections import defaultdict

from app.models.evidence import Evidence
from app.models.variable import ResearchVariable

_VARIABLE_SPECS: list[tuple[str, str, list[str], bool]] = [
    ("收入增长", "financial", ["营业收入", "营收", "同比增速", "季度收入", "分业务收入", "分地区收入"], True),
    ("盈利能力", "financial", ["毛利率", "净利率", "扣非净利", "扣非净利润", "ROE", "ROIC", "EBIT Margin", "净利润"], True),
    ("现金流质量", "financial", ["经营现金流", "经营活动现金流", "自由现金流", "资本开支", "CAPEX", "现金转换率"], True),
    ("负债压力", "financial", ["资产负债率", "有息负债", "债务结构", "短债", "流动比率", "速动比率"], True),
    ("行业竞争", "industry", ["市场份额", "市占率", "客户结构", "ASP", "同行排名", "产能份额", "技术份额", "同行对比"], True),
    ("治理合规", "governance", ["治理", "内控", "关联交易", "合规", "监管", "许可", "处罚"], False),
    ("经营韧性", "operation", ["订单", "客户", "分业务", "供应链", "产能利用率", "研发投入"], False),
    ("估值锚点", "valuation", ["PE", "PB", "EV/EBITDA", "EVEBITDA", "市盈率", "市净率", "估值倍数"], True),
]

_WEAK_VARIABLE_TOKENS = [
    "分红预案",
    "企业文化",
    "董事长讲话",
    "公司愿景",
    "创新驱动发展",
    "持续创造价值",
    "稳健增长",
    "高质量发展",
    "坚定推进",
]

_COMPLETE_METRIC_PATTERN = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|百万|千元|美元|人民币|港元|%|百分点|pct|倍)",
    re.IGNORECASE,
)

_IMPROVING_TOKENS = ["改善", "提升", "增长", "转正", "修复", "回升", "领先", "稳定增长", "保持领先"]
_DETERIORATING_TOKENS = ["下降", "下滑", "承压", "恶化", "亏损", "为负", "收缩", "价格下行", "处罚", "违约"]
_SLOWING_TOKENS = ["增长放缓", "增速放缓", "增速下降", "增速回落", "增速从", "降至", "环比下降"]

VARIABLE_SIGNAL_RULES = {
    "governance": {
        "negative": [
            "罚款",
            "罚单",
            "处罚",
            "penalty",
            "fine",
            "sanction",
            "强制",
            "mandated",
            "ordered",
            "forced",
            "调查",
            "investigation",
            "probe",
            "lawsuit",
            "litigation",
            "诉讼",
            "反垄断",
            "antitrust",
            "DMA",
            "违规",
            "violation",
        ],
        "positive": ["合规通过", "监管批准", "approved", "cleared", "settlement reached", "和解", "撤案"],
    },
    "financial": {
        "negative": [
            "亏损",
            "下滑",
            "下降",
            "减少",
            "增长放缓",
            "增速放缓",
            "增速下降",
            "增速回落",
            "降至",
            "环比下降",
            "loss",
            "decline",
            "decrease",
            "miss",
            "低于预期",
            "writedown",
            "减值",
        ],
        "positive": ["增长", "增加", "超预期", "beat", "record", "创新高", "growth", "expansion", "improved", "改善"],
    },
    "industry": {
        "negative": ["份额下降", "market share loss", "竞争加剧", "被超越", "价格竞争加剧"],
        "positive": ["份额提升", "market share gain", "领先", "第一"],
    },
    "valuation": {
        "negative": ["估值承压", "multiple compression", "市盈率下降", "估值下修"],
        "positive": ["估值提升", "multiple expansion", "估值修复"],
    },
}


def _count_signal_hits(text: str, tokens: list[str]) -> list[str]:
    lowered = text.lower()
    return [token for token in tokens if token.lower() in lowered]


def _rule_direction_for_category(category: str, items: list[Evidence]) -> tuple[str | None, list[str]]:
    rules = VARIABLE_SIGNAL_RULES.get(category, {})
    if not rules:
        return None, []

    negative_hits: list[str] = []
    positive_hits: list[str] = []
    for item in items:
        negative_hits.extend(_count_signal_hits(item.content, rules.get("negative", [])))
        positive_hits.extend(_count_signal_hits(item.content, rules.get("positive", [])))

    notes: list[str] = []
    if negative_hits:
        notes.append(f"规则层负向信号：{', '.join(dict.fromkeys(negative_hits))}")
    if positive_hits:
        notes.append(f"规则层正向信号：{', '.join(dict.fromkeys(positive_hits))}")
    if negative_hits and not positive_hits:
        return "deteriorating", notes
    if positive_hits and not negative_hits:
        return "improving", notes
    if negative_hits and positive_hits:
        notes.append("规则层同时命中正负信号，方向标记为 mixed，需人工复核")
        return "mixed", notes
    return None, notes


def _infer_direction_with_notes(items: list[Evidence], category: str) -> tuple[str, list[str]]:
    rule_direction, rule_notes = _rule_direction_for_category(category, items)
    if rule_direction is not None:
        return rule_direction, rule_notes

    improving = 0
    deteriorating = 0
    notes: list[str] = rule_notes.copy()
    for item in items:
        improving += sum(1 for token in _IMPROVING_TOKENS if token in item.content)
        deteriorating += sum(1 for token in _DETERIORATING_TOKENS if token in item.content)
        if any(token in item.content for token in _SLOWING_TOKENS):
            deteriorating += 1
            notes.append(f"{item.id}: 出现增长放缓/增速回落类表述")
        if item.stance == "counter":
            improving += 1
        elif item.stance == "support" and item.evidence_type == "risk_signal":
            deteriorating += 1

    if improving > 0 and deteriorating > 0:
        notes.append("变量同时包含改善与恶化信号，方向标记为 mixed，需在 Reason 中保留边界")
        return "mixed", notes
    if improving > deteriorating:
        return "improving", notes
    if deteriorating > improving:
        return "deteriorating", notes
    if improving == 0 and deteriorating == 0:
        return "unknown", notes
    return "stable", notes


def _summarize_variable(items: list[Evidence]) -> str:
    snippets = [item.content for item in items[:3]]
    return "；".join(snippets)


def _is_structured_metric_evidence(item: Evidence) -> bool:
    if item.is_noise or item.is_truncated:
        return False
    if item.evidence_type != "data":
        return False
    if any(token in item.content for token in _WEAK_VARIABLE_TOKENS):
        return False
    return bool(_COMPLETE_METRIC_PATTERN.search(item.content))


def _can_drive_variable(item: Evidence, requires_structured_metric: bool) -> bool:
    if item.is_noise:
        return False
    if any(token in item.content for token in _WEAK_VARIABLE_TOKENS):
        return False
    if requires_structured_metric:
        return _is_structured_metric_evidence(item)
    return not item.is_truncated and (item.evidence_score or item.quality_score or 0) >= 0.35


def normalize_variables(evidence: list[Evidence]) -> list[ResearchVariable]:
    """Group raw evidence into investment variables used by reasoning and decisions."""

    grouped: dict[tuple[str, str], list[Evidence]] = defaultdict(list)
    for item in evidence:
        for name, category, keywords, requires_structured_metric in _VARIABLE_SPECS:
            if any(keyword.lower() in item.content.lower() for keyword in keywords) and _can_drive_variable(
                item,
                requires_structured_metric,
            ):
                grouped[(name, category)].append(item)

    variables: list[ResearchVariable] = []
    for (name, category), items in grouped.items():
        evidence_ids: list[str] = []
        for item in items:
            if item.id not in evidence_ids:
                evidence_ids.append(item.id)
        direction, direction_notes = _infer_direction_with_notes(items, category)
        variables.append(
            ResearchVariable(
                name=name,
                category=category,
                value_summary=_summarize_variable(items),
                direction=direction,
                evidence_ids=evidence_ids[:6],
                direction_notes=direction_notes,
            )
        )

    order = {
        "financial": 0,
        "industry": 1,
        "operation": 2,
        "governance": 3,
        "valuation": 4,
        "risk": 5,
    }
    return sorted(variables, key=lambda item: (order.get(item.category, 99), item.name))[:8]
