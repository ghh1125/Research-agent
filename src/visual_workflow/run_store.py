from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.visual_workflow.executor import ExecutionResult, WorkflowExecutor
from src.visual_workflow.registry import WorkflowServices


@dataclass
class _RunRecord:
    run_id: str
    workflow: dict[str, Any]
    status: str = "queued"
    checkpoint: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    result: ExecutionResult | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)


class RunStore:
    def __init__(self, executor: WorkflowExecutor) -> None:
        self.executor = executor
        self._runs: dict[str, _RunRecord] = {}
        self._lock = threading.Lock()

    def create_run(
        self,
        workflow: dict[str, Any],
        services: WorkflowServices,
        *,
        initial_state: dict[str, Any] | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        record = _RunRecord(run_id=run_id, workflow=workflow)
        with self._lock:
            self._runs[run_id] = record
        thread = threading.Thread(
            target=self._worker,
            args=(record, services, initial_state),
            name=f"workflow-{run_id[:8]}",
            daemon=True,
        )
        thread.start()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = self._get_record(run_id)
        with record.condition:
            return self._public(record)

    def get_events(self, run_id: str, since: int = 0) -> dict[str, Any]:
        record = self._get_record(run_id)
        with record.condition:
            start = max(0, int(since))
            return {"events": record.events[start:], "next": len(record.events)}

    def resume_run(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        record = self._get_record(run_id)
        with record.condition:
            if record.status != "waiting":
                raise ValueError("当前运行不在等待人工操作状态")
            record.decision = dict(decision)
            record.status = "running"
            record.events.append({"type": "run", "status": "running", "resumed": True})
            record.condition.notify_all()
            return self._public(record)

    def _worker(
        self,
        record: _RunRecord,
        services: WorkflowServices,
        initial_state: dict[str, Any] | None,
    ) -> None:
        with record.condition:
            record.status = "running"
            record.events.append({"type": "run", "status": "running"})
        try:
            result = self.executor.execute(
                record.workflow,
                services,
                initial_state=initial_state,
                checkpoint_callback=lambda request: self._wait_for_decision(record, request),
                event_callback=lambda event: self._record_event(record, event),
            )
            with record.condition:
                record.result = result
                record.status = result.status
                record.events.append({"type": "run", "status": record.status})
                record.condition.notify_all()
        except Exception as exc:
            with record.condition:
                record.status = "failed"
                record.error = str(exc)
                record.events.append({"type": "run", "status": "failed", "error": str(exc)})
                record.condition.notify_all()

    def _wait_for_decision(self, record: _RunRecord, request: dict[str, Any]) -> dict[str, Any]:
        with record.condition:
            record.checkpoint = request
            record.decision = None
            record.status = "waiting"
            record.events.append({"type": "checkpoint", **request})
            record.condition.notify_all()
            while record.decision is None:
                record.condition.wait()
            decision = record.decision
            record.decision = None
            record.checkpoint = None
            return decision

    @staticmethod
    def _record_event(record: _RunRecord, event: dict[str, Any]) -> None:
        with record.condition:
            record.events.append(event)
            if event.get("type") == "node":
                record.nodes[event["nodeId"]] = event
            record.condition.notify_all()

    def _get_record(self, run_id: str) -> _RunRecord:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise KeyError(f"运行不存在: {run_id}") from exc

    @staticmethod
    def _public(record: _RunRecord) -> dict[str, Any]:
        return {
            "runId": record.run_id,
            "status": record.status,
            "checkpoint": record.checkpoint,
            "nodes": list(record.nodes.values()),
            "result": record.result.to_dict() if record.result is not None else None,
            "error": record.error,
        }


__all__ = ["RunStore"]

