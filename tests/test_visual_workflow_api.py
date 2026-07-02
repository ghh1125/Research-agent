from __future__ import annotations

import base64
import json
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

from src.visual_workflow.api_server import create_server, save_uploads
from src.visual_workflow.executor import WorkflowExecutor
from src.visual_workflow.registry import NodeDefinition, WorkflowServices
from src.visual_workflow.run_store import RunStore
from src.visual_workflow.workflow_store import WorkflowStore


class DummyServices(WorkflowServices):
    def __init__(self):
        object.__setattr__(self, "pipeline", None)


def wait_for_status(store: RunStore, run_id: str, expected: str) -> dict:
    deadline = time.time() + 2
    while time.time() < deadline:
        current = store.get_run(run_id)
        if current["status"] == expected:
            return current
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}: {store.get_run(run_id)}")


def json_request(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_run_store_pauses_and_resumes_same_background_run() -> None:
    def report(state, config, services, runtime):
        return {"report": {"markdown": runtime.get("feedback") or "first"}}

    registry = OrderedDict(
        [
            (
                "report",
                NodeDefinition("report", "Report", (), ("report",), report, checkpoint="report_review"),
            )
        ]
    )
    store = RunStore(WorkflowExecutor(registry))
    run_id = store.create_run(
        {"nodes": [{"id": "report-1", "type": "report"}], "edges": []},
        DummyServices(),
    )

    waiting = wait_for_status(store, run_id, "waiting")
    assert waiting["checkpoint"]["checkpoint"] == "report_review"
    assert store.resume_run(run_id, {"action": "regenerate", "feedback": "补充证据"})["status"] in {
        "running",
        "waiting",
    }
    wait_for_status(store, run_id, "waiting")
    store.resume_run(run_id, {"action": "approve"})

    completed = wait_for_status(store, run_id, "completed")
    assert completed["result"]["state"]["report"]["markdown"] == "补充证据"
    assert "apiKeys" not in json.dumps(completed)
    assert store.get_events(run_id, 0)["next"] >= 3


def test_save_uploads_decodes_content_and_confines_filename(tmp_path: Path) -> None:
    payload = {
        "files": [
            {
                "name": "../../财务报表.xlsx",
                "content": base64.b64encode(b"spreadsheet").decode("ascii"),
            }
        ]
    }

    result = save_uploads(payload, tmp_path)

    saved = Path(result[0]["path"])
    assert saved.parent.parent == tmp_path
    assert saved.name == "财务报表.xlsx"
    assert saved.read_bytes() == b"spreadsheet"


def test_http_api_serves_catalog_example_validation_and_upload(tmp_path: Path) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<h1>workflow</h1>", encoding="utf-8")
    example = tmp_path / "example.json"
    example.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    upload_root = tmp_path / "uploads"
    registry = OrderedDict(
        [("noop", NodeDefinition("noop", "No-op", (), (), lambda state, config, services, runtime: {}))]
    )
    server = create_server(
        host="127.0.0.1",
        port=0,
        registry=registry,
        web_root=web_root,
        example_path=example,
        upload_root=upload_root,
    )
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/api/functions") as response:
            assert json.load(response)[0]["type"] == "noop"
        with urllib.request.urlopen(f"{base}/api/examples/research-workflow") as response:
            assert json.load(response) == {"nodes": [], "edges": []}

        body = json.dumps(
            {"workflow": {"nodes": [{"id": "n1", "type": "noop"}], "edges": []}}
        ).encode()
        request = urllib.request.Request(
            f"{base}/api/workflows/validate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert json.load(response) == {"valid": True, "order": ["n1"]}

        upload_body = json.dumps(
            {"files": [{"name": "bp.pdf", "content": base64.b64encode(b"pdf").decode()}]}
        ).encode()
        upload_request = urllib.request.Request(
            f"{base}/api/uploads",
            data=upload_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(upload_request) as response:
            uploaded = json.load(response)["files"][0]
        assert Path(uploaded["path"]).read_bytes() == b"pdf"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_api_creates_opens_updates_and_deletes_saved_workflow(tmp_path: Path) -> None:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<h1>workflow</h1>", encoding="utf-8")
    example = tmp_path / "example.json"
    example.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    registry = OrderedDict(
        [("noop", NodeDefinition("noop", "No-op", (), (), lambda state, config, services, runtime: {}))]
    )
    server = create_server(
        host="127.0.0.1",
        port=0,
        registry=registry,
        web_root=web_root,
        example_path=example,
        upload_root=tmp_path / "uploads",
        workflow_store=WorkflowStore(tmp_path / "workflows.db"),
    )
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    workflow = {"nodes": [{"id": "n1", "type": "noop", "x": 10}], "edges": []}
    try:
        created = json_request(
            f"{base}/api/workflows",
            method="POST",
            payload={"name": "旧工作流", "description": "初始", "workflow": workflow},
        )
        workflow_id = created["id"]
        assert json_request(f"{base}/api/workflows")[0]["id"] == workflow_id
        assert json_request(f"{base}/api/workflows/{workflow_id}")["name"] == "旧工作流"

        workflow["nodes"][0]["x"] = 500
        updated = json_request(
            f"{base}/api/workflows/{workflow_id}",
            method="PUT",
            payload={"name": "更新后的工作流", "description": "覆盖保存", "workflow": workflow},
        )
        assert updated["id"] == workflow_id
        assert updated["workflow"]["nodes"][0]["x"] == 500
        assert len(json_request(f"{base}/api/workflows")) == 1

        deleted = json_request(f"{base}/api/workflows/{workflow_id}", method="DELETE")
        assert deleted == {"deleted": True, "id": workflow_id}
        assert json_request(f"{base}/api/workflows") == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
