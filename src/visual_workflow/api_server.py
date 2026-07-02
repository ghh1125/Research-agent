from __future__ import annotations

import base64
import dataclasses
import json
import mimetypes
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from src.llm import RealLLMClient
from src.pipeline import BPPipeline
from src.search import RealSearchClient
from src.settings import get_settings
from src.visual_workflow.executor import WorkflowExecutor
from src.visual_workflow.graph import topological_node_ids, validate_workflow
from src.visual_workflow.registry import (
    NodeDefinition,
    WorkflowServices,
    get_node_registry,
    validate_workflow_node_configs,
)
from src.visual_workflow.run_store import RunStore
from src.visual_workflow.workflow_store import WorkflowStore, sanitize_workflow

_API_KEY_FIELDS = {
    "openaiApiKey": "openai_api_key",
    "dashscopeApiKey": "dashscope_api_key",
    "openrouterApiKey": "openrouter_api_key",
    "deepseekApiKey": "deepseek_api_key",
    "tavilyApiKey": "tavily_api_key",
    "serperApiKey": "serper_api_key",
    "googleSearchApiKey": "google_search_api_key",
    "googleSearchCx": "google_search_cx",
}


def save_uploads(payload: dict[str, Any], upload_root: Path) -> list[dict[str, str]]:
    target = Path(upload_root) / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, str]] = []
    for item in payload.get("files", []):
        name = Path(str(item.get("name") or "upload.bin").replace("\x00", "")).name
        if name in {"", ".", ".."}:
            name = "upload.bin"
        try:
            content = base64.b64decode(item.get("content", ""), validate=True)
        except Exception as exc:
            raise ValueError(f"文件 {name} 的 Base64 内容无效") from exc
        path = target / name
        path.write_bytes(content)
        result.append({"name": name, "path": str(path.resolve())})
    return result


def build_services(api_keys: dict[str, Any] | None = None) -> WorkflowServices:
    overrides = {}
    for public_name, settings_name in _API_KEY_FIELDS.items():
        value = str((api_keys or {}).get(public_name) or "").strip()
        if value:
            overrides[settings_name] = value
    settings = dataclasses.replace(get_settings(), **overrides)
    pipeline = BPPipeline(
        llm_client=RealLLMClient(settings=settings),
        search_client=RealSearchClient(settings=settings),
    )
    return WorkflowServices(pipeline=pipeline)


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    registry: Mapping[str, NodeDefinition] | None = None,
    web_root: Path | None = None,
    example_path: Path | None = None,
    upload_root: Path | None = None,
    run_store: RunStore | None = None,
    workflow_store: WorkflowStore | None = None,
) -> ThreadingHTTPServer:
    project_root = Path(__file__).resolve().parents[2]
    registry = registry or get_node_registry()
    web_root = Path(web_root or project_root / "workflow_web").resolve()
    example_path = Path(example_path or project_root / "examples" / "research_workflow.json").resolve()
    upload_root = Path(upload_root or project_root / "data" / "workflow_uploads").resolve()
    run_store = run_store or RunStore(WorkflowExecutor(registry))
    workflow_store = workflow_store or WorkflowStore(project_root / "data" / "workflows.db")

    class WorkflowHandler(BaseHTTPRequestHandler):
        server_version = "ResearchWorkflowDemo/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/functions":
                    self._json([item.to_catalog_item() for item in registry.values()])
                elif parsed.path == "/api/examples/research-workflow":
                    self._json(json.loads(example_path.read_text(encoding="utf-8")))
                elif parsed.path == "/api/workflows":
                    self._json(workflow_store.list_workflows())
                elif parsed.path.startswith("/api/workflows/"):
                    self._json(workflow_store.get(self._workflow_id(parsed.path)))
                elif parsed.path.startswith("/api/runs/"):
                    self._get_run_route(parsed)
                else:
                    self._static(parsed.path)
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/uploads":
                    self._json({"files": save_uploads(payload, upload_root)}, HTTPStatus.CREATED)
                elif parsed.path == "/api/workflows/validate":
                    workflow = payload.get("workflow") or payload
                    validate_workflow(workflow, registry.keys())
                    validate_workflow_node_configs(workflow, registry)
                    self._json({"valid": True, "order": topological_node_ids(workflow)})
                elif parsed.path == "/api/workflows":
                    workflow = self._validated_saved_workflow(payload)
                    record = workflow_store.create(
                        name=str(payload.get("name") or ""),
                        description=str(payload.get("description") or ""),
                        workflow=workflow,
                    )
                    self._json(record, HTTPStatus.CREATED)
                elif parsed.path == "/api/runs":
                    workflow = payload.get("workflow") or {}
                    validate_workflow(workflow, registry.keys())
                    validate_workflow_node_configs(workflow, registry)
                    run_id = run_store.create_run(
                        workflow,
                        build_services(payload.get("apiKeys")),
                        initial_state=payload.get("initialState"),
                    )
                    self._json({"runId": run_id, "status": "queued"}, HTTPStatus.ACCEPTED)
                elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/resume"):
                    run_id = parsed.path.split("/")[3]
                    self._json(run_store.resume_run(run_id, payload))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "接口不存在")
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if not parsed.path.startswith("/api/workflows/"):
                    self._error(HTTPStatus.NOT_FOUND, "接口不存在")
                    return
                payload = self._read_json()
                workflow = self._validated_saved_workflow(payload)
                record = workflow_store.update(
                    self._workflow_id(parsed.path),
                    name=str(payload.get("name") or ""),
                    description=str(payload.get("description") or ""),
                    workflow=workflow,
                )
                self._json(record)
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if not parsed.path.startswith("/api/workflows/"):
                    self._error(HTTPStatus.NOT_FOUND, "接口不存在")
                    return
                workflow_id = self._workflow_id(parsed.path)
                workflow_store.delete(workflow_id)
                self._json({"deleted": True, "id": workflow_id})
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))

        def _get_run_route(self, parsed) -> None:
            parts = parsed.path.strip("/").split("/")
            run_id = parts[2] if len(parts) >= 3 else ""
            if len(parts) == 4 and parts[3] == "events":
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
                self._json(run_store.get_events(run_id, since))
            elif len(parts) == 3:
                self._json(run_store.get_run(run_id))
            else:
                self._error(HTTPStatus.NOT_FOUND, "接口不存在")

        def _validated_saved_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
            workflow = payload.get("workflow") or {}
            validate_workflow(workflow, registry.keys())
            validate_workflow_node_configs(workflow, registry)
            return sanitize_workflow(workflow, registry)

        @staticmethod
        def _workflow_id(path: str) -> str:
            workflow_id = path.removeprefix("/api/workflows/").strip("/")
            if not workflow_id or "/" in workflow_id:
                raise KeyError("工作流不存在")
            return workflow_id

        def _static(self, request_path: str) -> None:
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            path = (web_root / relative).resolve()
            if web_root not in path.parents and path != web_root:
                self._error(HTTPStatus.FORBIDDEN, "禁止访问该路径")
                return
            if not path.is_file():
                self._error(HTTPStatus.NOT_FOUND, "页面不存在")
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 300 * 1024 * 1024:
                raise ValueError("请求体超过 300MB")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: HTTPStatus, message: str) -> None:
            self._json({"error": message}, status)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), WorkflowHandler)


__all__ = ["build_services", "create_server", "save_uploads"]
