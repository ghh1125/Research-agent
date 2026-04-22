from __future__ import annotations

from app.agent.prompts.role_prompts import ROLE_CONTRACTS
from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.judgment import PressureTest
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable


def _dedupe(items: list[str], limit: int = 8) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _summarize_evidence(items: list[Evidence], fallback: str) -> str:
    if not items:
        return fallback
    snippets = [item.content for item in items[:3]]
    return "；".join(snippets)


def _pressure_ids(items: list[PressureTest], attack_types: set[str]) -> list[str]:
    return _dedupe([item.test_id for item in items if item.attack_type in attack_types])


def _summarize_pressure_tests(items: list[PressureTest], attack_types: set[str], fallback: str) -> str:
    selected = [item for item in items if item.attack_type in attack_types]
    if not selected:
        return fallback
    return "；".join(
        f"{item.test_id}/{item.attack_type}/{item.severity}: {item.weakness}"
        for item in selected[:3]
    )


def _join_summaries(*parts: str) -> str:
    return "；".join(part for part in parts if part)


def _contract(role_id: str) -> dict:
    return ROLE_CONTRACTS[role_id]


def synthesize_role_outputs(
    topic: Topic,
    sources: list[Source],
    evidence: list[Evidence],
    variables: list[ResearchVariable],
    judgment: Judgment,
) -> list[ResearchRoleOutput]:
    """Expose the implicit research roles as first-class workflow artifacts."""

    fact_sources = [item.id for item in sources if item.flow_type == "fact"]
    risk_sources = [item.id for item in sources if item.flow_type == "risk"]
    counter_sources = [item.id for item in sources if item.flow_type == "counter"]

    fact_evidence = [item for item in evidence if item.flow_type == "fact"]
    risk_evidence = [
        item for item in evidence if item.flow_type == "risk" or item.evidence_type == "risk_signal" or item.stance == "support"
    ]
    counter_evidence = [item for item in evidence if item.flow_type == "counter" or item.stance == "counter"]

    investment = judgment.investment_decision
    return [
        ResearchRoleOutput(
            role_id="fact_researcher",
            role_name="资料员",
            role_description=_contract("fact_researcher")["role_description"],
            cognitive_bias="neutral",
            objective="回答公开世界里发生了什么，尽量提取事实和数据，不直接下判断。",
            role_prompt=_contract("fact_researcher")["role_prompt"],
            operating_rules=_contract("fact_researcher")["operating_rules"],
            forbidden_actions=_contract("fact_researcher")["forbidden_actions"],
            success_criteria=_contract("fact_researcher")["success_criteria"],
            source_ids=_dedupe(fact_sources),
            evidence_ids=_dedupe([item.id for item in fact_evidence]),
            variable_names=[item.name for item in variables if item.category in {"financial", "operation", "industry"}],
            framework_types=["financial", "industry", "general"],
            output_summary=_summarize_evidence(fact_evidence, f"当前围绕“{topic.topic}”的事实证据不足。"),
        ),
        ResearchRoleOutput(
            role_id="risk_officer",
            role_name="风控官",
            role_description=_contract("risk_officer")["role_description"],
            cognitive_bias="risk_first",
            objective="主动寻找负面信号、治理问题、监管处罚、现金流和负债压力。",
            role_prompt=_contract("risk_officer")["role_prompt"],
            operating_rules=_contract("risk_officer")["operating_rules"],
            forbidden_actions=_contract("risk_officer")["forbidden_actions"],
            success_criteria=_contract("risk_officer")["success_criteria"],
            source_ids=_dedupe(risk_sources),
            evidence_ids=_dedupe([item.id for item in risk_evidence]),
            variable_names=[item.name for item in variables if item.category in {"risk", "governance", "financial"}],
            framework_types=["credit", "governance", "compliance"],
            pressure_test_ids=_pressure_ids(judgment.pressure_tests, {"fragile_evidence", "weak_source"}),
            output_summary=_join_summaries(
                _summarize_evidence(risk_evidence, "当前风险流尚未形成稳定负面证据。"),
                _summarize_pressure_tests(
                    judgment.pressure_tests,
                    {"fragile_evidence", "weak_source"},
                    "",
                ),
            ),
        ),
        ResearchRoleOutput(
            role_id="counter_analyst",
            role_name="反方分析师",
            role_description=_contract("counter_analyst")["role_description"],
            cognitive_bias="contrarian",
            objective="专门寻找改善、反转、风险缓解或能推翻负面判断的反证。",
            role_prompt=_contract("counter_analyst")["role_prompt"],
            operating_rules=_contract("counter_analyst")["operating_rules"],
            forbidden_actions=_contract("counter_analyst")["forbidden_actions"],
            success_criteria=_contract("counter_analyst")["success_criteria"],
            source_ids=_dedupe(counter_sources),
            evidence_ids=_dedupe([item.id for item in counter_evidence]),
            variable_names=[item.name for item in variables if item.direction == "improving"],
            framework_types=["adversarial"],
            pressure_test_ids=_pressure_ids(judgment.pressure_tests, {"ignored_counter_evidence", "logic_gap"}),
            output_summary=_join_summaries(
                _summarize_evidence(counter_evidence, "当前反证流尚未找到足够改善或风险缓解证据。"),
                _summarize_pressure_tests(
                    judgment.pressure_tests,
                    {"ignored_counter_evidence", "logic_gap"},
                    "",
                ),
            ),
        ),
        ResearchRoleOutput(
            role_id="synthesis_analyst",
            role_name="主研究员",
            role_description=_contract("synthesis_analyst")["role_description"],
            cognitive_bias="synthesis",
            objective="综合事实、风险和反证，处理冲突，形成有证据边界的研究判断。",
            role_prompt=_contract("synthesis_analyst")["role_prompt"],
            operating_rules=_contract("synthesis_analyst")["operating_rules"],
            forbidden_actions=_contract("synthesis_analyst")["forbidden_actions"],
            success_criteria=_contract("synthesis_analyst")["success_criteria"],
            source_ids=[],
            evidence_ids=_dedupe(judgment.conclusion_evidence_ids),
            variable_names=[item.name for item in variables],
            framework_types=["financial", "credit", "industry", "governance", "adversarial", "gap"],
            pressure_test_ids=[item.test_id for item in judgment.pressure_tests],
            output_summary=_join_summaries(
                judgment.conclusion,
                _summarize_pressure_tests(
                    judgment.pressure_tests,
                    {"fragile_evidence", "ignored_counter_evidence", "evidence_gap", "weak_source", "logic_gap"},
                    "",
                ),
            ),
        ),
        ResearchRoleOutput(
            role_id="investment_manager",
            role_name="投资经理",
            role_description=_contract("investment_manager")["role_description"],
            cognitive_bias="action",
            objective="把研究判断转化为研究优先级、观察池或深度研究动作，并给出复盘触发条件。",
            role_prompt=_contract("investment_manager")["role_prompt"],
            operating_rules=_contract("investment_manager")["operating_rules"],
            forbidden_actions=_contract("investment_manager")["forbidden_actions"],
            success_criteria=_contract("investment_manager")["success_criteria"],
            source_ids=[],
            evidence_ids=_dedupe(investment.evidence_ids if investment else []),
            variable_names=[item.name for item in variables if item.direction in {"improving", "deteriorating"}],
            framework_types=["gap", "adversarial"],
            pressure_test_ids=[item.test_id for item in judgment.pressure_tests if item.severity in {"medium", "high"}],
            output_summary=_join_summaries(
                (
                    f"{investment.decision_target}: {investment.decision}。{investment.rationale}"
                    if investment
                    else "当前尚未形成投资处理建议。"
                ),
                _summarize_pressure_tests(
                    judgment.pressure_tests,
                    {"evidence_gap", "weak_source", "logic_gap"},
                    "",
                ),
            ),
        ),
    ]
