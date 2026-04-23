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
    ("护城河", "industry", ["retention", "留存率", "MAU", "DAU", "merchant", "商户", "take rate", "货币化率", "merchant density", "商户密度", "ecosystem lock-in", "生态锁定", "switching cost", "转换成本", "repeat purchase", "复购"], True),
    ("治理合规", "governance", ["治理", "内控", "关联交易", "合规", "监管", "许可", "处罚"], False),
    ("经营韧性", "operation", ["订单", "客户", "分业务", "供应链", "产能利用率", "研发投入"], False),
    ("估值锚点", "valuation", ["PE", "PB", "EV/EBITDA", "EVEBITDA", "市盈率", "市净率", "估值倍数"], True),
]

_VARIABLE_METRIC_WHITELIST: dict[str, set[str]] = {
    "收入增长": {
        "revenue",
        "revenue_yoy",
        "gmv",
        "gmv_signal",
        "customer_management_revenue",
        "cmr",
        "order_growth",
        "segment_revenue",
        "business_revenue",
        "regional_revenue",
        "cloud_revenue",
        "aidc_revenue",
        "local_services_revenue",
        "cainiao_revenue",
    },
    "盈利能力": {
        "gross_margin",
        "gross_profit",
        "net_margin",
        "net_income",
        "non_gaap_net_income",
        "adjusted_ebita",
        "adjusted_ebita_margin",
        "ebit_margin",
        "ebita_margin",
        "operating_margin",
        "operating_income",
        "roe",
        "roic",
        "diluted_eps",
    },
    "现金流质量": {
        "operating_cash_flow",
        "ocf",
        "free_cash_flow",
        "fcf",
        "capital_expenditure",
        "capex",
        "cash_conversion_rate",
        "ocf_net_income",
        "fcf_coverage",
    },
    "负债压力": {
        "debt_to_asset_ratio",
        "asset_liability_ratio",
        "interest_bearing_debt",
        "debt_structure",
        "short_term_debt",
        "current_ratio",
        "quick_ratio",
        "cash_balance",
        "net_debt",
    },
    "行业竞争": {
        "market_share",
        "peer_comparison",
        "customer_structure",
        "asp",
        "peer_rank",
        "capacity_share",
        "technology_share",
        "segment_position",
        "capex_intensity",
        "overseas_exposure",
    },
    "护城河": {
        "retention",
        "retention_rate",
        "merchant_density",
        "mau",
        "dau",
        "merchant_count",
        "take_rate",
        "ecosystem_lock_in",
        "switching_cost",
        "repeat_purchase",
        "repeat_purchase_rate",
        "customer_retention",
    },
    "估值锚点": {
        "pe",
        "pe_ttm",
        "pb",
        "ev_ebitda",
        "ev/ebitda",
        "fcf_yield",
        "historical_percentile",
        "peer_relative_valuation",
        "valuation_multiple",
    },
}

_MAX_VARIABLES_PER_EVIDENCE = 2
_LONG_SUMMARY_TOKENS = [
    "电话会",
    "摘要",
    "管理层",
    "增长动能",
    "长期目标",
    "展望",
    "guidance",
    "outlook",
]
_BUSINESS_DIMENSION_TOKENS = [
    "云业务",
    "广告业务",
    "本地生活",
    "国际业务",
    "AIDC",
    "菜鸟",
    "电商",
    "金融科技",
    "游戏",
    "数据中心",
    "automotive",
    "cloud",
    "ads",
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
    if item.is_noise or item.is_truncated or item.cross_entity_contamination or not item.can_enter_main_chain:
        return False
    if item.evidence_type != "data":
        return False
    if any(token in item.content for token in _WEAK_VARIABLE_TOKENS):
        return False
    return bool(_COMPLETE_METRIC_PATTERN.search(item.content))


def _normalized_metric_name(item: Evidence) -> str | None:
    if not item.metric_name:
        return None
    return re.sub(r"[\s\-]+", "_", item.metric_name.strip().lower())


def _has_metric_value(item: Evidence) -> bool:
    return item.metric_value is not None or bool(_COMPLETE_METRIC_PATTERN.search(item.content))


def _metric_allowed_for_variable(item: Evidence, variable_name: str) -> bool:
    metric_name = _normalized_metric_name(item)
    if not metric_name:
        return False
    return metric_name in _VARIABLE_METRIC_WHITELIST.get(variable_name, set())


def _content_keyword_matches(item: Evidence, keywords: list[str]) -> bool:
    lowered = item.content.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _is_long_mixed_summary(item: Evidence) -> bool:
    text = item.content
    lowered = text.lower()
    if item.metric_name:
        return False
    business_hits = sum(1 for token in _BUSINESS_DIMENSION_TOKENS if token.lower() in lowered or token in text)
    metric_group_hits = sum(
        1
        for keywords in [
            ["营业收入", "营收", "revenue"],
            ["毛利率", "净利润", "EBITA", "margin"],
            ["经营现金流", "自由现金流", "资本开支", "cash flow", "capex"],
            ["PE", "PB", "EV/EBITDA", "估值"],
            ["市场份额", "同行", "竞争"],
        ]
        if any(keyword.lower() in lowered for keyword in keywords)
    )
    has_summary_marker = any(token.lower() in lowered for token in _LONG_SUMMARY_TOKENS)
    return len(text) >= 90 and (has_summary_marker or business_hits >= 3 or metric_group_hits >= 3)


def _can_drive_variable(item: Evidence, requires_structured_metric: bool) -> bool:
    if item.is_noise or item.cross_entity_contamination or not item.can_enter_main_chain:
        return False
    if any(token in item.content for token in _WEAK_VARIABLE_TOKENS):
        return False
    if requires_structured_metric:
        return _is_structured_metric_evidence(item)
    return not item.is_truncated and (item.evidence_score or item.quality_score or 0) >= 0.35


def _variable_match_score(item: Evidence, name: str, keywords: list[str], requires_structured_metric: bool) -> int | None:
    if item.is_noise or item.is_truncated or item.cross_entity_contamination or not item.can_enter_main_chain:
        return None
    if any(token in item.content for token in _WEAK_VARIABLE_TOKENS):
        return None

    metric_name = _normalized_metric_name(item)
    if metric_name and name in _VARIABLE_METRIC_WHITELIST:
        if _metric_allowed_for_variable(item, name) and _has_metric_value(item):
            return 100
        return None

    if not _content_keyword_matches(item, keywords):
        return None

    if requires_structured_metric:
        if _is_long_mixed_summary(item):
            return None
        if not _is_structured_metric_evidence(item):
            return None
        return 20

    if not _can_drive_variable(item, requires_structured_metric):
        return None
    return 10


def _candidate_variables_for_evidence(item: Evidence) -> list[tuple[str, str, int]]:
    candidates: list[tuple[str, str, int]] = []
    for name, category, keywords, requires_structured_metric in _VARIABLE_SPECS:
        score = _variable_match_score(item, name, keywords, requires_structured_metric)
        if score is not None:
            candidates.append((name, category, score))
    candidates.sort(key=lambda value: value[2], reverse=True)
    return candidates[:_MAX_VARIABLES_PER_EVIDENCE]


def normalize_variables(evidence: list[Evidence]) -> list[ResearchVariable]:
    """Group raw evidence into investment variables used by reasoning and decisions."""

    grouped: dict[tuple[str, str], list[Evidence]] = defaultdict(list)
    for item in evidence:
        for name, category, _score in _candidate_variables_for_evidence(item):
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
