from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pydantic import BaseModel

from src.visual_workflow.graph import topological_node_ids, validate_workflow
from src.visual_workflow.registry import NodeDefinition, WorkflowServices, validate_workflow_node_configs

CheckpointCallback = Callable[[dict[str, Any]], dict[str, Any]]
EventCallback = Callable[[dict[str, Any]], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    return value


@dataclass
class NodeExecution:
    node_id: str
    node_type: str
    name: str
    description: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    missing_inputs: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "nodeType": self.node_type,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "missingInputs": self.missing_inputs,
            "outputKeys": self.output_keys,
            "outputs": self.outputs,
            "error": self.error,
        }


@dataclass
class ExecutionResult:
    state: dict[str, Any]
    nodes: list[NodeExecution]

    @property
    def status(self) -> str:
        return "failed" if any(node.status == "failed" for node in self.nodes) else "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "state": serialize_value(self.state),
            "nodes": [node.to_dict() for node in self.nodes],
        }


class WorkflowExecutor:
    def __init__(self, registry: Mapping[str, NodeDefinition]) -> None:
        self.registry = registry

    def execute(
        self,
        workflow: dict[str, Any],
        services: WorkflowServices,
        *,
        initial_state: dict[str, Any] | None = None,
        checkpoint_callback: CheckpointCallback | None = None,
        event_callback: EventCallback | None = None,
    ) -> ExecutionResult:
        validate_workflow(workflow, self.registry.keys())
        validate_workflow_node_configs(workflow, self.registry)
        state = dict(initial_state or {})
        nodes_by_id = {node["id"]: node for node in workflow.get("nodes", [])}
        executions: list[NodeExecution] = []

        for node_id in topological_node_ids(workflow):
            node = nodes_by_id[node_id]
            definition = self.registry[node["type"]]
            execution = NodeExecution(
                node_id=node_id,
                node_type=definition.type,
                name=(node.get("config") or {}).get("display_name") or definition.name,
                description=(node.get("config") or {}).get("description") or definition.description,
                status="running",
                started_at=_now(),
            )
            executions.append(execution)
            self._emit(event_callback, execution)

            missing = self._missing_inputs(definition, state)
            if missing:
                execution.status = "skipped"
                execution.missing_inputs = missing
                execution.finished_at = _now()
                self._emit(event_callback, execution)
                continue

            try:
                outputs = self._run_with_checkpoint(
                    node,
                    definition,
                    state,
                    services,
                    checkpoint_callback,
                )
                state.update(outputs)
                execution.status = "completed"
                execution.output_keys = list(outputs)
                execution.outputs = serialize_value(outputs)
            except Exception as exc:
                execution.status = "failed"
                execution.error = str(exc)
            execution.finished_at = _now()
            self._emit(event_callback, execution)

        return ExecutionResult(state=state, nodes=executions)

    def _run_with_checkpoint(
        self,
        node: dict[str, Any],
        definition: NodeDefinition,
        state: dict[str, Any],
        services: WorkflowServices,
        callback: CheckpointCallback | None,
    ) -> dict[str, Any]:
        config = node.get("config") or {}
        outputs = definition.runner(state, config, services, {})
        state.update(outputs)
        if callback is None or definition.checkpoint is None:
            return outputs

        if definition.checkpoint == "competitor_selection":
            decision = callback(self._checkpoint_request(node, definition, outputs))
            if decision.get("action") not in {"select", "approve"}:
                raise ValueError("竞品发现节点需要提交选择结果")
            selected_ids = list(decision.get("selected_ids") or [])
            discovery = outputs["competitor_discovery"]
            if isinstance(discovery, dict):
                discovery["selected_ids"] = selected_ids
            else:
                discovery.selected_ids = selected_ids
            return outputs

        while True:
            decision = callback(self._checkpoint_request(node, definition, outputs))
            action = decision.get("action", "approve")
            if action == "approve":
                return outputs
            feedback = str(decision.get("feedback") or "").strip()
            if not feedback:
                raise ValueError("重新生成或重新分析前必须填写具体审核意见")
            if definition.checkpoint == "report_review" and action == "regenerate":
                runtime = {"feedback": feedback}
            elif definition.checkpoint == "competitor_report_review" and action in {"resynthesize", "reanalyze"}:
                runtime = {"mode": action, "feedback": feedback}
            else:
                raise ValueError(f"不支持的审核操作: {action}")
            outputs = definition.runner(state, config, services, runtime)
            state.update(outputs)

    @staticmethod
    def _missing_inputs(definition: NodeDefinition, state: dict[str, Any]) -> list[str]:
        missing = [key for key in definition.required_inputs if state.get(key) is None]
        if definition.required_any and not any(all(state.get(key) is not None for key in group) for group in definition.required_any):
            alternatives = [" + ".join(group) for group in definition.required_any]
            missing.append(" 或 ".join(alternatives))
        return missing

    @staticmethod
    def _checkpoint_request(
        node: dict[str, Any], definition: NodeDefinition, outputs: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "nodeId": node["id"],
            "nodeType": definition.type,
            "name": (node.get("config") or {}).get("display_name") or definition.name,
            "description": (node.get("config") or {}).get("description") or definition.description,
            "checkpoint": definition.checkpoint,
            "outputs": serialize_value(outputs),
        }

    @staticmethod
    def _emit(callback: EventCallback | None, execution: NodeExecution) -> None:
        if callback is not None:
            callback({"type": "node", **execution.to_dict()})


__all__ = [
    "ExecutionResult",
    "NodeExecution",
    "WorkflowExecutor",
    "serialize_value",
]
