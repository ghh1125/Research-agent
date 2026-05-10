from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_flow.analysis.debate import run_investment_debate
from research_flow.continuity.memory import ResearchMemoryLog
from research_flow.decision.synthesis import build_risk_review_with_debate
from research_flow.evidence.data_registry import DataToolRegistry
from research_flow.evidence.knowledge_store import LocalKnowledgeStore
from research_flow.graph import ResearchGraph
from research_flow.schema import (
    AnalystReport,
    DataArtifact,
    DebateCase,
    Evidence,
    EvidenceBundle,
    ManagerDecision,
    PortfolioDecision,
    ResearchGraphConfig,
    ResearchMemoryEntry,
    ResearchPlan,
    ResearchTask,
    RiskDebateTurn,
    RiskReview,
    ScenarioAnalysis,
)
from research_flow.understanding.planner import build_research_plan_with_llm


def _task() -> ResearchTask:
    return ResearchTask(
        id="task_contract",
        raw_query="深度研究英伟达财务质量、估值和风险",
        symbols=["NVDA"],
        entity="英伟达",
        market="US",
        question_type="single_stock_deep_dive",
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        task_id="task_contract",
        objective="形成有证据链的投研判断",
        boundary="不替代正式投资决策",
        dimensions=[],
        selected_agents=["fundamentals", "valuation"],
        data_sources=["market_data", "financial_statements"],
        assumptions_to_verify=["收入增长", "利润率"],
    )


class EmptyPlanLLM:
    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        assert schema is ResearchPlan
        return _plan()


def test_llm_planner_repairs_missing_dimensions() -> None:
    plan = build_research_plan_with_llm(_task(), EmptyPlanLLM())

    assert [dimension.name for dimension in plan.dimensions] == ["fundamentals", "valuation"]
    assert {"financial_statements", "market_data", "valuation"} <= set(plan.data_sources)


class FakeFinancialTool:
    category = "financial_statements"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        return [
            DataArtifact(
                id="financial_statements_native_1",
                category="financial_statements",
                title="NVDA income statement",
                source_type="income_statement",
                provider="fake_financial_tool",
                url="https://example.com/nvda-income",
                content="Revenue grew 20%. Gross margin was 74%.",
                metadata={"official": True},
            )
        ]


class NoSearch:
    def search(self, query: str, *, category: str, max_results: int = 5):
        raise RuntimeError("search should not be required when native tools return artifacts")


class EvidenceLLM:
    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        assert schema is EvidenceBundle
        return EvidenceBundle(
            evidence=[
                Evidence(
                    id="e1",
                    artifact_id="financial_statements_native_1",
                    category="financial_statements",
                    claim="Revenue grew 20%.",
                    metric_name="revenue_growth",
                    metric_value=20,
                    unit="%",
                    source_title="NVDA income statement",
                    source_url="https://example.com/nvda-income",
                    quality="high",
                )
            ]
        )


def test_registry_uses_native_data_tools_before_generic_search(tmp_path: Path) -> None:
    registry = DataToolRegistry(
        LocalKnowledgeStore(tmp_path / "knowledge"),
        search_client=NoSearch(),
        llm_client=EvidenceLLM(),
        config=ResearchGraphConfig(fetch_source_content=False),
        tool_providers=[FakeFinancialTool()],
    )

    bundle = registry.collect(_task(), _plan())

    assert [artifact.provider for artifact in bundle.artifacts] == ["fake_financial_tool"]
    assert bundle.tool_counts["financial_statements"] == 1
    assert bundle.evidence[0].artifact_id == "financial_statements_native_1"


class InvalidEvidenceLLM:
    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        return EvidenceBundle(
            evidence=[
                Evidence(
                    id="bad",
                    artifact_id="missing_artifact",
                    category="financial_statements",
                    claim="This should be rejected.",
                    source_title="bad",
                    quality="high",
                )
            ]
        )


def test_registry_drops_invalid_evidence_and_falls_back_to_artifact_claim(tmp_path: Path) -> None:
    registry = DataToolRegistry(
        LocalKnowledgeStore(tmp_path / "knowledge"),
        search_client=NoSearch(),
        llm_client=InvalidEvidenceLLM(),
        config=ResearchGraphConfig(fetch_source_content=False, allow_heuristic_fallback=True),
        tool_providers=[FakeFinancialTool()],
    )

    bundle = registry.collect(_task(), _plan())

    assert [item.artifact_id for item in bundle.evidence] == ["financial_statements_native_1"]
    assert bundle.evidence[0].quality == "high"


class DebateLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        side = (context or {})["side"]
        round_index = (context or {})["round_index"]
        self.calls.append(f"{side}:{round_index}")
        return DebateCase(
            side=side,
            thesis=f"{side} round {round_index}",
            arguments=[f"{side} argument {round_index}"],
            key_disagreements=["利润率"],
            falsification_tests=["下一期财报验证"],
            evidence_ids=["e1"],
        )


def test_investment_debate_runs_configured_rounds() -> None:
    llm = DebateLLM()
    reports = [
        AnalystReport(
            role_id="fundamentals",
            role_name="Fundamentals Analyst",
            conclusion="收入增长但利润率需验证",
            key_points=["收入增长"],
            evidence_ids=["e1"],
            confidence="high",
        )
    ]

    debate = run_investment_debate(reports, _task(), EvidenceBundle(), llm, max_rounds=2)

    assert llm.calls == ["bull:1", "bear:1", "bull:2", "bear:2"]
    assert len(debate.history) == 4
    assert debate.bull_case.thesis == "bull round 2"
    assert debate.bear_case.thesis == "bear round 2"


class RiskLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        stage = (context or {}).get("stage")
        if stage == "risk_debator":
            speaker = (context or {})["speaker"]
            round_index = (context or {})["round_index"]
            self.calls.append(f"{speaker}:{round_index}")
            return {"speaker": speaker, "round_index": round_index, "view": f"{speaker} view {round_index}", "risk_flags": [speaker]}
        assert schema is RiskReview
        return RiskReview(
            aggressive_view="aggressive final",
            neutral_view="neutral final",
            conservative_view="conservative final",
            risk_flags=["liquidity", "drawdown"],
            portfolio_context="portfolio context",
        )


def test_risk_team_runs_three_roles_for_each_round() -> None:
    llm = RiskLLM()
    decision = ManagerDecision(
        rating="deep_dive_candidate",
        core_logic=["基本面仍需验证"],
        key_assumptions=["收入增长", "利润率稳定", "政策可控"],
        fragile_assumption="利润率稳定",
        confidence="medium",
        variant_perception="市场分歧在利润率",
        tracking_metrics=["收入", "毛利率"],
        verification_path=["财报验证"],
    )
    scenario = ScenarioAnalysis(
        base_case="base",
        bull_case="bull",
        bear_case="bear",
        target_price_range="100-120",
        margin_of_safety="below base",
    )

    review = build_risk_review_with_debate(_task(), decision, scenario, llm, max_rounds=2)

    assert llm.calls == [
        "aggressive:1",
        "conservative:1",
        "neutral:1",
        "aggressive:2",
        "conservative:2",
        "neutral:2",
    ]
    assert len(review.debate_history) == 6


def test_memory_resolves_pending_entries_and_returns_context(tmp_path: Path) -> None:
    memory = ResearchMemoryLog(tmp_path / "memory.jsonl")
    memory.append(
        ResearchMemoryEntry(
            task_id="old",
            entity="英伟达",
            symbols=["NVDA"],
            conclusion="观察",
            rating="watchlist",
            price_context="100",
            key_assumptions=["收入增长"],
            revisit_triggers=["财报"],
            status="pending",
        )
    )

    resolved = memory.resolve_pending(
        "NVDA",
        current_price=110.0,
        benchmark_return=0.02,
        reflection="判断有效，收入增长兑现。",
    )

    assert resolved == 1
    entries = memory.load()
    assert entries[0].status == "resolved"
    assert entries[0].raw_return == pytest.approx(0.10)
    assert entries[0].alpha_return == pytest.approx(0.08)
    assert "判断有效" in memory.context_for("英伟达")


class EndToEndLLM(EvidenceLLM, DebateLLM):
    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        if schema is ResearchTask:
            return _task()
        if schema is ResearchPlan:
            return _plan()
        if schema is EvidenceBundle:
            return EvidenceBundle(
                evidence=[
                    Evidence(
                        id="e1",
                        artifact_id="financial_statements_1",
                        category="financial_statements",
                        claim="Revenue grew 20%. EPS was 5. PE was 20.",
                        metric_name="eps",
                        metric_value=5,
                        source_title="financial source",
                    ),
                    Evidence(
                        id="e2",
                        artifact_id="financial_statements_1",
                        category="financial_statements",
                        claim="PE was 20.",
                        metric_name="pe",
                        metric_value=20,
                        source_title="financial source",
                    ),
                ]
            )
        if schema is AnalystReport:
            agent = (context or {})["agent"]
            return AnalystReport(role_id=agent, role_name=agent, conclusion="ok", confidence="high")
        if schema is DebateCase:
            return DebateLLM.complete_json(self, prompt, schema, role=role, context=context)
        if schema is ManagerDecision:
            return ManagerDecision(
                rating="deep_dive_candidate",
                core_logic=["ok"],
                key_assumptions=["收入增长", "利润率稳定", "政策可控"],
                fragile_assumption="利润率稳定",
                confidence="high",
                variant_perception="ok",
            )
        if schema is ScenarioAnalysis:
            return ScenarioAnalysis(base_case="base", bull_case="bull", bear_case="bear", target_price_range="100-120", margin_of_safety="margin")
        if schema is RiskDebateTurn:
            return RiskDebateTurn(speaker=(context or {})["speaker"], round_index=(context or {})["round_index"], view="risk")
        if schema is RiskReview:
            return RiskReview(aggressive_view="a", neutral_view="n", conservative_view="c", portfolio_context="p")
        if schema is PortfolioDecision:
            return PortfolioDecision(action="观察", position_hint="small", rationale="resume target", risk_level="medium", revisit_trigger="trigger")
        return EvidenceLLM.complete_json(self, prompt, schema, role=role, context=context)


class ExplodingSearch(NoSearch):
    pass


class SearchOK:
    def search(self, query: str, *, category: str, max_results: int = 5):
        return [
            {
                "title": f"{category} source",
                "url": f"https://example.com/{category}",
                "content": "Revenue grew 20%. EPS was 5. PE was 20.",
                "provider": "fake_search",
            }
        ]


def test_graph_returns_final_checkpoint_without_recollecting_evidence(tmp_path: Path) -> None:
    config = ResearchGraphConfig(
        checkpoint_enabled=True,
        clear_checkpoint_on_success=False,
        checkpoint_dir=tmp_path / "checkpoints",
        results_dir=tmp_path / "reports",
        memory_path=tmp_path / "memory.jsonl",
        knowledge_dir=tmp_path / "knowledge",
        fetch_source_content=False,
        selected_agents=["fundamentals", "valuation"],
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
    )
    first = ResearchGraph(config, llm_client=EndToEndLLM(), search_client=SearchOK())
    result = first.propagate("深度研究英伟达财务质量、估值和风险")

    second = ResearchGraph(config, llm_client=EndToEndLLM(), search_client=ExplodingSearch())
    resumed = second.propagate("深度研究英伟达财务质量、估值和风险")

    assert resumed.task.id == result.task.id
    assert resumed.portfolio_decision.action == "观察"
