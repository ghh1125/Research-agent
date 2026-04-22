from __future__ import annotations

from app.models.judgment import Judgment
from app.models.summary import ExecutiveSummary


def build_executive_summary(judgment: Judgment, early_stop_reason: str | None = None) -> ExecutiveSummary:
    """Build a single-screen operator summary."""

    top_risk = "当前未识别到有证据支撑的主要风险"
    if early_stop_reason:
        top_risk = early_stop_reason
    elif judgment.risk:
        top_risk = judgment.risk[0].text
    elif judgment.pressure_tests:
        top_risk = judgment.pressure_tests[0].weakness
    elif judgment.evidence_gaps:
        top_risk = judgment.evidence_gaps[0].text

    next_action = "暂无下一步研究建议"
    if judgment.research_actions:
        next_action = judgment.research_actions[0].objective
    elif judgment.evidence_gaps:
        next_action = f"补齐证据缺口：{judgment.evidence_gaps[0].text}"

    minutes = 30
    if judgment.confidence == "low":
        minutes = 60
    if judgment.evidence_gaps and any(item.importance == "high" for item in judgment.evidence_gaps):
        minutes = max(minutes, 120)
    if judgment.investment_decision and judgment.investment_decision.decision == "deep_dive_candidate":
        minutes = max(minutes, 240)

    return ExecutiveSummary(
        one_line_conclusion=judgment.conclusion,
        top_risk=top_risk,
        next_action=next_action,
        confidence=judgment.confidence,
        research_time_minutes=minutes,
        why_continue=(
            judgment.investment_decision.research_recommendation_reason
            if judgment.investment_decision and judgment.investment_decision.research_recommendation_reason
            else "当前输出是初筛判断，是否继续取决于证据质量、关键缺口和下一步研究动作。"
        ),
        why_not_stronger=(
            judgment.pressure_tests[0].weakness
            if judgment.pressure_tests
            else "当前系统仍要求人工复核关键证据和结论推导，不能直接升级为强结论。"
        ),
        top_bear_thesis=judgment.bear_theses[0].summary if judgment.bear_theses else top_risk,
        key_evidence_gap=judgment.evidence_gaps[0].text if judgment.evidence_gaps else None,
        next_research_focus=(
            judgment.investment_decision.next_best_research_path
            if judgment.investment_decision and judgment.investment_decision.next_best_research_path
            else next_action
        ),
    )
