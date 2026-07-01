from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path

from src.pipeline import BPPipeline
from src.visual_workflow.executor import WorkflowExecutor
from src.visual_workflow.registry import NodeDefinition, WorkflowServices, get_node_registry


class DummyServices(WorkflowServices):
    def __init__(self):
        object.__setattr__(self, "pipeline", None)


def test_executor_accumulates_shared_state_in_topological_order_and_skips_missing_inputs() -> None:
    calls: list[str] = []

    def run_start(state, config, services, runtime):
        calls.append("start")
        return {"project_input": config["value"]}

    def run_report(state, config, services, runtime):
        calls.append("report")
        return {"report": f"{state['project_input']}-report"}

    def run_missing(state, config, services, runtime):
        raise AssertionError("runner must not be called")

    registry = OrderedDict(
        (
            definition.type,
            definition,
        )
        for definition in [
            NodeDefinition("start", "Start", (), ("project_input",), run_start),
            NodeDefinition("report", "Report", ("project_input",), ("report",), run_report),
            NodeDefinition("missing", "Missing", ("never_created",), ("unused",), run_missing),
        ]
    )
    graph = {
        "nodes": [
            {"id": "missing-1", "type": "missing"},
            {"id": "report-1", "type": "report"},
            {"id": "start-1", "type": "start", "config": {"value": "acme"}},
        ],
        "edges": [
            {"source": "start-1", "target": "report-1"},
            {"source": "report-1", "target": "missing-1"},
        ],
    }

    result = WorkflowExecutor(registry).execute(graph, DummyServices())

    assert calls == ["start", "report"]
    assert result.state["report"] == "acme-report"
    assert [item.status for item in result.nodes] == ["completed", "completed", "skipped"]
    assert result.nodes[-1].missing_inputs == ["never_created"]


def test_executor_continues_after_a_failed_node() -> None:
    def fail(state, config, services, runtime):
        raise RuntimeError("broken node")

    def independent(state, config, services, runtime):
        return {"ok": True}

    registry = OrderedDict(
        [
            ("fail", NodeDefinition("fail", "Fail", (), ("bad",), fail)),
            ("independent", NodeDefinition("independent", "Independent", (), ("ok",), independent)),
        ]
    )
    graph = {
        "nodes": [{"id": "fail-1", "type": "fail"}, {"id": "independent-1", "type": "independent"}],
        "edges": [],
    }

    result = WorkflowExecutor(registry).execute(graph, DummyServices())

    assert [item.status for item in result.nodes] == ["failed", "completed"]
    assert result.nodes[0].error == "broken node"
    assert result.state["ok"] is True


def test_report_review_regenerates_only_with_explicit_feedback() -> None:
    feedback_seen: list[str | None] = []
    decisions = iter(
        [
            {"action": "regenerate", "feedback": "补充来源和关键里程碑"},
            {"action": "approve"},
        ]
    )

    def report(state, config, services, runtime):
        feedback_seen.append(runtime.get("feedback"))
        return {"project_overview": {"markdown": runtime.get("feedback") or "first"}}

    registry = OrderedDict(
        [
            (
                "projectOverview",
                NodeDefinition(
                    "projectOverview",
                    "Overview",
                    (),
                    ("project_overview",),
                    report,
                    checkpoint="report_review",
                ),
            )
        ]
    )
    graph = {"nodes": [{"id": "overview-1", "type": "projectOverview"}], "edges": []}

    result = WorkflowExecutor(registry).execute(
        graph,
        DummyServices(),
        checkpoint_callback=lambda request: next(decisions),
    )

    assert feedback_seen == [None, "补充来源和关键里程碑"]
    assert result.state["project_overview"]["markdown"] == "补充来源和关键里程碑"


def test_competitor_selection_and_two_review_actions_are_forwarded_to_runner() -> None:
    runtimes: list[dict] = []
    decisions = iter(
        [
            {"action": "select", "selected_ids": ["c1", "c2"]},
            {"action": "resynthesize", "feedback": "统一比较口径"},
            {"action": "reanalyze", "feedback": "补充价格证据"},
            {"action": "approve"},
        ]
    )

    def discover(state, config, services, runtime):
        return {"competitor_discovery": {"candidates": [{"id": "c1"}, {"id": "c2"}], "selected_ids": []}}

    def analyze(state, config, services, runtime):
        runtimes.append(dict(runtime))
        return {"competitor_analysis": {"markdown": runtime.get("mode", "initial")}}

    registry = OrderedDict(
        [
            (
                "competitorDiscovery",
                NodeDefinition(
                    "competitorDiscovery",
                    "Discovery",
                    (),
                    ("competitor_discovery",),
                    discover,
                    checkpoint="competitor_selection",
                ),
            ),
            (
                "competitorAnalysis",
                NodeDefinition(
                    "competitorAnalysis",
                    "Analysis",
                    ("competitor_discovery",),
                    ("competitor_analysis",),
                    analyze,
                    checkpoint="competitor_report_review",
                ),
            ),
        ]
    )
    graph = {
        "nodes": [
            {"id": "discovery-1", "type": "competitorDiscovery"},
            {"id": "analysis-1", "type": "competitorAnalysis"},
        ],
        "edges": [{"source": "discovery-1", "target": "analysis-1"}],
    }

    result = WorkflowExecutor(registry).execute(
        graph,
        DummyServices(),
        checkpoint_callback=lambda request: next(decisions),
    )

    assert result.state["competitor_discovery"]["selected_ids"] == ["c1", "c2"]
    assert runtimes == [
        {},
        {"mode": "resynthesize", "feedback": "统一比较口径"},
        {"mode": "reanalyze", "feedback": "补充价格证据"},
    ]
    assert result.state["competitor_analysis"]["markdown"] == "reanalyze"


def test_default_visual_workflow_runs_the_existing_pipeline(fake_llm_client, fake_search_client) -> None:
    graph = json.loads(
        (Path(__file__).parents[1] / "examples" / "research_workflow.json").read_text(encoding="utf-8")
    )
    graph["nodes"][0]["config"] = {
        "company_name": "示例科技",
        "industry": "人工智能",
        "project_description": "企业级 AI 软件",
    }
    services = WorkflowServices(
        pipeline=BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    )

    def approve(request):
        if request["checkpoint"] == "competitor_selection":
            candidates = request["outputs"]["competitor_discovery"]["candidates"]
            return {"action": "select", "selected_ids": [candidates[0]["id"]]}
        return {"action": "approve"}

    result = WorkflowExecutor(get_node_registry()).execute(
        graph,
        services,
        checkpoint_callback=approve,
    )

    assert result.status == "completed"
    assert result.state["due_diligence"].markdown
    assert "项目投研报告" in result.state["final_report"].markdown


def test_team_only_workflow_still_runs_valuation_and_final_report(fake_llm_client, fake_search_client) -> None:
    graph = json.loads(
        (Path(__file__).parents[1] / "examples" / "research_workflow.json").read_text(encoding="utf-8")
    )
    graph["nodes"][0]["config"] = {
        "company_name": "示例科技",
        "industry": "人工智能",
        "project_description": "企业级 AI 软件",
    }
    graph["nodes"] = [node for node in graph["nodes"] if node["type"] != "deepDueDiligence"]
    graph["nodes"].insert(
        5,
        {"id": "team-1", "type": "teamDueDiligence", "x": 1260, "y": 120, "config": {}},
    )
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if edge["source"] != "dd-1" and edge["target"] != "dd-1"
    ]
    graph["edges"].extend(
        [
            {"source": "competitor-1", "target": "team-1"},
            {"source": "team-1", "target": "valuation-1"},
        ]
    )
    services = WorkflowServices(
        pipeline=BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    )

    def approve(request):
        if request["checkpoint"] == "competitor_selection":
            candidates = request["outputs"]["competitor_discovery"]["candidates"]
            return {"action": "select", "selected_ids": [candidates[0]["id"]]}
        return {"action": "approve"}

    result = WorkflowExecutor(get_node_registry()).execute(
        graph,
        services,
        checkpoint_callback=approve,
    )

    assert result.status == "completed"
    assert result.state["due_diligence"].completed_categories == ["团队"]
    assert result.state["due_diligence"].missing_categories == [
        "业务",
        "财务",
        "技术与知识产权",
        "法律",
    ]
    assert result.state["valuation_analysis"] is not None
    assert result.state["final_report"] is not None


def test_node_instance_name_is_used_in_execution_status() -> None:
    registry = OrderedDict(
        [("noop", NodeDefinition("noop", "默认名称", (), ("ok",), lambda state, config, services, runtime: {"ok": True}))]
    )
    graph = {
        "nodes": [
            {
                "id": "noop-1",
                "type": "noop",
                "config": {
                    "display_name": "投委会专用分析",
                    "description": "仅供本轮投委会使用",
                },
            }
        ],
        "edges": [],
    }

    result = WorkflowExecutor(registry).execute(graph, DummyServices())

    assert result.nodes[0].name == "投委会专用分析"
    assert result.nodes[0].description == "仅供本轮投委会使用"
