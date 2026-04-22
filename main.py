from __future__ import annotations

import re

from app.agent.steps.action import generate_research_actions
from app.agent.steps.auto_research import auto_research_loop
from app.agent.steps.define import define_problem
from app.agent.steps.decompose import decompose_problem
from app.agent.steps.extract import extract_evidence
from app.agent.steps.investment import apply_investment_layer
from app.agent.steps.reason import reason_and_generate
from app.agent.steps.report import generate_report
from app.agent.steps.retrieve import retrieve_information
from app.agent.steps.role import synthesize_role_outputs
from app.agent.steps.summary import build_executive_summary
from app.agent.steps.variable import normalize_variables
from app.agent.pipeline import _append_financial_source
from app.db.repository import InMemoryResearchRepository
from app.services.financial_data_service import fetch_financial_snapshot
from app.services.storage_service import (
    save_evidence,
    save_judgment,
    save_questions,
    save_report,
    save_roles,
    save_sources,
    save_topic,
    save_variables,
)


_RELATIVE_CONTEXT_TOKENS = ["同行", "行业平均", "对比", "竞争对手", "市占率", "市场份额", "相对位置", "peer", "competitor"]


def _has_relative_context(evidence: list, financial_snapshot=None) -> bool:
    if financial_snapshot is not None and financial_snapshot.peer_comparison:
        return True
    return any(
        any(token.lower() in item.content.lower() for token in _RELATIVE_CONTEXT_TOKENS)
        for item in evidence
    )


def _mark_question_coverage(questions: list, evidence: list, topic=None, financial_snapshot=None) -> list:
    relative_context_ready = _has_relative_context(evidence, financial_snapshot)
    requires_relative_context = (
        topic is not None and getattr(topic, "research_object_type", "unknown") == "listed_company"
    )
    evidence_by_question = {
        question.id: [item for item in evidence if item.question_id == question.id]
        for question in questions
    }

    def _has_complete_number(text: str, tokens: list[str]) -> bool:
        if not any(token in text for token in tokens):
            return False
        return bool(re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|百万|千元|美元|人民币|港元|%|百分点|倍)", text))

    def _coverage_level(question, items: list) -> str:
        if not items:
            return "uncovered"
        texts = [item.content for item in items if (item.evidence_score or item.quality_score or 0) >= 0.35]
        if not texts:
            return "uncovered"
        joined = " ".join(texts)
        framework = getattr(question, "framework_type", "general")
        if framework == "financial":
            has_revenue = _has_complete_number(joined, ["营业收入", "营收", "收入"])
            has_profit = _has_complete_number(joined, ["净利润", "归母净利润", "扣非净利润"])
            has_margin = _has_complete_number(joined, ["毛利率", "净利率"])
            has_trend = any(token in joined for token in ["同比", "三年", "趋势", "上年同期", "较上年"])
            strong = has_revenue and has_profit and has_margin and has_trend
            return "covered" if strong else "partial"
        if framework == "credit":
            has_cashflow = _has_complete_number(joined, ["经营现金流", "经营活动现金流", "经营活动产生的现金流量净额"])
            has_capex = _has_complete_number(joined, ["资本开支", "CAPEX", "购建固定资产"])
            has_debt = any(_has_complete_number(joined, [token]) for token in ["有息负债", "债务结构", "短债", "资产负债率", "流动比率"])
            strong = has_cashflow and has_capex and has_debt
            return "covered" if strong else "partial"
        if framework == "industry":
            has_share = any(token in joined for token in ["市场份额", "市占率", "份额"])
            has_peer = relative_context_ready or any(token in joined for token in ["同行对比", "同业对比", "同行排名", "竞争对手"])
            has_competition = any(token in joined for token in ["竞争格局", "价格竞争", "客户结构", "技术路线", "产能份额"])
            strong = has_share and has_peer and has_competition
            return "covered" if strong else "partial"
        if framework == "valuation":
            has_multiple = any(token in joined for token in ["PE", "PB", "EV/EBITDA", "EVEBITDA", "市盈率", "市净率", "估值倍数"])
            return "covered" if has_multiple and relative_context_ready else "uncovered"
        return "covered"

    marked = []
    for question in questions:
        coverage_level = _coverage_level(question, evidence_by_question.get(question.id, []))
        covered = coverage_level == "covered"
        if (
            covered
            and requires_relative_context
            and question.framework_type in {"industry", "valuation"}
            and not relative_context_ready
        ):
            covered = False
            coverage_level = "partial"
        marked.append(question.model_copy(update={"covered": covered, "coverage_level": coverage_level}))
    return marked


def _step(title: str) -> None:
    print("\n" + "-" * 80)
    print(f"[STEP] {title}")
    print("-" * 80)


def _print_financial_snapshot(snapshot) -> None:
    print(f"status: {snapshot.status}")
    print(f"provider: {snapshot.provider}")
    print(f"symbol: {snapshot.symbol or '未解析'}")
    if getattr(snapshot, "provider_attempts", None):
        print("provider_attempts:")
        for attempt in snapshot.provider_attempts:
            retry_text = "可重试" if attempt.retryable else "不可重试"
            fallback_text = f"，next={attempt.next_provider}" if attempt.next_provider else ""
            print(f"  - {attempt.provider}: {attempt.status}（{retry_text}{fallback_text}）{attempt.message}")
    if snapshot.metrics:
        for metric in snapshot.metrics:
            print(f"- {metric.name}: {metric.value}{metric.unit or ''} ({metric.period or 'latest'})")
    if snapshot.peer_symbols:
        print(f"peer_symbols: {', '.join(snapshot.peer_symbols)}")
    if snapshot.peer_comparison:
        print("peer_comparison:")
        for row in snapshot.peer_comparison:
            print(f"  {row}")
    if snapshot.note:
        print(f"note: {snapshot.note}")


def _print_result(query: str) -> None:
    repository = InMemoryResearchRepository()

    _step("1/11 Define - 定义研究问题")
    topic = define_problem(query)
    save_topic(repository, topic)
    print(f"topic_id: {topic.id}")
    print(f"topic: {topic.topic}")
    print(f"goal: {topic.goal}")
    print(f"type: {topic.type}")
    print(f"research_object_type: {topic.research_object_type}")
    print(f"market_type: {topic.market_type}")
    print(f"entity: {topic.entity or '无'}")
    print(f"listing_status: {topic.listing_status}")
    if topic.listing_note:
        print(f"listing_note: {topic.listing_note}")

    _step("2/12 Financial Snapshot - 结构化金融快照")
    financial_snapshot = fetch_financial_snapshot(topic)
    _print_financial_snapshot(financial_snapshot)

    _step("3/12 Decompose - 拆解研究问题")
    questions = decompose_problem(topic)
    save_questions(repository, questions)
    for question in questions:
        print(f"- {question.id} | P{question.priority} | {question.framework_type} | {question.content}")

    _step("4/12 Retrieve - 真实检索资料")
    print("正在调用搜索 API，请稍等...")
    subject = topic.entity or topic.topic
    for question in questions:
        print(f"fact_query[{question.id}]: {subject} {question.content}")
    print(f"risk_flow: {subject} 风险 / 现金流 / 监管 / 治理")
    print(f"counter_flow: {subject} 改善 / 增长 / 风险缓解 / 拐点")
    sources = retrieve_information(questions, topic)
    sources = _append_financial_source(sources, financial_snapshot, topic, questions)
    save_sources(repository, sources)
    print(f"retrieved_sources: {len(sources)}")
    for source in sources:
        print(f"- {source.id} | {source.flow_type} | [{source.provider}] [{source.tier.value}] score={source.source_score} | PDF={source.pdf_parse_status} | {source.title}")
        print(f"  query: {source.search_query}")
        print(f"  url: {source.url}")

    _step("5/12 Extract - 提取结构化证据")
    evidence = extract_evidence(topic, questions, sources)
    questions = _mark_question_coverage(questions, evidence, topic, financial_snapshot)
    save_questions(repository, questions)
    save_evidence(repository, evidence)
    print(f"evidence_count: {len(evidence)}")
    for item in evidence:
        print(f"- {item.id} | {item.flow_type} | {item.evidence_type} | {item.stance} | score={item.evidence_score} | source={item.source_id} | question={item.question_id}")
        print(f"  {item.content}")

    _step("6/12 Variable - 归一化投研变量")
    variables = normalize_variables(evidence)
    save_variables(repository, variables)
    print(f"variable_count: {len(variables)}")
    for variable in variables:
        print(f"- {variable.name} | {variable.category} | {variable.direction} | evidence={variable.evidence_ids}")
        print(f"  {variable.value_summary}")

    _step("7/12 Reason - 证据分组与判断")
    print("正在调用/执行 Reason 逻辑，请稍等...")
    judgment = reason_and_generate(topic, evidence, questions, variables)
    save_judgment(repository, judgment)
    print(f"conclusion: {judgment.conclusion}")
    print(f"conclusion_evidence_ids: {judgment.conclusion_evidence_ids}")
    print(f"confidence: {judgment.confidence}")
    print(f"research_confidence: {judgment.research_confidence}")
    print(f"signal_confidence: {judgment.signal_confidence}")
    print(f"source_confidence: {judgment.source_confidence}")
    print(f"positioning: {judgment.positioning or '待定'}")
    print(f"confidence_basis: {judgment.confidence_basis.model_dump()}")
    print("clusters:")
    for cluster in judgment.clusters:
        print(
            f"- {cluster.theme} | support={cluster.support_evidence_ids} | "
            f"counter={cluster.counter_evidence_ids}"
        )
    print("pressure_tests:")
    for test in judgment.pressure_tests:
        print(f"- {test.test_id} | {test.attack_type} | severity={test.severity}")
        print(f"  weakness: {test.weakness}")
        print(f"  counter_conclusion: {test.counter_conclusion}")
    print("bear_theses:")
    for thesis in judgment.bear_theses:
        print(f"- {thesis.title} | evidence={thesis.evidence_ids}")
        print(f"  summary: {thesis.summary}")
        print(f"  transmission_path: {thesis.transmission_path}")
    print("catalysts:")
    for catalyst in judgment.catalysts:
        print(f"- {catalyst.title} | {catalyst.catalyst_type} | {catalyst.timeframe} | evidence={catalyst.evidence_ids}")
        print(f"  why_it_matters: {catalyst.why_it_matters}")

    _step("8/12 Action - 生成结构化研究任务")
    actions = generate_research_actions(judgment)
    judgment = judgment.model_copy(update={"research_actions": actions})
    save_judgment(repository, judgment)
    for action in actions:
        print(f"{action.id} | {action.priority} | {action.objective}")
        print(f"   reason: {action.reason}")
        print(f"   required_data: {action.required_data}")
        print(f"   query_templates: {action.query_templates}")

    _step("9/12 Auto Research - 自动补证 loop")
    print("如果初步 judgment 为 low，系统会最多自动补证 1 轮...")
    auto_result = auto_research_loop(topic, questions, sources, evidence, variables, judgment, actions)
    sources = auto_result.sources
    evidence = auto_result.evidence
    variables = auto_result.variables
    questions = _mark_question_coverage(questions, evidence, topic, financial_snapshot)
    judgment = auto_result.judgment.model_copy(update={"research_actions": auto_result.actions})
    save_sources(repository, sources)
    save_evidence(repository, evidence)
    save_variables(repository, variables)
    save_judgment(repository, judgment)
    for trace in auto_result.trace:
        print(f"- round={trace.round_index} triggered={trace.triggered} stop={trace.stop_reason}")
        print(f"  actions={trace.selected_action_ids}")
        print(f"  queries={trace.executed_queries}")
        print(f"  new_sources={trace.new_source_ids}")
        print(f"  new_evidence={trace.new_evidence_ids}")
    print(f"updated_evidence_count: {len(evidence)}")
    print(f"updated_confidence: {judgment.confidence}")

    _step("10/12 Investment - 生成投资层判断")
    judgment = apply_investment_layer(topic, questions, evidence, judgment, variables)
    save_judgment(repository, judgment)
    if judgment.research_scope:
        print("research_scope:")
        print(f"  depth: {judgment.research_scope.depth_recommendation}")
        print(f"  estimated_hours: {judgment.research_scope.estimated_hours}")
        print(f"  urgency: {judgment.research_scope.urgency}")
        print(f"  reason: {judgment.research_scope.reason}")
    if judgment.peer_context:
        print("peer_context:")
        print(f"  status: {judgment.peer_context.status}")
        print(f"  note: {judgment.peer_context.note}")
        if judgment.peer_context.comparison_rows:
            print("  comparison_rows:")
            for row in judgment.peer_context.comparison_rows:
                print(f"    {row}")
    if judgment.trend_signals:
        print("trend_signals:")
        for signal in judgment.trend_signals:
            print(f"- {signal.metric} | {signal.direction} | evidence={signal.evidence_ids}")
    if judgment.investment_decision:
        print("investment_decision:")
        print(f"  target: {judgment.investment_decision.decision_target}")
        print(f"  decision: {judgment.investment_decision.decision}")
        print(f"  rationale: {judgment.investment_decision.rationale}")
        print(f"  recommendation_reason: {judgment.investment_decision.research_recommendation_reason}")
        print(f"  next_best_path: {judgment.investment_decision.next_best_research_path}")
        print(f"  positioning: {judgment.investment_decision.positioning}")
        print(f"  basis: {judgment.investment_decision.decision_basis}")
        print(f"  trigger_to_revisit: {judgment.investment_decision.trigger_to_revisit}")

    _step("11/12 Roles - 汇总多角色视角")
    roles = synthesize_role_outputs(topic, sources, evidence, variables, judgment)
    save_roles(repository, roles)
    for role in roles:
        print(f"- {role.role_name} | {role.cognitive_bias}")
        print(f"  description: {role.role_description}")
        print(f"  objective: {role.objective}")
        print(f"  rules: {'；'.join(role.operating_rules)}")
        print(f"  forbidden: {'；'.join(role.forbidden_actions)}")
        print(f"  evidence: {role.evidence_ids or ['无']}")
        print(f"  output: {role.output_summary}")

    _step("12/12 Report - 生成研究报告")
    report = generate_report(topic, questions, sources, evidence, variables, roles, judgment)
    executive_summary = build_executive_summary(judgment)
    save_report(repository, report)
    print(f"report_id: {report.id}")
    print(f"sections: {len(report.report_sections)}")

    print("\n" + "=" * 80)
    print("最终结果汇总")
    print("=" * 80)
    print("\n研究主题")
    print(topic.topic)

    print("\n执行摘要")
    print(f"one_line_conclusion: {executive_summary.one_line_conclusion}")
    print(f"top_risk: {executive_summary.top_risk}")
    print(f"next_action: {executive_summary.next_action}")
    print(f"research_time_minutes: {executive_summary.research_time_minutes}")

    print("\n结构化金融快照")
    _print_financial_snapshot(financial_snapshot)

    print("\n初步结论")
    print(judgment.conclusion)
    print(f"结论证据: {', '.join(judgment.conclusion_evidence_ids) or '无'}")

    print("\n置信度")
    print(judgment.confidence)
    print(f"research={judgment.research_confidence}, signal={judgment.signal_confidence}, source={judgment.source_confidence}")
    print(judgment.confidence_basis.model_dump())

    print("\n关键变量")
    if variables:
        for variable in variables:
            print(f"- {variable.name} | {variable.direction} | evidence={variable.evidence_ids}")
    else:
        print("- 当前未形成稳定变量")

    print("\n多角色视角")
    if roles:
        for role in roles:
            print(f"- {role.role_name}: {role.output_summary}")
    else:
        print("- 暂无多角色输出")

    print("\n主要风险")
    if judgment.risk:
        for item in judgment.risk:
            print(f"- {item.text} | evidence={item.evidence_ids}")
    else:
        print("- 当前未形成有证据支撑的风险项")

    print("\n结论压力测试")
    if judgment.pressure_tests:
        for item in judgment.pressure_tests:
            print(f"- [{item.severity}] {item.attack_type}: {item.weakness}")
    else:
        print("- 当前未识别到显式结论脆弱点")

    print("\n证据缺口")
    if judgment.evidence_gaps:
        for item in judgment.evidence_gaps:
            print(f"- [{item.importance}] {item.text}")
    else:
        print("- 暂无显式证据缺口")

    print("\n下一步研究建议")
    if judgment.research_actions:
        for item in judgment.research_actions:
            print(f"{item.id} | {item.priority} | {item.objective} | {item.reason}")
    else:
        print("- 暂无下一步建议")

    print("\n投资层判断")
    if judgment.investment_decision:
        print(f"target: {judgment.investment_decision.decision_target}")
        print(f"decision: {judgment.investment_decision.decision}")
        print(f"basis: {judgment.investment_decision.decision_basis}")
        print(f"trigger: {judgment.investment_decision.trigger_to_revisit}")
    else:
        print("- 暂无投资层判断")

    print("\n检索来源")
    for source in sources:
        print(f"- [{source.flow_type}] [{source.provider}] {source.title} | {source.url}")

    print("\nMarkdown 报告")
    print(report.markdown)
    print("=" * 80 + "\n")


def main() -> None:
    print("Research Agent 投研 Demo")
    print("输入一个投研主题后回车。输入 q / quit / exit 退出。")

    while True:
        query = input("\n请输入研究主题: ").strip()
        if query.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            return
        if not query:
            print("请输入非空研究主题。")
            continue

        try:
            _print_result(query)
        except Exception as exc:
            print(f"\n运行失败: {type(exc).__name__}: {exc}")
            print("请检查 .env 中的 DASHSCOPE_API_KEY / TAVILY_API_KEY，以及网络连接。")


if __name__ == "__main__":
    main()
