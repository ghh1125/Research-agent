from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.visual_workflow.graph import WorkflowValidationError, topological_node_ids, validate_workflow


KNOWN_TYPES = {"start", "projectOverview", "industryAnalysis", "competitorDiscovery"}


def workflow(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def test_topological_order_is_deterministic_for_parallel_nodes() -> None:
    graph = workflow(
        [
            {"id": "start-1", "type": "start"},
            {"id": "industry-1", "type": "industryAnalysis"},
            {"id": "overview-1", "type": "projectOverview"},
            {"id": "discovery-1", "type": "competitorDiscovery"},
        ],
        [
            {"source": "start-1", "target": "overview-1"},
            {"source": "overview-1", "target": "industry-1"},
            {"source": "industry-1", "target": "discovery-1"},
        ],
    )

    validate_workflow(graph, KNOWN_TYPES)

    assert topological_node_ids(graph) == ["start-1", "overview-1", "industry-1", "discovery-1"]


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        ([{"id": "x", "type": "unknown"}], [], "未知节点类型"),
        ([{"id": "x", "type": "start"}, {"id": "x", "type": "start"}], [], "节点 ID 重复"),
        ([{"id": "x", "type": "start"}], [{"source": "x", "target": "missing"}], "不存在的节点"),
        (
            [{"id": "a", "type": "start"}, {"id": "b", "type": "projectOverview"}],
            [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
            "环",
        ),
    ],
)
def test_invalid_workflows_are_rejected(nodes, edges, message) -> None:
    with pytest.raises(WorkflowValidationError, match=message):
        validate_workflow(workflow(nodes, edges), KNOWN_TYPES)


def test_default_workflow_contains_current_pipeline_and_all_optional_dd_nodes() -> None:
    path = Path(__file__).parents[1] / "examples" / "research_workflow.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    default_types = [node["type"] for node in graph["nodes"]]

    assert default_types == [
        "start",
        "projectOverview",
        "industryAnalysis",
        "competitorDiscovery",
        "competitorAnalysis",
        "deepDueDiligence",
        "valuationAnalysis",
        "finalReport",
    ]
    assert set(graph["availableNodeTypes"]) >= {
        "teamDueDiligence",
        "businessDueDiligence",
        "financialDueDiligence",
        "techIpDueDiligence",
        "legalDueDiligence",
    }
