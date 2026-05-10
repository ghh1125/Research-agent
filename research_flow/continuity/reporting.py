from __future__ import annotations

import json
from pathlib import Path

from research_flow.schema import ResearchMemoryEntry, ResearchReport, ResearchResult


def build_memory_entry(result: ResearchResult) -> ResearchMemoryEntry:
    return ResearchMemoryEntry(
        task_id=result.task.id,
        entity=result.task.entity,
        symbols=result.task.symbols,
        conclusion=result.portfolio_decision.action,
        rating=result.manager_decision.rating,
        price_context=_price_context(result),
        key_assumptions=result.manager_decision.key_assumptions,
        revisit_triggers=[result.portfolio_decision.revisit_trigger, *result.manager_decision.tracking_metrics[:3]],
    )


def build_report(result: ResearchResult) -> ResearchReport:
    sections = {
        "结论先行": f"{result.portfolio_decision.action}。{result.portfolio_decision.rationale}",
        "评级": f"{result.manager_decision.rating} / confidence={result.manager_decision.confidence}",
        "目标价/估值区间": result.scenario_analysis.target_price_range,
        "投资逻辑": "\n".join(f"- {item}" for item in result.manager_decision.core_logic),
        "关键假设": "\n".join(f"- {item}" for item in result.manager_decision.key_assumptions),
        "催化剂": "\n".join(f"- {item}" for item in result.manager_decision.tracking_metrics),
        "风险": "\n".join(f"- {item}" for item in result.risk_review.risk_flags),
        "组合风险指标": _format_metrics(result.risk_review.portfolio_metrics),
        "反方观点": result.bear_case.thesis,
        "多空辩论": _format_investment_debate(result),
        "风控辩论": _format_risk_debate(result),
        "跟踪指标": "\n".join(f"- {item}" for item in result.manager_decision.tracking_metrics),
        "数据来源": "\n".join(
            f"- {artifact.title} [{artifact.category}]"
            + (f"({artifact.url})" if artifact.url else "")
            for artifact in result.evidence_bundle.artifacts
        ),
        "下一步研究问题": "\n".join(f"- {item}" for item in result.manager_decision.verification_path),
    }
    lines = ["# 投研报告", ""]
    for title, body in sections.items():
        lines.extend([f"## {title}", body or "暂无", ""])
    lines.append("> 非投资建议。本报告用于投研研究、证据复查和后续跟踪。")
    return ResearchReport(
        markdown="\n".join(lines),
        sections=sections,
        data_sources=[artifact.title for artifact in result.evidence_bundle.artifacts],
    )


def _format_metrics(metrics: dict[str, object]) -> str:
    if not metrics:
        return "暂无可计算的组合/行情风险指标。"
    return "\n".join(f"- {key}: {value}" for key, value in metrics.items())


def _format_investment_debate(result: ResearchResult) -> str:
    lines = [f"- Bull: {result.bull_case.thesis}", f"- Bear: {result.bear_case.thesis}"]
    for turn in result.investment_debate_history:
        lines.append(f"- {turn.side} round {turn.round_index}: {turn.thesis}")
    return "\n".join(lines)


def _format_risk_debate(result: ResearchResult) -> str:
    if not result.risk_review.debate_history:
        return "暂无风控辩论记录。"
    return "\n".join(
        f"- {turn.speaker} round {turn.round_index}: {turn.view}" for turn in result.risk_review.debate_history
    )


def _price_context(result: ResearchResult) -> str | None:
    for evidence in result.evidence_bundle.evidence:
        name = (evidence.metric_name or "").lower()
        if name in {"price", "current_price", "last_price", "close"} and evidence.metric_value is not None:
            return str(evidence.metric_value)
    for artifact in result.evidence_bundle.artifacts:
        if artifact.category == "market_data":
            fast_info = artifact.content.find("last_price")
            if fast_info >= 0:
                return artifact.content[fast_info : fast_info + 80]
    return None


def write_result_state(result: ResearchResult, results_dir: str | Path) -> Path:
    root = Path(results_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{result.task.id}.json"
    path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
