from __future__ import annotations

from research_flow.schema import AnalystReport, Evidence, EvidenceBundle, ResearchPlan, ResearchTask

AGENT_CATEGORY_SCOPE: dict[str, list[str]] = {
    "macro": ["macro", "news"],
    "industry": ["industry", "filings", "news"],
    "fundamentals": ["financial_statements", "filings"],
    "valuation": ["valuation", "financial_statements", "market_data"],
    "news_event": ["news", "filings", "macro"],
    "technical_positioning": ["market_data"],
}

ROLE_NAMES = {
    "macro": "Macro Analyst",
    "industry": "Industry Analyst",
    "fundamentals": "Fundamentals Analyst",
    "valuation": "Valuation Analyst",
    "news_event": "News/Event Analyst",
    "technical_positioning": "Technical/Positioning Analyst",
}


def _evidence_for(agent: str, evidence: list[Evidence]) -> list[Evidence]:
    allowed = set(AGENT_CATEGORY_SCOPE[agent])
    return [item for item in evidence if item.category in allowed]


def build_analyst_reports(task: ResearchTask, plan: ResearchPlan, bundle: EvidenceBundle, llm_client=None, *, allow_fallback: bool = False) -> list[AnalystReport]:
    reports: list[AnalystReport] = []
    for agent in plan.selected_agents:
        scoped = _evidence_for(agent, bundle.evidence)
        if llm_client is not None:
            report = _build_analyst_report_with_llm(task, plan, bundle, agent, scoped, llm_client)
            reports.append(report)
            continue
        if not allow_fallback:
            raise RuntimeError(f"LLM analyst report is required for {agent}")
        evidence_ids = [item.id for item in scoped[:6]]
        points = [item.claim for item in scoped[:4]]
        sources = sorted({item.source_title for item in scoped})
        conclusion = _conclusion(agent, task, points)
        reports.append(
            AnalystReport(
                role_id=agent,
                role_name=ROLE_NAMES[agent],
                conclusion=conclusion,
                key_points=points or ["该维度证据不足，不能作为核心结论来源。"],
                evidence_ids=evidence_ids,
                data_sources=sources,
                confidence="high" if any(item.quality == "high" for item in scoped) else "medium" if scoped else "low",
                open_questions=[] if scoped else ["补充该维度的高质量来源。"],
            )
        )
    return reports


def _build_analyst_report_with_llm(
    task: ResearchTask,
    plan: ResearchPlan,
    bundle: EvidenceBundle,
    agent: str,
    scoped: list[Evidence],
    llm_client,
) -> AnalystReport:
    prompt = f"""
你是 {ROLE_NAMES[agent]}。你只能负责自己的专业部分，不能写完整最终报告。
请基于证据生成结构化子报告，必须包含结论、依据、数据来源、置信度、待验证问题。

ResearchTask:
{task.model_dump_json(ensure_ascii=False)}

ResearchPlan:
{plan.model_dump_json(ensure_ascii=False)}

你的工具/证据范围:
{[item.model_dump() for item in scoped[:20]]}

可用来源:
{[artifact.model_dump() for artifact in bundle.artifacts if artifact.category in AGENT_CATEGORY_SCOPE[agent]][:12]}
""".strip()
    report = llm_client.complete_json(
        prompt,
        AnalystReport,
        role="deep",
        context={"stage": "analyst", "agent": agent, "quick_model": task.quick_model, "deep_model": task.deep_model},
    )
    if report.role_id != agent:
        report = report.model_copy(update={"role_id": agent})
    if not report.role_name:
        report = report.model_copy(update={"role_name": ROLE_NAMES[agent]})
    return report


def _conclusion(agent: str, task: ResearchTask, points: list[str]) -> str:
    subject = task.entity or (task.symbols[0] if task.symbols else "研究对象")
    if not points:
        return f"{subject} 的 {ROLE_NAMES[agent]} 证据不足。"
    prefix = {
        "macro": "宏观不是主驱动，但会约束折现率、汇率和政策风险。",
        "industry": "行业胜负手在供需、成本曲线和竞争格局。",
        "fundamentals": "基本面需要围绕增长、毛利率和现金流继续验证。",
        "valuation": "估值必须用 base/bull/bear 三情景而不是单点判断。",
        "news_event": "近期事件提供催化剂和风险触发点。",
        "technical_positioning": "技术面只作为辅助，不决定投资结论。",
    }[agent]
    return f"{subject}: {prefix}"
