from __future__ import annotations

from collections import defaultdict

from app.models.evidence import Evidence
from app.models.judgment import (
    InvestmentDecision,
    Judgment,
    PeerContext,
    ResearchScope,
    TrendSignal,
)
from app.models.question import Question
from app.models.topic import Topic
from app.models.variable import ResearchVariable

_IMPROVING_TOKENS = ["改善", "提升", "增长", "转正", "修复", "回升", "领先", "稳定增长", "保持领先"]
_DETERIORATING_TOKENS = ["下降", "下滑", "承压", "恶化", "亏损", "为负", "收缩", "违约", "逾期", "处罚", "价格下行"]
_VETO_TOKENS = ["退市", "ST", "违约", "无证经营", "重大处罚", "资金占用", "审计保留", "无法表示意见"]
_PEER_TOKENS = ["同行", "行业平均", "对比", "竞争对手", "市占率", "市场份额", "相对位置"]
_KNOWN_PEERS = [
    "阿里巴巴",
    "京东",
    "美团",
    "抖音电商",
    "亚马逊",
    "比亚迪",
    "亿纬锂能",
    "国轩高科",
    "LG新能源",
    "松下",
    "特斯拉",
    "中创新航",
]
_PEER_GROUPS = {
    "宁德时代": {
        "local_peers": ["比亚迪", "亿纬锂能", "国轩高科", "中创新航"],
        "global_peers": ["LG新能源", "松下", "三星SDI"],
        "value_chain_peers": ["特斯拉", "天齐锂业", "赣锋锂业"],
    },
    "比亚迪": {
        "local_peers": ["宁德时代", "吉利汽车", "长城汽车"],
        "global_peers": ["特斯拉", "丰田", "大众"],
        "value_chain_peers": ["亿纬锂能", "赣锋锂业"],
    },
    "拼多多": {
        "local_peers": ["阿里巴巴", "京东", "美团", "抖音电商"],
        "global_peers": ["亚马逊", "Sea Limited"],
        "value_chain_peers": ["顺丰控股", "极兔速递"],
    },
    "英伟达": {
        "local_peers": ["AMD", "博通", "英特尔"],
        "global_peers": ["AMD", "博通", "英特尔"],
        "value_chain_peers": ["台积电", "美光科技", "超微电脑"],
    },
}
_PEER_BENCHMARK_DIMENSIONS = [
    "Revenue Growth",
    "Gross Margin",
    "Capex Intensity",
    "Market Share",
    "Overseas Exposure",
    "R&D Ratio",
    "Valuation Multiple",
    "Leverage",
]
_PEER_REQUIRED_FIELDS = {
    "revenue_growth": ["revenue_growth", "营收增速", "收入增速", "Revenue Growth"],
    "gross_margin": ["gross_margin", "毛利率", "Gross Margin"],
    "valuation": ["valuation_pe", "valuation_ev_ebitda", "PE", "PB", "EV/EBITDA", "估值"],
    "market_share": ["market_share", "市场份额", "市占率", "Market Share"],
    "capex_intensity": ["capex_intensity", "资本开支强度", "Capex Intensity"],
    "overseas_exposure": ["overseas_exposure", "海外", "Overseas Exposure"],
}

_METRIC_TOKENS = {
    "盈利能力": ["利润", "净利润", "毛利率", "营收", "收入", "盈利"],
    "现金流": ["现金流", "自由现金流", "经营活动现金流", "回款"],
    "负债结构": ["负债", "杠杆", "债务", "短债", "资产负债率"],
    "行业竞争": ["竞争", "价格", "产能", "份额", "市场", "行业"],
    "治理合规": ["治理", "内控", "关联交易", "合规", "监管", "许可", "处罚"],
}
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _min_confidence(left: str, right: str) -> str:
    if _CONFIDENCE_RANK.get(left, 0) <= _CONFIDENCE_RANK.get(right, 0):
        return left
    return right


def _valid_ids(evidence: list[Evidence]) -> set[str]:
    return {item.id for item in evidence}


def _dedupe_ids(ids: list[str], valid_ids: set[str], limit: int = 8) -> list[str]:
    deduped: list[str] = []
    for evidence_id in ids:
        if evidence_id not in valid_ids or evidence_id in deduped:
            continue
        deduped.append(evidence_id)
        if len(deduped) >= limit:
            break
    return deduped


def _build_research_scope(topic: Topic, evidence: list[Evidence], questions: list[Question], judgment: Judgment) -> ResearchScope:
    high_gaps = [gap for gap in judgment.evidence_gaps if gap.importance == "high"]
    high_priority_uncovered = [question for question in questions if question.priority == 1 and not question.covered]

    if not evidence:
        return ResearchScope(
            estimated_hours="0.5-1小时",
            urgency="low",
            depth_recommendation="quick_screen",
            reason="当前没有有效证据，建议先做快速补证，不宜进入深度研究。",
        )

    if topic.type == "compliance" or any("合规" in item.text or "监管" in item.text for item in judgment.risk):
        return ResearchScope(
            estimated_hours="2-4小时",
            urgency="high",
            depth_recommendation="standard_research",
            reason="合规问题存在一票否决属性，需要优先补充监管口径和合同/资质证据。",
        )

    if high_gaps or high_priority_uncovered:
        return ResearchScope(
            estimated_hours="2-4小时",
            urgency="medium",
            depth_recommendation="standard_research",
            reason="高优先级问题仍有证据缺口，适合做标准研究而不是直接下投资结论。",
        )

    if topic.type == "company" and judgment.confidence == "medium":
        return ResearchScope(
            estimated_hours="1-2天",
            urgency="medium",
            depth_recommendation="deep_dive",
            reason="已有多条证据支撑初步判断，可进入财务、估值和同行对比的深挖阶段。",
        )

    return ResearchScope(
        estimated_hours="1-2小时",
        urgency="low",
        depth_recommendation="quick_screen",
        reason="当前更适合快速筛选和补充关键证据，暂不建议投入过多研究时间。",
    )


def _infer_direction(texts: list[str]) -> str:
    improving = sum(1 for text in texts for token in _IMPROVING_TOKENS if token in text)
    deteriorating = sum(1 for text in texts for token in _DETERIORATING_TOKENS if token in text)
    if improving > deteriorating:
        return "improving"
    if deteriorating > improving:
        return "deteriorating"
    if improving == 0 and deteriorating == 0:
        return "unknown"
    return "stable"


def _build_trend_signals(evidence: list[Evidence], variables: list[ResearchVariable] | None = None) -> list[TrendSignal]:
    if variables:
        return [
            TrendSignal(
                metric=variable.name,
                direction=variable.direction,
                evidence_ids=variable.evidence_ids[:4],
            )
            for variable in variables
            if variable.direction != "unknown" or variable.evidence_ids
        ][:5]

    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in evidence:
        for metric, tokens in _METRIC_TOKENS.items():
            if any(token in item.content for token in tokens):
                grouped[metric].append(item)

    signals: list[TrendSignal] = []
    for metric, items in grouped.items():
        evidence_ids = [item.id for item in items[:4]]
        if not evidence_ids:
            continue
        signals.append(
            TrendSignal(
                metric=metric,
                direction=_infer_direction([item.content for item in items]),
                evidence_ids=evidence_ids,
            )
        )
    return signals[:5]


def _peer_row_dimension_coverage(rows: list[dict]) -> set[str]:
    covered: set[str] = set()
    for row in rows:
        for dimension, keys in _PEER_REQUIRED_FIELDS.items():
            for key in keys:
                value = row.get(key)
                if value is None or value == "":
                    continue
                covered.add(dimension)
                break
    return covered


def _peer_text_dimension_coverage(items: list[Evidence]) -> set[str]:
    usable_texts = [
        item.content
        for item in items
        if not any(token in item.content for token in ["未披露", "缺少", "没有披露", "未提供", "待补充"])
    ]
    text = " ".join(usable_texts)
    covered: set[str] = set()
    for dimension, tokens in _PEER_REQUIRED_FIELDS.items():
        if any(token in text for token in tokens):
            covered.add(dimension)
    return covered


def _missing_peer_dimensions(covered: set[str]) -> list[str]:
    labels = {
        "revenue_growth": "营收增速",
        "gross_margin": "毛利率",
        "valuation": "估值倍数",
        "market_share": "市场份额",
        "capex_intensity": "资本开支强度",
        "overseas_exposure": "海外暴露",
    }
    return [labels[key] for key in _PEER_REQUIRED_FIELDS if key not in covered]


def _peer_context_status(rows: list[dict], peer_evidence: list[Evidence]) -> tuple[str, str]:
    row_covered = _peer_row_dimension_coverage(rows)
    text_covered = _peer_text_dimension_coverage(peer_evidence)
    covered = row_covered | text_covered
    required_core = {"revenue_growth", "gross_margin", "valuation"}
    if required_core.issubset(covered) and len(covered) >= 4:
        return "covered", "同行对比已覆盖营收增速、盈利能力、估值与至少一个竞争/资本维度。"
    missing = "、".join(_missing_peer_dimensions(covered)[:4])
    return "needs_research", f"已有同行线索，但缺少可直接比较的核心字段：{missing}。"


def _build_peer_context(topic: Topic, evidence: list[Evidence]) -> PeerContext:
    object_type = getattr(topic, "research_object_type", "unknown")
    if object_type in {"macro_theme", "event"}:
        return PeerContext(
            required=False,
            status="not_applicable",
            note="当前对象是宏观或事件研究，同行参照不是必需项，应改看影响路径和关键变量。",
        )

    peer_evidence = [
        item for item in evidence if any(token in item.content for token in _PEER_TOKENS)
    ]
    entity = topic.entity or topic.topic
    peer_group = _PEER_GROUPS.get(entity, {})
    inferred_peers = [peer for peers in peer_group.values() for peer in peers]
    peer_entities = list(
        dict.fromkeys(
            [peer for peer in _KNOWN_PEERS if any(peer in item.content for item in evidence)] + inferred_peers
        )
    )
    peer_rows = [
        {
            "peer_group": group_name,
            "peer": peer,
            "benchmark_dimensions": _PEER_BENCHMARK_DIMENSIONS,
            "status": "needs_data",
        }
        for group_name, peers in peer_group.items()
        for peer in peers
    ]

    if peer_evidence:
        status, status_note = _peer_context_status(peer_rows, peer_evidence)
        return PeerContext(
            required=True,
            status=status,
            peer_entities=peer_entities,
            evidence_ids=[item.id for item in peer_evidence[:5]],
            comparison_rows=peer_rows,
            note=f"{status_note} 仍建议优先补充 professional/official 来源的结构化同业、主题或信用基准。",
        )

    if object_type == "private_company":
        note = "非上市公司研究需要可比模式、竞品和产业链相关上市标的，目前证据链缺少明确横向比较。"
    elif object_type == "industry_theme":
        note = "行业主题研究需要龙头、跟随者、受益者和受损者参照，目前缺少产业链相对位置证据。"
    elif object_type == "credit_issuer":
        note = "信用主体研究需要可比发债主体、偿债指标或评级参照，目前证据链缺少信用基准。"
    elif object_type in {"concept_theme", "fund_etf", "commodity"}:
        note = "主题/资产研究需要相关标的、持仓或价格基准，目前缺少相对比较证据。"
    else:
        note = "公司研究需要同行或行业基准，目前证据链缺少明确横向比较。"
    return PeerContext(
        required=True,
        status="needs_research",
        peer_entities=peer_entities,
        comparison_rows=peer_rows,
        note=note,
    )


def _decision_taxonomy(topic: Topic) -> tuple[str, dict[str, str], str]:
    object_type = getattr(topic, "research_object_type", "unknown")
    if object_type in {"industry_theme", "macro_theme", "event"}:
        return (
            "theme_tracking",
            {
                "strong": "establish_tracking",
                "normal": "monitor_for_trigger",
                "weak": "deprioritize",
            },
            "该字段表示研究跟踪建议，不构成投资建议或交易指令。",
        )
    if object_type == "credit_issuer":
        return (
            "credit_review",
            {
                "strong": "enter_credit_review",
                "normal": "high_risk_watch",
                "weak": "deprioritize",
            },
            "该字段表示信用研究处理建议，不构成债券买卖建议或评级意见。",
        )
    if object_type in {"concept_theme", "fund_etf", "commodity"}:
        return (
            "theme_tracking",
            {
                "strong": "deep_dive_candidate",
                "normal": "thematic_watch",
                "weak": "deprioritize",
            },
            "该字段表示主题/资产研究跟踪建议，不构成交易指令。",
        )
    return (
        "research_priority",
        {
            "strong": "deep_dive_candidate",
            "normal": "watchlist",
            "weak": "deprioritize",
        },
        "该字段仅表示研究流程处理建议，不构成投资建议或交易指令；任何投资动作前仍需人工确认估值和仓位约束。",
    )


def _research_reason(topic: Topic, judgment: Judgment, peer_context: PeerContext) -> str:
    object_type = getattr(topic, "research_object_type", "unknown")
    if object_type == "listed_company":
        return f"基于{judgment.confidence}置信度、{peer_context.status}的相对比较和证据缺口，当前建议按上市公司初筛路径推进。"
    if object_type == "private_company":
        return "当前对象为非上市公司，应优先验证商业模式、融资质量、治理透明度和可比公司，而不是直接做股票估值。"
    if object_type == "credit_issuer":
        return "当前对象为信用主体，应优先验证偿债能力、再融资窗口、评级变化和风险触发点。"
    if object_type in {"industry_theme", "macro_theme", "event"}:
        return "当前对象是主题/宏观/事件研究，应优先建立跟踪框架并等待关键变量或催化剂验证。"
    return "当前对象适合按主题资产初筛路径处理，先验证驱动因素、风险边界和可跟踪标的。"


def _next_best_path(topic: Topic, judgment: Judgment) -> str:
    if judgment.research_actions:
        return judgment.research_actions[0].objective
    object_type = getattr(topic, "research_object_type", "unknown")
    return {
        "listed_company": "补充官方财报、同行估值和管理层指引。",
        "private_company": "补充融资、客户、产品和可比公司证据。",
        "credit_issuer": "补充债务到期、现金流、评级和再融资证据。",
        "industry_theme": "补充政策文件、行业数据和龙头公司证据。",
        "macro_theme": "补充官方宏观数据、政策路径和受益/受损对象。",
        "event": "补充官方声明、事件时间线和影响路径证据。",
        "concept_theme": "补充相关标的、产业链证据和政策催化剂。",
        "fund_etf": "补充持仓、费用、流动性和跟踪误差信息。",
        "commodity": "补充价格、库存、供需和政策数据。",
    }.get(object_type, "补充官方或专业来源证据。")


def _build_decision_basis(
    evidence: list[Evidence],
    judgment: Judgment,
    peer_context: PeerContext,
    variables: list[ResearchVariable] | None,
    has_veto: bool,
) -> list[str]:
    basis = [
        f"confidence={judgment.confidence}",
        f"source_count={judgment.confidence_basis.source_count}",
        f"source_diversity={judgment.confidence_basis.source_diversity}",
        f"evidence_gap_level={judgment.confidence_basis.evidence_gap_level}",
        f"conflict_level={judgment.confidence_basis.conflict_level}",
        f"peer_context={peer_context.status}",
        f"risk_count={len(judgment.risk)}",
        f"has_veto_risk={str(has_veto).lower()}",
    ]
    if peer_context.peer_entities:
        basis.append(f"peer_group={','.join(peer_context.peer_entities[:6])}")
    if peer_context.comparison_rows:
        basis.append(f"peer_benchmark_dimensions={','.join(_PEER_BENCHMARK_DIMENSIONS[:4])}")
    high_gap = any(gap.importance == "high" for gap in judgment.evidence_gaps)
    basis.append(f"high_priority_evidence_gap={str(high_gap).lower()}")
    if variables:
        deteriorating = [item.name for item in variables if item.direction == "deteriorating"]
        improving = [item.name for item in variables if item.direction == "improving"]
        mixed = [item.name for item in variables if item.direction == "mixed"]
        if deteriorating:
            basis.append(f"deteriorating_variables={','.join(deteriorating[:3])}")
        if improving:
            basis.append(f"improving_variables={','.join(improving[:3])}")
        if mixed:
            basis.append(f"mixed_variables={','.join(mixed[:3])}")
    return basis


def _build_decision(
    topic: Topic,
    evidence: list[Evidence],
    judgment: Judgment,
    peer_context: PeerContext,
    variables: list[ResearchVariable] | None = None,
) -> InvestmentDecision:
    valid_ids = _valid_ids(evidence)
    base_ids = _dedupe_ids(
        judgment.conclusion_evidence_ids + [evidence_id for risk in judgment.risk for evidence_id in risk.evidence_ids],
        valid_ids,
    )
    risk_text = "；".join(item.text for item in judgment.risk)
    evidence_text = "；".join(item.content for item in evidence)
    has_veto = any(token in risk_text or token in evidence_text for token in _VETO_TOKENS)
    decision_basis = _build_decision_basis(evidence, judgment, peer_context, variables, has_veto)

    if not evidence:
        target, decision_map, caveat = _decision_taxonomy(topic)
        return InvestmentDecision(
            decision_target=target,
            decision=decision_map["normal"],
            rationale="当前没有可验证证据，不足以支持投入更多研究资源或形成投资动作。",
            evidence_ids=[],
            decision_basis=decision_basis,
            trigger_to_revisit="获得至少两个独立来源的有效证据后重新运行研究流程。",
            caveat=caveat,
            research_recommendation_reason=_research_reason(topic, judgment, peer_context),
            next_best_research_path=_next_best_path(topic, judgment),
            positioning=judgment.positioning or "信息不足，待补证",
        )

    target, decision_map, caveat = _decision_taxonomy(topic)
    if has_veto and topic.type in {"company", "compliance"}:
        return InvestmentDecision(
            decision_target=target,
            decision=decision_map["weak"],
            rationale="已有证据触及一票否决或高严重度风险，当前更适合降低研究优先级。",
            evidence_ids=base_ids,
            decision_basis=decision_basis,
            trigger_to_revisit="出现监管澄清、处罚解除、风险整改完成或独立来源反证时重新评估。",
            caveat=caveat,
            research_recommendation_reason=_research_reason(topic, judgment, peer_context),
            next_best_research_path=_next_best_path(topic, judgment),
            positioning=judgment.positioning or "风险过高，暂缓研究",
        )

    if judgment.confidence == "medium" and (peer_context.status == "covered" or not peer_context.required) and len(judgment.risk) <= 1:
        return InvestmentDecision(
            decision_target=target if target != "research_priority" else "deep_research_entry",
            decision=decision_map["strong"],
            rationale="现有证据支持初步正向判断，且已有一定同行/行业参照，可作为深度研究候选继续验证。",
            evidence_ids=base_ids,
            decision_basis=decision_basis,
            trigger_to_revisit="若后续财务数据、行业份额或核心风险证据发生反向变化，应重新评估。",
            caveat=caveat,
            research_recommendation_reason=_research_reason(topic, judgment, peer_context),
            next_best_research_path=_next_best_path(topic, judgment),
            positioning=judgment.positioning or "值得进入标准研究",
        )

    return InvestmentDecision(
        decision_target=target if target != "research_priority" else "watchlist_entry",
        decision=decision_map["normal"],
        rationale="当前已有研究线索，但证据覆盖、同行参照或置信度仍不足，建议放入观察清单并补证。",
        evidence_ids=base_ids,
        decision_basis=decision_basis,
        trigger_to_revisit="补齐高优先级证据缺口、获得同行对比或出现关键风险缓解证据后重新评估。",
        caveat=caveat,
        research_recommendation_reason=_research_reason(topic, judgment, peer_context),
        next_best_research_path=_next_best_path(topic, judgment),
        positioning=judgment.positioning or "等待关键触发点",
    )


def apply_investment_layer(
    topic: Topic,
    questions: list[Question],
    evidence: list[Evidence],
    judgment: Judgment,
    variables: list[ResearchVariable] | None = None,
) -> Judgment:
    """Attach a minimal investment workflow layer without changing the research pipeline."""

    peer_context = _build_peer_context(topic, evidence)
    adjusted_judgment = judgment
    if peer_context.required and peer_context.status == "needs_research":
        adjusted_judgment = judgment.model_copy(
            update={
                "confidence": _min_confidence(judgment.confidence, "medium"),
                "research_confidence": _min_confidence(judgment.research_confidence, "medium"),
                "positioning": judgment.positioning or "等待关键触发点",
            }
        )
    investment_decision = _build_decision(topic, evidence, adjusted_judgment, peer_context, variables)
    return adjusted_judgment.model_copy(
        update={
            "research_scope": _build_research_scope(topic, evidence, questions, adjusted_judgment),
            "trend_signals": _build_trend_signals(evidence, variables),
            "peer_context": peer_context,
            "investment_decision": investment_decision,
            "positioning": adjusted_judgment.positioning or investment_decision.positioning,
        }
    )
