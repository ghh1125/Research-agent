from __future__ import annotations

from app.models.judgment import EvidenceGap, Judgment, ResearchAction, RiskItem


def _priority_from_gap(gap: EvidenceGap) -> str:
    return "high" if gap.importance == "high" else "medium" if gap.importance == "medium" else "low"


def _templates_for_text(text: str) -> list[str]:
    if any(token in text for token in ["财务", "现金流", "利润", "收入", "财报", "经营数据"]):
        return [
            "{entity} annual report operating cash flow capex free cash flow",
            "{entity} 年报 营业收入 净利润 毛利率 资本开支 自由现金流",
            "{entity} investor relations revenue gross margin net income cash flow capex",
        ]
    if any(token in text for token in ["同行", "行业", "竞争", "份额", "估值"]):
        return [
            "{entity} market share peer comparison gross margin valuation multiple",
            "{entity} 行业竞争 市场份额 同行排名 价格竞争",
            "{entity} peers revenue growth gross margin market share analyst report",
        ]
    if any(token in text for token in ["合规", "监管", "处罚", "资质", "治理"]):
        return [
            "{entity} 监管 处罚 合规 风险",
            "{entity} 公司治理 内控 关联交易",
            "{entity} regulatory filing governance risk",
        ]
    return [
        "{entity} 官方公告 财报 关键数据",
        "{entity} 专业财经 研究 风险",
        "{entity} annual report investor presentation",
    ]


def _required_data_for_text(text: str) -> list[str]:
    data: list[str] = []
    if any(token in text for token in ["财务", "现金流", "利润", "收入", "财报"]):
        data.extend(["营业收入", "同比增速", "净利润", "毛利率", "经营现金流", "资本开支", "自由现金流"])
    if any(token in text for token in ["增长", "用户", "订单", "GMV"]):
        data.extend(["用户数", "订单数", "GMV", "营销费用率"])
    if any(token in text for token in ["竞争", "同行", "行业"]):
        data.extend(["市场份额", "同行增速", "毛利率对比", "估值倍数", "价格竞争信号"])
    if any(token in text for token in ["合规", "监管", "治理", "处罚"]):
        data.extend(["监管处罚记录", "公告披露", "治理与内控信息"])
    return list(dict.fromkeys(data or ["官方披露", "专业来源交叉验证", "关键经营数据"]))


def _source_targets_for_text(text: str) -> list[str]:
    targets = ["official filings", "investor relations"]
    if any(token in text for token in ["同行", "行业", "竞争", "估值"]):
        targets.append("professional finance media")
        targets.append("broker research")
    if any(token in text for token in ["合规", "监管", "处罚"]):
        targets.append("regulators / exchanges")
    return list(dict.fromkeys(targets + ["recognized data providers"]))


def _action_from_gap(index: int, gap: EvidenceGap) -> ResearchAction:
    objective = (
        gap.text.replace("子问题证据不足：", "")
        .replace("子问题仅部分覆盖：", "")
        .strip()
        or "补齐关键证据缺口"
    )
    query_templates = _templates_for_text(objective)
    source_targets = _source_targets_for_text(objective)
    return ResearchAction(
        id=f"a{index}",
        priority=_priority_from_gap(gap),
        question=objective,
        objective=objective,
        reason=f"该证据缺口重要性为{gap.importance}，会直接影响研究判断的可信度。",
        required_data=_required_data_for_text(objective),
        search_query=query_templates[0],
        query_templates=query_templates,
        target_sources=source_targets,
        source_targets=source_targets,
        question_id=gap.question_id,
    )


def _action_from_risk(index: int, risk: RiskItem) -> ResearchAction:
    objective = f"交叉验证风险项：{risk.text}"
    query_templates = _templates_for_text(risk.text)
    source_targets = _source_targets_for_text(risk.text)
    return ResearchAction(
        id=f"a{index}",
        priority="medium",
        question=objective,
        objective=objective,
        reason="该风险已有证据支持，但需要独立高质量来源交叉验证，避免单一材料放大风险。",
        required_data=_required_data_for_text(risk.text),
        search_query=query_templates[0],
        query_templates=query_templates,
        target_sources=source_targets,
        source_targets=source_targets,
    )


def _fallback_action(index: int, judgment: Judgment) -> ResearchAction:
    query_templates = [
        "{entity} annual report operating cash flow capex free cash flow",
        "{entity} investor relations annual report quarterly results revenue margin",
        "{entity} market share peer comparison valuation multiple",
    ]
    source_targets = ["official filings", "investor relations", "recognized data providers", "broker research"]
    return ResearchAction(
        id=f"a{index}",
        priority="medium" if judgment.confidence == "low" else "low",
        question="如何补齐官方来源、核心财务指标和同行参照",
        objective="补齐官方来源和关键经营财务数据",
        reason="当前研究仍需要更高质量来源来提高证据链可靠性。",
        required_data=["官方财报", "营业收入", "净利润", "毛利率", "经营现金流", "资本开支", "同行或行业参照"],
        search_query=query_templates[0],
        query_templates=query_templates,
        target_sources=source_targets,
        source_targets=source_targets,
    )


def _sorted_unique_actions(actions: list[ResearchAction]) -> list[ResearchAction]:
    priority_order = {"high": 0, "medium": 1, "low": 2}
    seen: set[str] = set()
    deduped: list[ResearchAction] = []
    for action in sorted(actions, key=lambda item: (priority_order.get(item.priority, 9), item.objective)):
        key = f"{action.objective}|{action.reason}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return [item.model_copy(update={"id": f"a{index}"}) for index, item in enumerate(deduped, start=1)]


def generate_research_actions(judgment: Judgment) -> list[ResearchAction]:
    """Generate structured research tasks from evidence gaps and risks.

    NOTE: This generates diagnostic guidance on补证方向 (gap identification),
    but does NOT automatically execute the补证 loop. The tasks are recommendations
    for what evidence gaps should be addressed next. Final judgment is based on
    current evidence only. To implement automatic multi-round补证, wrap this with
    explicit loop control and budget constraints.
    """

    if judgment.research_actions:
        return _sorted_unique_actions(judgment.research_actions)

    actions: list[ResearchAction] = []
    for gap in sorted(
        judgment.evidence_gaps,
        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item.importance, 3),
    ):
        actions.append(_action_from_gap(len(actions) + 1, gap))
        if len(actions) >= 3:
            return _sorted_unique_actions(actions)

    for item in judgment.risk[:2]:
        actions.append(_action_from_risk(len(actions) + 1, item))
        if len(actions) >= 3:
            return _sorted_unique_actions(actions)

    if not actions:
        actions.append(_fallback_action(1, judgment))

    return _sorted_unique_actions(actions)
