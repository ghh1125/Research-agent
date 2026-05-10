from __future__ import annotations

from research_flow.schema import AnalystReport, DebateCase, DebateTurn, EvidenceBundle, InvestmentDebate, ResearchTask


def run_investment_debate(
    reports: list[AnalystReport],
    task: ResearchTask,
    bundle: EvidenceBundle,
    llm_client,
    *,
    max_rounds: int = 1,
    allow_fallback: bool = False,
) -> InvestmentDebate:
    history: list[DebateTurn] = []
    bull: DebateCase | None = None
    bear: DebateCase | None = None
    for round_index in range(1, max(max_rounds, 1) + 1):
        bull = build_bull_case(
            reports,
            task,
            bundle,
            llm_client,
            allow_fallback=allow_fallback,
            round_index=round_index,
            debate_history=history,
        )
        history.append(_turn("bull", round_index, bull))
        bear = build_bear_case(
            reports,
            task,
            bundle,
            llm_client,
            allow_fallback=allow_fallback,
            round_index=round_index,
            debate_history=history,
        )
        history.append(_turn("bear", round_index, bear))
    assert bull is not None and bear is not None
    return InvestmentDebate(bull_case=bull, bear_case=bear, history=history)


def build_bull_case(
    reports: list[AnalystReport],
    task: ResearchTask | None = None,
    bundle: EvidenceBundle | None = None,
    llm_client=None,
    *,
    allow_fallback: bool = False,
    round_index: int = 1,
    debate_history: list[DebateTurn] | None = None,
) -> DebateCase:
    if llm_client is not None:
        return _build_debate_case_with_llm("bull", reports, task, bundle, llm_client, round_index, debate_history or [])
    if not allow_fallback:
        raise RuntimeError("LLM bull researcher is required")
    evidence_ids = [eid for report in reports for eid in report.evidence_ids[:2]][:8]
    return DebateCase(
        side="bull",
        thesis="多头认为增长延续、成本/产业链优势和可验证催化剂仍能支撑继续研究。",
        arguments=[
            "基本面仍有收入增长和现金流证据。",
            "行业若保持集中度，成本曲线优势会放大长期竞争力。",
            "估值若处在同行中位附近，bull 情景仍有安全边际验证空间。",
        ],
        key_disagreements=["利润率能否抵抗价格竞争", "海外政策是否压缩估值", "需求增长是否可持续"],
        falsification_tests=["收入增速连续低于行业", "毛利率继续明显下滑", "核心政策/客户风险兑现"],
        evidence_ids=evidence_ids,
    )


def build_bear_case(
    reports: list[AnalystReport],
    task: ResearchTask | None = None,
    bundle: EvidenceBundle | None = None,
    llm_client=None,
    *,
    allow_fallback: bool = False,
    round_index: int = 1,
    debate_history: list[DebateTurn] | None = None,
) -> DebateCase:
    if llm_client is not None:
        return _build_debate_case_with_llm("bear", reports, task, bundle, llm_client, round_index, debate_history or [])
    if not allow_fallback:
        raise RuntimeError("LLM bear researcher is required")
    evidence_ids = [eid for report in reversed(reports) for eid in report.evidence_ids[:2]][:8]
    return DebateCase(
        side="bear",
        thesis="空头认为价格战、利润率压力、海外政策和估值压缩可能削弱赔率。",
        arguments=[
            "官方披露和新闻中已经出现利润率压力与政策风险。",
            "如果估值只靠乐观增长假设支撑，安全边际不足。",
            "技术面和短期事件不能替代基本面证据。",
        ],
        key_disagreements=["毛利率下行是否暂时", "海外风险是否已反映在估值中", "行业供给是否继续过剩"],
        falsification_tests=["毛利率稳定回升", "海外订单/政策好于预期", "估值回到有吸引力区间"],
        evidence_ids=evidence_ids,
    )


def _build_debate_case_with_llm(
    side: str,
    reports: list[AnalystReport],
    task: ResearchTask | None,
    bundle: EvidenceBundle | None,
    llm_client,
    round_index: int,
    debate_history: list[DebateTurn],
) -> DebateCase:
    role = "Bull Researcher" if side == "bull" else "Bear Researcher"
    prompt = f"""
你是 {role}。这是第 {round_index} 轮多空辩论。请基于前面各分析师子报告、证据链和上一轮辩论生成结构化{'多头' if side == 'bull' else '空头'}观点。
必须输出 thesis、arguments、关键分歧、证伪路径和 evidence_ids。

ResearchTask:
{task.model_dump_json(ensure_ascii=False) if task else ''}

Analyst reports:
{[report.model_dump() for report in reports]}

Evidence:
{[item.model_dump() for item in (bundle.evidence if bundle else [])[:30]]}

Debate history:
{[turn.model_dump() for turn in debate_history]}
""".strip()
    return llm_client.complete_json(
        prompt,
        DebateCase,
        role="deep",
        context={
            "stage": "debate",
            "side": side,
            "round_index": round_index,
            "quick_model": task.quick_model if task else None,
            "deep_model": task.deep_model if task else None,
        },
    )


def _turn(side: str, round_index: int, case: DebateCase) -> DebateTurn:
    return DebateTurn(
        side=side,  # type: ignore[arg-type]
        round_index=round_index,
        thesis=case.thesis,
        arguments=case.arguments,
        key_disagreements=case.key_disagreements,
        falsification_tests=case.falsification_tests,
        evidence_ids=case.evidence_ids,
    )
