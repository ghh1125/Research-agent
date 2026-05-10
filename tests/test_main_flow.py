from __future__ import annotations

from pathlib import Path
from typing import Any

from main import run_query
from research_flow.graph import ResearchGraph, ResearchGraphConfig
from research_flow.schema import (
    AnalystReport,
    DebateCase,
    ManagerDecision,
    PortfolioDecision,
    Evidence,
    EvidenceBundle,
    ResearchPlan,
    ResearchTask,
    RiskDebateTurn,
    RiskReview,
    ScenarioAnalysis,
)


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        self.calls.append(f"{schema.__name__}:{role}:{(context or {}).get('agent', '')}{(context or {}).get('side', '')}")
        if schema is ResearchTask:
            return ResearchTask(
                id="task_llm",
                raw_query="深度研究宁德时代",
                symbols=["300750.SZ"],
                entity="宁德时代",
                market="A_share",
                question_type="single_stock_deep_dive",
                research_depth="deep",
                risk_preference="neutral",
            )
        if schema is ResearchPlan:
            return ResearchPlan(
                task_id="task_llm",
                objective="形成宁德时代有证据链的深度投研判断",
                boundary="不直接给交易指令",
                selected_agents=["macro", "industry", "fundamentals", "valuation", "news_event", "technical_positioning"],
                data_sources=["market_data", "financial_statements", "filings", "news", "macro", "industry", "valuation", "knowledge"],
                dimensions=[],
                assumptions_to_verify=["收入增长", "毛利率", "海外政策"],
            )
        if schema is EvidenceBundle:
            return EvidenceBundle(
                evidence=[
                    Evidence(
                        id="e1",
                        artifact_id="financial_statements_1",
                        category="financial_statements",
                        claim="收入增长 12%，毛利率 24%。",
                        metric_name="revenue_growth",
                        metric_value=12,
                        unit="%",
                        period="latest",
                        source_title="financial source",
                        source_url="https://example.com/financial_statements",
                        quality="high",
                    )
                ]
            )
        if schema is AnalystReport:
            agent = (context or {})["agent"]
            return AnalystReport(
                role_id=agent,
                role_name=agent,
                conclusion=f"{agent} 基于证据完成分析",
                key_points=["收入增长有证据", "毛利率需要跟踪"],
                evidence_ids=["e1"],
                data_sources=["source"],
                confidence="high",
            )
        if schema is DebateCase:
            side = (context or {})["side"]
            return DebateCase(
                side=side,
                thesis=f"{side} thesis",
                arguments=["argument"],
                key_disagreements=["毛利率"],
                falsification_tests=["财报证伪"],
                evidence_ids=["e1"],
            )
        if schema is ManagerDecision:
            return ManagerDecision(
                rating="deep_dive_candidate",
                core_logic=["基本面、估值、风险需要同时验证"],
                key_assumptions=["收入增长", "毛利率稳定", "海外政策可控"],
                fragile_assumption="毛利率稳定",
                confidence="high",
                variant_perception="市场低估毛利率韧性",
                tracking_metrics=["收入增速", "毛利率"],
                verification_path=["补齐财报", "跟踪新闻"],
            )
        if schema is ScenarioAnalysis:
            return ScenarioAnalysis(
                base_case="收入增长放缓但现金流保持",
                bull_case="储能和海外需求超预期",
                bear_case="价格战压缩利润率",
                target_price_range="base/bull/bear 目标价区间",
                margin_of_safety="低于 base 估值才有安全边际",
                key_drivers=["收入增速", "毛利率", "折现率"],
                evidence_ids=["e1"],
            )
        if schema is RiskReview:
            return RiskReview(
                aggressive_view="上行弹性来自需求超预期",
                neutral_view="等待毛利率确认",
                conservative_view="永久损失来自价格战和政策",
                risk_flags=["价格战", "海外政策"],
                portfolio_context="组合相关性需要检查",
            )
        if schema is RiskDebateTurn:
            speaker = (context or {})["speaker"]
            return RiskDebateTurn(
                speaker=speaker,
                round_index=(context or {})["round_index"],
                view=f"{speaker} risk view",
                risk_flags=[speaker],
            )
        if schema is PortfolioDecision:
            return PortfolioDecision(
                action="值得进一步研究",
                position_hint="进入研究池",
                rationale="证据足以继续深挖",
                risk_level="medium",
                revisit_trigger="财报和价格触发",
            )
        raise AssertionError(schema)


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    def search(self, query: str, *, category: str, max_results: int = 5):
        self.queries.append((category, query))
        return [
            {
                "title": f"{category} source",
                "url": f"https://example.com/{category}",
                "content": "宁德时代 revenue growth 12%, gross margin 24%, overseas policy risk.",
                "provider": "fake_search",
            }
        ]


def test_main_entry_runs_real_provider_interfaces_through_five_layer_flow(tmp_path: Path) -> None:
    llm = FakeLLM()
    search = FakeSearch()
    result = run_query(
        "深度研究宁德时代的行业竞争、财务质量、估值和风险，判断是否值得进一步研究",
        config=ResearchGraphConfig(
            results_dir=tmp_path / "reports",
            memory_path=tmp_path / "memory.jsonl",
            knowledge_dir=tmp_path / "knowledge",
            fetch_source_content=False,
        ),
        llm_client=llm,
        search_client=search,
    )

    assert result.task.question_type == "single_stock_deep_dive"
    assert result.task.symbols == ["300750.SZ"]
    assert result.plan.selected_agents == ["macro", "industry", "fundamentals", "valuation", "news_event", "technical_positioning"]
    assert {category for category, _ in search.queries} >= {"market_data", "financial_statements", "filings", "news", "macro", "industry", "valuation"}
    assert any(call.startswith("ResearchTask:quick") for call in llm.calls)
    assert sum(call.startswith("AnalystReport:deep") for call in llm.calls) == 6
    assert any(call.startswith("ManagerDecision:deep") for call in llm.calls)
    assert [stage.name for stage in result.stage_trace] == [
        "任务理解与研究规划",
        "数据检索与证据沉淀",
        "多 Agent 专项分析",
        "投资判断、估值与风险裁决",
        "报告输出、记忆复盘与持续跟踪",
    ]
    assert "# 投研报告" in result.report.markdown
    assert "## 数据来源" in result.report.markdown
    assert (tmp_path / "memory.jsonl").exists()
    assert (tmp_path / "knowledge" / "records.jsonl").exists()


def test_progress_callback_reports_runtime_steps_and_data_tools(tmp_path: Path) -> None:
    events: list[str] = []

    result = run_query(
        "深度研究宁德时代的行业竞争、财务质量、估值和风险，判断是否值得进一步研究",
        config=ResearchGraphConfig(
            results_dir=tmp_path / "reports",
            memory_path=tmp_path / "memory.jsonl",
            knowledge_dir=tmp_path / "knowledge",
            fetch_source_content=False,
        ),
        llm_client=FakeLLM(),
        search_client=FakeSearch(),
        progress_callback=events.append,
    )

    assert result.portfolio_decision.action == "值得进一步研究"
    assert any(event.startswith("[runtime] LLM") for event in events)
    assert any(event.startswith("[runtime] Search") for event in events)
    assert any(event.startswith("[step 1/5] 任务理解与研究规划 start") for event in events)
    assert any(event.startswith("[step 2/5] 数据检索与证据沉淀 start") for event in events)
    assert any("data[market_data]" in event for event in events)
    assert any("search[market_data] query=" in event for event in events)
    assert any(event.startswith("[step 3/5] 多 Agent 专项分析 start") for event in events)
    assert any("bull/bear debate start" in event for event in events)
    assert any(event.startswith("[step 4/5] 投资判断、估值与风险裁决 done") for event in events)
    assert any(event.startswith("[step 5/5] 报告输出、记忆复盘与持续跟踪 done") for event in events)


def test_checkpoint_resume_records_stage_state(tmp_path: Path) -> None:
    graph = ResearchGraph(
        ResearchGraphConfig(
            checkpoint_enabled=True,
            clear_checkpoint_on_success=False,
            checkpoint_dir=tmp_path / "checkpoints",
            results_dir=tmp_path / "reports",
            memory_path=tmp_path / "memory.jsonl",
            knowledge_dir=tmp_path / "knowledge",
            fetch_source_content=False,
        ),
        llm_client=FakeLLM(),
        search_client=FakeSearch(),
    )

    result = graph.propagate("研究阿里巴巴财务质量、现金流、估值和行业竞争")

    checkpoint = tmp_path / "checkpoints" / f"{result.task.id}.json"
    assert checkpoint.exists()
    assert '"last_stage": "报告输出、记忆复盘与持续跟踪"' in checkpoint.read_text(encoding="utf-8")
