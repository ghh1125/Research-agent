from __future__ import annotations

from research_flow.schema import (
    AnalystReport,
    DebateCase,
    EvidenceBundle,
    ManagerDecision,
    PortfolioDecision,
    ResearchTask,
    RiskDebateTurn,
    RiskReview,
    ScenarioAnalysis,
)
from research_flow.portfolio import compute_portfolio_risk_metrics
from research_flow.valuation import enrich_scenario_analysis


def build_manager_decision(task: ResearchTask, reports: list[AnalystReport], bull: DebateCase, bear: DebateCase) -> ManagerDecision:
    high_conf = sum(1 for report in reports if report.confidence == "high")
    confidence = "high" if high_conf >= 2 else "medium" if reports else "low"
    rating = "deep_dive_candidate" if confidence in {"high", "medium"} else "watchlist"
    return ManagerDecision(
        rating=rating,
        core_logic=[
            "研究结论必须同时穿过基本面、估值和风险三道验证。",
            "多头和空头的核心分歧集中在利润率、海外政策和需求持续性。",
            "当前更适合形成研究评级和跟踪路径，而不是直接交易指令。",
        ],
        key_assumptions=["收入增长延续", "毛利率不被价格战持续侵蚀", "海外政策风险可控"],
        fragile_assumption="毛利率不被价格战持续侵蚀",
        confidence=confidence,  # type: ignore[arg-type]
        variant_perception="胜负手不是单期增长，而是增长、毛利率和估值折现率能否同时守住。",
        tracking_metrics=["收入增速", "毛利率", "经营现金流", "海外订单/政策", "同行估值倍数"],
        verification_path=[
            "补齐最近两期财报三表和分部数据",
            "对比同行价格、份额和毛利率变化",
            "在财报/政策/价格触发时更新 bull/bear 情景",
        ],
    )


def build_manager_decision_with_llm(
    task: ResearchTask,
    reports: list[AnalystReport],
    bull: DebateCase,
    bear: DebateCase,
    llm_client,
    *,
    memory_context: str | None = None,
) -> ManagerDecision:
    memory_section = (
        f"\n\n历史判断记忆（同一实体的历史评级与结论，请校准当前裁决避免重复旧错误）：\n{memory_context}"
        if memory_context and memory_context.strip()
        else ""
    )
    prompt = f"""
你是 Research Manager。请在多空辩论之后收敛成投研判断，不要给直接交易指令。
必须输出：评级、核心逻辑、三个关键假设、最脆弱假设、置信度、variant perception、跟踪指标、验证路径。

Task:
{task.model_dump_json(ensure_ascii=False)}
Analyst reports:
{[report.model_dump() for report in reports]}
Bull:
{bull.model_dump_json(ensure_ascii=False)}
Bear:
{bear.model_dump_json(ensure_ascii=False)}{memory_section}
""".strip()
    return llm_client.complete_json(
        prompt,
        ManagerDecision,
        role="deep",
        context={"stage": "research_manager", "quick_model": task.quick_model, "deep_model": task.deep_model},
    )


def build_scenario_analysis(task: ResearchTask, decision: ManagerDecision, bundle: EvidenceBundle | None = None) -> ScenarioAnalysis:
    subject = task.entity or (task.symbols[0] if task.symbols else "研究对象")
    scenario = ScenarioAnalysis(
        base_case=f"{subject} 增长放缓但仍维持正现金流，估值回到同行中位附近。",
        bull_case="收入增长、毛利率和海外订单同时好于预期，估值获得重新扩张。",
        bear_case="价格战延续、利润率下台阶、海外政策扰动导致估值压缩。",
        target_price_range="base/bull/bear 暂以相对估值区间表达；接入完整财务模型后输出定量目标价。",
        margin_of_safety="只有当价格低于 base 情景估值并且毛利率假设未被证伪时，才具备安全边际。",
        key_drivers=["收入增速", "毛利率", "费用率", "资本开支", "折现率", "终值倍数"],
        evidence_ids=[],
    )
    return enrich_scenario_analysis(scenario, bundle) if bundle else scenario


def build_scenario_analysis_with_llm(
    task: ResearchTask,
    decision: ManagerDecision,
    reports: list[AnalystReport],
    llm_client,
    bundle: EvidenceBundle | None = None,
) -> ScenarioAnalysis:
    prompt = f"""
你是 Valuation / Scenario Analyst。请在 Research Manager 裁决之后做 base/bull/bear 三情景估值。
必须覆盖收入增速、毛利率、费用率、资本开支、折现率、终值倍数、目标价区间和安全边际。
如果证据不足，明确说明缺口，不要编造数字。

Task:
{task.model_dump_json(ensure_ascii=False)}
Manager decision:
{decision.model_dump_json(ensure_ascii=False)}
Reports:
{[report.model_dump() for report in reports]}
Evidence:
{[item.model_dump() for item in (bundle.evidence if bundle else [])[:30]]}
""".strip()
    scenario = llm_client.complete_json(
        prompt,
        ScenarioAnalysis,
        role="deep",
        context={"stage": "scenario", "quick_model": task.quick_model, "deep_model": task.deep_model},
    )
    return enrich_scenario_analysis(scenario, bundle) if bundle else scenario


def _portfolio_metrics(bundle: EvidenceBundle | None) -> dict[str, object]:
    return compute_portfolio_risk_metrics(bundle) if bundle is not None else {}


def build_risk_review(task: ResearchTask, decision: ManagerDecision, scenario: ScenarioAnalysis, bundle: EvidenceBundle | None = None) -> RiskReview:
    metrics = _portfolio_metrics(bundle)
    return RiskReview(
        aggressive_view="激进视角关注上行弹性：若增长和利润率同时改善，可进入高弹性跟踪。",
        neutral_view="中性视角关注赔率：等待估值区间、毛利率和订单数据同步确认。",
        conservative_view="保守视角关注永久损失：价格战、政策、资本开支和估值压缩是主要尾部风险。",
        risk_flags=["利润率下滑", "海外政策", "行业供给过剩", "估值压缩", "流动性/仓位拥挤"],
        portfolio_context=f"风险偏好={task.risk_preference}；当前阶段应先做组合暴露、相关性和回撤检查。",
        portfolio_metrics=metrics,
    )


def build_risk_review_with_llm(
    task: ResearchTask,
    decision: ManagerDecision,
    scenario: ScenarioAnalysis,
    llm_client,
    bundle: EvidenceBundle | None = None,
) -> RiskReview:
    metrics = _portfolio_metrics(bundle)
    prompt = f"""
你是 Risk Management Team。请分别给出 aggressive、neutral、conservative 风险视角，并加入组合语境。
需要覆盖下行风险、流动性、波动率、组合相关性、回撤和风险收益比。

Task:
{task.model_dump_json(ensure_ascii=False)}
Manager decision:
{decision.model_dump_json(ensure_ascii=False)}
Scenario:
{scenario.model_dump_json(ensure_ascii=False)}
Portfolio metrics computed from market evidence:
{metrics}
""".strip()
    review = llm_client.complete_json(
        prompt,
        RiskReview,
        role="deep",
        context={"stage": "risk", "quick_model": task.quick_model, "deep_model": task.deep_model},
    )
    return review.model_copy(update={"portfolio_metrics": metrics or review.portfolio_metrics})


def build_risk_review_with_debate(
    task: ResearchTask,
    decision: ManagerDecision,
    scenario: ScenarioAnalysis,
    llm_client,
    *,
    max_rounds: int = 1,
    bundle: EvidenceBundle | None = None,
) -> RiskReview:
    metrics = _portfolio_metrics(bundle)
    history: list[RiskDebateTurn] = []
    speakers = ["aggressive", "conservative", "neutral"]
    for round_index in range(1, max(max_rounds, 1) + 1):
        for speaker in speakers:
            prompt = f"""
你是 Risk Management Team 里的 {speaker} debator。请只从自己的风险偏好出发发言。
aggressive 关注上行弹性和可承受波动；conservative 关注永久损失、流动性、回撤；neutral 关注赔率、等待条件和组合相关性。

Task:
{task.model_dump_json(ensure_ascii=False)}
Manager decision:
{decision.model_dump_json(ensure_ascii=False)}
Scenario:
{scenario.model_dump_json(ensure_ascii=False)}
Portfolio metrics:
{metrics}
Risk debate history:
{[turn.model_dump() for turn in history]}
""".strip()
            raw = llm_client.complete_json(
                prompt,
                RiskDebateTurn,
                role="deep",
                context={
                    "stage": "risk_debator",
                    "speaker": speaker,
                    "round_index": round_index,
                    "quick_model": task.quick_model,
                    "deep_model": task.deep_model,
                },
            )
            turn = raw if isinstance(raw, RiskDebateTurn) else RiskDebateTurn.model_validate(raw)
            history.append(turn)
    review = build_risk_review_with_llm(task, decision, scenario, llm_client, bundle)
    return review.model_copy(update={"debate_history": history, "portfolio_metrics": metrics or review.portfolio_metrics})


def build_portfolio_decision(task: ResearchTask, decision: ManagerDecision, risk: RiskReview) -> PortfolioDecision:
    if task.risk_preference == "conservative" and "估值压缩" in risk.risk_flags:
        action = "观察"
        position_hint = "保守组合暂不提高仓位，等待触发条件。"
    elif task.question_type == "trading_decision_assist":
        action = "可小仓位跟踪"
        position_hint = "仅适合小仓位试探，必须设置复盘触发。"
    else:
        action = "值得进一步研究"
        position_hint = "进入研究池，不直接转为交易指令。"
    return PortfolioDecision(
        action=action,  # type: ignore[arg-type]
        position_hint=position_hint,
        rationale="组合经理只批准研究/跟踪动作，仓位需要结合现有组合暴露、相关性和回撤预算。",
        risk_level="high" if task.risk_preference == "aggressive" else "medium",
        revisit_trigger="财报、公告、重大新闻或价格进入目标区间时重新评估。",
    )


def build_portfolio_decision_with_llm(task: ResearchTask, decision: ManagerDecision, risk: RiskReview, scenario: ScenarioAnalysis, llm_client) -> PortfolioDecision:
    prompt = f"""
你是 Portfolio Manager。请从组合角度判断风险收益比、仓位、回撤、流动性、相关性。
action 必须从以下枚举中选择：值得进一步研究、观察、回避、减仓、可小仓位跟踪。

Task:
{task.model_dump_json(ensure_ascii=False)}
Manager decision:
{decision.model_dump_json(ensure_ascii=False)}
Scenario:
{scenario.model_dump_json(ensure_ascii=False)}
Risk:
{risk.model_dump_json(ensure_ascii=False)}
""".strip()
    return llm_client.complete_json(
        prompt,
        PortfolioDecision,
        role="deep",
        context={"stage": "portfolio", "quick_model": task.quick_model, "deep_model": task.deep_model},
    )
