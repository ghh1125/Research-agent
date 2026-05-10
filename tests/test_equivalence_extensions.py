from __future__ import annotations

import sys
import types
import re
from pathlib import Path
from typing import Any

import pytest

from research_flow.analysis.tool_loop import build_analyst_reports_with_tool_loop
from research_flow.continuity.tracking import TrackingRunner, TrackingRule
from research_flow.evidence.data_registry import DataToolRegistry
from research_flow.evidence.knowledge_store import LocalKnowledgeStore, KnowledgeRecord
from research_flow.evidence.search import RealSearchClient
from research_flow.llm import RealLLMClient
from research_flow.portfolio.risk import compute_portfolio_risk_metrics
from research_flow.schema import (
    AnalystReport,
    DataArtifact,
    Evidence,
    EvidenceBundle,
    ResearchGraphConfig,
    ResearchPlan,
    ResearchTask,
)
from research_flow.settings import get_settings


def _task() -> ResearchTask:
    return ResearchTask(
        id="task_equivalence",
        raw_query="深度研究 NVDA",
        symbols=["NVDA"],
        entity="英伟达",
        market="US",
        question_type="single_stock_deep_dive",
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        task_id="task_equivalence",
        objective="证据驱动的投研判断",
        boundary="不替代投资决策",
        dimensions=[],
        selected_agents=["news_event"],
        data_sources=["news"],
        assumptions_to_verify=["新闻催化剂"],
    )


class SearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str, *, category: str, max_results: int = 5):
        self.calls.append((category, query))
        return [
            {
                "title": f"{category} evidence",
                "url": f"https://example.com/{category}",
                "content": "NVDA announced a new product catalyst.",
                "provider": "fake_search",
            }
        ]


class ToolLoopLLM:
    def __init__(self) -> None:
        self.analyst_calls = 0

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        if schema is EvidenceBundle:
            return EvidenceBundle(
                evidence=[
                    Evidence(
                        id="e_news",
                        artifact_id="news_1",
                        category="news",
                        claim="NVDA announced a new product catalyst.",
                        source_title="news evidence",
                        source_url="https://example.com/news",
                        quality="high",
                    )
                ]
            )
        if schema is AnalystReport:
            self.analyst_calls += 1
            if self.analyst_calls == 1:
                return AnalystReport(
                    role_id="news_event",
                    role_name="News/Event Analyst",
                    conclusion="证据不足，需要补充新闻。",
                    confidence="low",
                    requested_data_sources=["news"],
                    followup_queries=["NVDA latest product catalyst"],
                    open_questions=["补充近期新闻"],
                )
            return AnalystReport(
                role_id="news_event",
                role_name="News/Event Analyst",
                conclusion="新闻催化剂已用新增证据确认。",
                confidence="high",
                evidence_ids=["e_news"],
            )
        raise AssertionError(schema)


def test_analyst_tool_loop_collects_requested_evidence(tmp_path: Path) -> None:
    search = SearchClient()
    llm = ToolLoopLLM()
    registry = DataToolRegistry(
        LocalKnowledgeStore(tmp_path / "knowledge"),
        search_client=search,
        llm_client=llm,
        config=ResearchGraphConfig(fetch_source_content=False, max_agent_tool_rounds=1),
    )

    result = build_analyst_reports_with_tool_loop(_task(), _plan(), EvidenceBundle(), registry, llm)

    assert llm.analyst_calls == 2
    assert search.calls and search.calls[-1][0] == "news"
    assert result.reports[0].confidence == "high"
    assert result.bundle.evidence[0].id == "e_news"


def test_tavily_search_uses_snippets_not_raw_page_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    captured_payload: dict[str, Any] = {}

    def fake_request_json(
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        assert payload is not None
        captured_payload.update(payload)
        return {
            "results": [
                {
                    "title": "snippet source",
                    "url": "https://example.com/source",
                    "content": "short search snippet",
                    "raw_content": "raw page content " * 10000,
                }
            ]
        }

    monkeypatch.setattr("research_flow.evidence.search._request_json", fake_request_json)

    rows = RealSearchClient(get_settings()).search("NVDA revenue", category="news", max_results=1)

    assert captured_payload["include_raw_content"] is False
    assert rows[0]["content"] == "short search snippet"


class LengthGuardEvidenceLLM:
    def __init__(self, max_prompt_chars: int = 12000) -> None:
        self.max_prompt_chars = max_prompt_chars
        self.prompt_lengths: list[int] = []

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        assert schema is EvidenceBundle
        self.prompt_lengths.append(len(prompt))
        if len(prompt) > self.max_prompt_chars:
            raise RuntimeError(f"prompt too long: {len(prompt)}")
        artifact_ids = re.findall(r"\[(news_\d+)\]", prompt)
        return EvidenceBundle(
            evidence=[
                Evidence(
                    id=f"e_{artifact_id}",
                    artifact_id=artifact_id,
                    category="news",
                    claim="NVDA revenue and product catalyst evidence.",
                    source_title="source",
                    quality="medium",
                )
                for artifact_id in artifact_ids[:1]
            ]
        )


class LongSearch:
    def search(self, query: str, *, category: str, max_results: int = 5):
        return [
            {
                "title": f"{category} source {idx}",
                "url": f"https://example.com/{category}/{idx}",
                "content": "NVDA revenue growth, product catalyst, margin risk. " + ("long text " * 800),
                "provider": "fake_search",
            }
            for idx in range(1, max_results + 1)
        ]


def test_evidence_extraction_batches_and_truncates_context(tmp_path: Path) -> None:
    llm = LengthGuardEvidenceLLM()
    registry = DataToolRegistry(
        LocalKnowledgeStore(tmp_path / "knowledge"),
        search_client=LongSearch(),
        llm_client=llm,
        config=ResearchGraphConfig(fetch_source_content=False, search_max_results=9),
    )

    bundle = registry.collect(_task(), _plan().model_copy(update={"data_sources": ["news"]}))

    assert bundle.evidence
    assert len(llm.prompt_lengths) >= 2
    assert max(llm.prompt_lengths) <= llm.max_prompt_chars


class FollowupCategoryLLM:
    def __init__(self) -> None:
        self.analyst_round = 0

    def complete_json(self, prompt: str, schema: type, *, role: str = "quick", context: dict[str, Any] | None = None):
        if schema is EvidenceBundle:
            artifact_ids = re.findall(r"\[(macro_\d+|market_data_\d+)\]", prompt)
            return EvidenceBundle(
                evidence=[
                    Evidence(
                        id=f"e_{artifact_id}",
                        artifact_id=artifact_id,
                        category=artifact_id.rsplit("_", 1)[0],
                        claim="follow-up evidence",
                        source_title="source",
                    )
                    for artifact_id in artifact_ids[:1]
                ]
            )
        if schema is AnalystReport:
            agent = (context or {})["agent"]
            self.analyst_round += 1
            if self.analyst_round <= 2:
                if agent == "macro":
                    return AnalystReport(
                        role_id=agent,
                        role_name=agent,
                        conclusion="需要宏观补证",
                        confidence="low",
                        requested_data_sources=["国家统计局 (2024-2025年GDP、工业增加值数据)"],
                        followup_queries=[
                            "2024-2025年中国GDP 工业增加值 国家统计局",
                            "中国政策 利率 汇率 2025",
                            "宏观 周期 新能源汽车 需求",
                            "国家统计局 社会消费品零售 2025",
                        ],
                    )
                return AnalystReport(
                    role_id=agent,
                    role_name=agent,
                    conclusion="需要持仓补证",
                    confidence="low",
                    requested_data_sources=["基金持仓报告（公募基金季度持仓明细）"],
                    followup_queries=[
                        "获取宁德时代日频技术指标数据",
                        "查询同期北向资金对宁德时代的每日持股变化及资金流向",
                        "查询融资融券余额及交易明细",
                        "获取最近一期公募基金对宁德时代的持仓及变动数据",
                    ],
                )
            return AnalystReport(
                role_id=agent,
                role_name=agent,
                conclusion="补证完成",
                confidence="high",
                evidence_ids=["e_macro_1"],
            )
        raise AssertionError(schema)


class RecordingSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str, *, category: str, max_results: int = 5):
        self.calls.append((category, query))
        return [
            {
                "title": f"{category} source",
                "url": f"https://example.com/{category}",
                "content": "follow-up evidence",
                "provider": "fake_search",
            }
        ]


def test_tool_loop_normalizes_and_caps_followup_categories(tmp_path: Path) -> None:
    search = RecordingSearch()
    llm = FollowupCategoryLLM()
    registry = DataToolRegistry(
        LocalKnowledgeStore(tmp_path / "knowledge"),
        search_client=search,
        llm_client=llm,
        config=ResearchGraphConfig(
            fetch_source_content=False,
            search_max_results=1,
            max_followup_queries_per_round=4,
            max_followup_categories_per_round=2,
        ),
    )
    plan = ResearchPlan(
        task_id="task_equivalence",
        objective="follow-up category normalization",
        boundary="test",
        dimensions=[],
        selected_agents=["macro", "technical_positioning"],
        data_sources=["macro", "market_data", "news"],
    )

    build_analyst_reports_with_tool_loop(_task(), plan, EvidenceBundle(), registry, llm, max_rounds=1)

    categories = [category for category, _ in search.calls]
    assert categories
    assert set(categories) <= {"macro", "market_data"}
    assert "国家统计局 (2024-2025年GDP、工业增加值数据)" not in categories
    assert "基金持仓报告（公募基金季度持仓明细）" not in categories
    assert len(search.calls) <= 4


def test_local_knowledge_store_supports_vector_style_retrieval(tmp_path: Path) -> None:
    store = LocalKnowledgeStore(tmp_path / "knowledge", search_mode="hybrid")
    store.add(KnowledgeRecord(id="1", kind="note", title="battery margin", content="gross margin pressure from price war", metadata={}))
    store.add(KnowledgeRecord(id="2", kind="note", title="cloud ai demand", content="accelerator demand and datacenter capex remain strong", metadata={}))

    results = store.search("datacenter accelerator demand", limit=1)

    assert results[0].id == "2"


def test_portfolio_risk_metrics_from_market_artifact() -> None:
    artifact = DataArtifact(
        id="market",
        category="market_data",
        title="price history",
        source_type="market_data",
        provider="test",
        content=(
            "## price_history\n"
            "Date,Close,Volume\n"
            "2026-01-01,100,1000000\n"
            "2026-01-02,110,1200000\n"
            "2026-01-03,105,900000\n"
            "2026-01-04,120,1300000\n"
        ),
    )

    metrics = compute_portfolio_risk_metrics(EvidenceBundle(artifacts=[artifact]), positions={"NVDA": 0.25})

    assert metrics["max_drawdown"] < 0
    assert metrics["annualized_volatility"] > 0
    assert metrics["largest_position_weight"] == pytest.approx(0.25)


def test_tracking_runner_fires_price_and_news_alerts() -> None:
    runner = TrackingRunner(
        [
            TrackingRule(symbol="NVDA", kind="price_below", threshold=90, label="估值区间"),
            TrackingRule(symbol="NVDA", kind="news_keyword", keyword="export control", label="政策风险"),
        ]
    )

    events = runner.evaluate("NVDA", price=88, news_titles=["US export control update for chips"])

    assert {event.label for event in events} == {"估值区间", "政策风险"}


def test_real_llm_provider_candidates_respect_task_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "default-model")
    monkeypatch.setenv("OPENAI_DEEP_MODEL", "default-deep")

    client = RealLLMClient(get_settings())

    assert client.provider_candidates(role="deep")[0].model == "default-deep"
    assert client.provider_candidates(role="deep", explicit_model="task-deep")[0].model == "task-deep"


def test_default_config_does_not_fetch_full_source_content() -> None:
    assert ResearchGraphConfig().fetch_source_content is False


def test_real_llm_client_emits_provider_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_QUICK_MODEL", "")
    monkeypatch.setenv("OPENAI_DEEP_MODEL", "")
    events: list[str] = []

    class FakeCompletions:
        def create(self, **kwargs: Any):
            assert kwargs["model"] == "test-model"
            message = types.SimpleNamespace(
                content=(
                    '{"id":"task_progress","raw_query":"研究 NVDA","symbols":["NVDA"],'
                    '"entity":"英伟达","market":"US","question_type":"single_stock_deep_dive"}'
                )
            )
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float = 60,
            max_retries: int = 0,
        ) -> None:
            assert api_key == "test-key"
            assert max_retries == 0
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    client = RealLLMClient(get_settings(), progress_callback=events.append)
    task = client.complete_json("return a task", ResearchTask, role="quick")

    assert task.id == "task_progress"
    assert any("llm[quick] schema=ResearchTask provider=openai model=test-model start" in event for event in events)
    assert any("llm[quick] schema=ResearchTask provider=openai model=test-model done" in event for event in events)


def test_real_llm_client_tries_comma_separated_models_after_quota_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "dashscope")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_QUICK_MODEL", "quota-model,working-model")
    events: list[str] = []
    models: list[str] = []

    class FakeCompletions:
        def create(self, **kwargs: Any):
            model = kwargs["model"]
            models.append(model)
            if model == "quota-model":
                raise RuntimeError("AllocationQuota.FreeTierOnly: The free tier of the model has been exhausted")
            message = types.SimpleNamespace(
                content=(
                    '{"id":"task_fallback","raw_query":"研究 NVDA","symbols":["NVDA"],'
                    '"entity":"英伟达","market":"US","question_type":"single_stock_deep_dive"}'
                )
            )
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float = 60,
            max_retries: int = 0,
        ) -> None:
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    client = RealLLMClient(get_settings(), progress_callback=events.append)
    task = client.complete_json("return a task", ResearchTask, role="quick")

    assert task.id == "task_fallback"
    assert models == ["quota-model", "working-model"]
    assert any("model=quota-model error=RuntimeError" in event for event in events)
    assert any("model=working-model done" in event for event in events)


def test_real_llm_client_explains_dashscope_free_tier_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "dashscope")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_QUICK_MODEL", "quota-model")

    class FakeCompletions:
        def create(self, **kwargs: Any):
            raise RuntimeError("AllocationQuota.FreeTierOnly: The free tier of the model has been exhausted")

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float = 60,
            max_retries: int = 0,
        ) -> None:
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    client = RealLLMClient(get_settings())
    with pytest.raises(RuntimeError) as exc_info:
        client.complete_json("return a task", ResearchTask, role="quick")

    message = str(exc_info.value)
    assert "AllocationQuota.FreeTierOnly" in message
    assert "disable free tier only" in message
    assert "DASHSCOPE_QUICK_MODEL" in message
