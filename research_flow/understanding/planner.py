from __future__ import annotations

from research_flow.schema import ResearchDimension, ResearchPlan, ResearchTask

DEFAULT_ANALYSTS = [
    "macro",
    "industry",
    "fundamentals",
    "valuation",
    "news_event",
    "technical_positioning",
]

AGENT_SOURCES: dict[str, list[str]] = {
    "macro": ["macro", "policy", "rates", "fx"],
    "industry": ["industry", "supply_chain", "competitors"],
    "fundamentals": ["financial_statements", "filings", "cashflow", "balance_sheet", "income_statement"],
    "valuation": ["valuation", "market_data", "peer_multiples", "dcf_inputs"],
    "news_event": ["news", "announcements", "filings"],
    "technical_positioning": ["market_data", "technical_indicators", "positioning"],
}


def select_agents(task: ResearchTask) -> list[str]:
    if task.question_type == "event_impact":
        return ["macro", "industry", "news_event", "fundamentals", "valuation", "technical_positioning"]
    if task.question_type == "portfolio_risk_review":
        return ["macro", "industry", "fundamentals", "valuation", "technical_positioning"]
    if task.question_type == "trading_decision_assist":
        return ["news_event", "technical_positioning", "fundamentals", "valuation", "macro"]
    return DEFAULT_ANALYSTS.copy()


def build_research_plan(task: ResearchTask, selected_agents: list[str] | None = None) -> ResearchPlan:
    agents = selected_agents or select_agents(task)
    dimensions: list[ResearchDimension] = []
    objectives = {
        "macro": "判断利率、汇率、政策和周期是否改变研究对象的赔率。",
        "industry": "判断行业供需、竞争格局、产业链位置和同行差异。",
        "fundamentals": "分析收入、利润、现金流、资产负债表和财务质量。",
        "valuation": "建立估值锚：历史估值、可比公司、DCF 与三情景目标区间。",
        "news_event": "识别近期公告、新闻、监管、价格战和催化剂/风险事件。",
        "technical_positioning": "只作为辅助，观察价格、成交、趋势和仓位拥挤度。",
    }
    for agent in agents:
        dimensions.append(
            ResearchDimension(
                name=agent,
                objective=objectives[agent],
                data_sources=AGENT_SOURCES[agent],
                hypotheses_to_test=[
                    f"{agent} 证据是否足以支撑结论",
                    f"{agent} 是否存在会推翻主结论的反例",
                ],
            )
        )
    data_sources = sorted({source for dimension in dimensions for source in dimension.data_sources})
    return ResearchPlan(
        task_id=task.id,
        objective=f"围绕“{task.raw_query}”形成有证据链的投研判断。",
        boundary="输出投研研究结论和组合语境建议，不替代正式投资决策或交易指令。",
        dimensions=dimensions,
        selected_agents=agents,
        data_sources=data_sources,
        assumptions_to_verify=[
            "核心增长/盈利假设是否有官方或高质量来源支撑",
            "估值结论是否依赖单一乐观假设",
            "空头观点是否能被后续事实证伪",
        ],
    )


required_data_sources_by_agent = lambda agents: {agent: AGENT_SOURCES[agent] for agent in agents}
select_agents_for_task = select_agents


def build_research_plan_with_llm(task: ResearchTask, llm_client, selected_agents: list[str] | None = None) -> ResearchPlan:
    prompt = f"""
你是投研研究计划生成器。根据标准化 ResearchTask 生成 research plan。
计划必须明确：
- 研究维度
- 每个维度要查的数据源
- 需要验证的关键假设
- selected_agents，只允许 macro、industry、fundamentals、valuation、news_event、technical_positioning

selected_agents 是后续多 Agent 工作流的入口控制，必须和研究维度、数据源、关键假设保持一致。

ResearchTask:
{task.model_dump_json(ensure_ascii=False)}

用户指定 selected_agents:
{selected_agents}
""".strip()
    plan = llm_client.complete_json(
        prompt,
        ResearchPlan,
        role="quick",
        context={"stage": "planner", "quick_model": task.quick_model, "deep_model": task.deep_model},
    )
    if selected_agents:
        plan = plan.model_copy(update={"selected_agents": selected_agents})
    if not plan.selected_agents:
        plan = plan.model_copy(update={"selected_agents": select_agents(task)})
    if not plan.dimensions:
        repaired = build_research_plan(task, plan.selected_agents)
        plan = plan.model_copy(update={"dimensions": repaired.dimensions})
    if not plan.data_sources:
        data_sources = sorted({source for agent in plan.selected_agents for source in AGENT_SOURCES.get(agent, [])})
        plan = plan.model_copy(update={"data_sources": data_sources})
    else:
        required_sources = {source for agent in plan.selected_agents for source in AGENT_SOURCES.get(agent, [])}
        plan = plan.model_copy(update={"data_sources": sorted(set(plan.data_sources) | required_sources)})
    return plan
