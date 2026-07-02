from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest

from src.visual_workflow.registry import FileField, NodeDefinition
from src.visual_workflow.workflow_store import WorkflowStore, sanitize_workflow


def test_workflow_store_persists_and_updates_same_record(tmp_path: Path) -> None:
    database = tmp_path / "workflows.db"
    store = WorkflowStore(database)
    created = store.create(
        name="我的投研流程",
        description="第一次保存",
        workflow={"nodes": [{"id": "n1", "type": "noop"}], "edges": []},
    )

    reopened = WorkflowStore(database)
    loaded = reopened.get(created["id"])
    assert loaded["name"] == "我的投研流程"
    assert loaded["workflow"]["nodes"][0]["id"] == "n1"

    updated = reopened.update(
        created["id"],
        name="更新后的流程",
        description="打开旧流程后覆盖保存",
        workflow={"nodes": [{"id": "n1", "type": "noop", "x": 240}], "edges": []},
    )

    assert updated["id"] == created["id"]
    assert updated["createdAt"] == created["createdAt"]
    assert updated["name"] == "更新后的流程"
    assert reopened.get(created["id"])["workflow"]["nodes"][0]["x"] == 240
    assert [item["id"] for item in reopened.list_workflows()] == [created["id"]]


def test_workflow_store_deletes_record(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows.db")
    created = store.create(name="待删除", description="", workflow={"nodes": [], "edges": []})

    store.delete(created["id"])

    assert store.list_workflows() == []
    with pytest.raises(KeyError, match="工作流不存在"):
        store.get(created["id"])


def test_sanitize_workflow_removes_runtime_and_uploaded_files() -> None:
    registry = OrderedDict(
        [
            (
                "start",
                NodeDefinition(
                    "start",
                    "开始",
                    (),
                    ("project_input",),
                    lambda state, config, services, runtime: {},
                    file_fields=(FileField("bp_files", "BP"),),
                ),
            )
        ]
    )
    workflow = {
        "name": "自定义流程",
        "nodes": [
            {
                "id": "start-1",
                "type": "start",
                "x": 100,
                "y": 200,
                "status": "completed",
                "config": {
                    "display_name": "竞品搜索",
                    "bp_files": ["/tmp/private-bp.pdf"],
                    "llm_steps": {
                        "start_normalization": {
                            "model": "qwen3.7-plus",
                            "prompt": "自定义 {raw_input}",
                        }
                    },
                },
            }
        ],
        "edges": [],
    }

    sanitized = sanitize_workflow(workflow, registry)

    node = sanitized["nodes"][0]
    assert "status" not in node
    assert "bp_files" not in node["config"]
    assert node["config"]["display_name"] == "竞品搜索"
    assert node["config"]["llm_steps"]["start_normalization"]["prompt"] == "自定义 {raw_input}"
    assert workflow["nodes"][0]["config"]["bp_files"] == ["/tmp/private-bp.pdf"]
