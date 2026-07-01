from __future__ import annotations

from collections.abc import Collection
from heapq import heappop, heappush
from typing import Any


class WorkflowValidationError(ValueError):
    pass


def validate_workflow(workflow: dict[str, Any], known_types: Collection[str]) -> None:
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    node_ids: set[str] = set()

    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        node_type = str(node.get("type", "")).strip()
        if not node_id:
            raise WorkflowValidationError("节点 ID 不能为空")
        if node_id in node_ids:
            raise WorkflowValidationError(f"节点 ID 重复: {node_id}")
        if node_type not in known_types:
            raise WorkflowValidationError(f"未知节点类型: {node_type}")
        node_ids.add(node_id)

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids or target not in node_ids:
            raise WorkflowValidationError(f"连线引用了不存在的节点: {source} -> {target}")

    topological_node_ids(workflow)


def topological_node_ids(workflow: dict[str, Any]) -> list[str]:
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    order_index = {node["id"]: index for index, node in enumerate(nodes)}
    indegree = {node_id: 0 for node_id in order_index}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in order_index}

    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source not in indegree or target not in indegree:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    ready: list[tuple[int, str]] = []
    for node_id, degree in indegree.items():
        if degree == 0:
            heappush(ready, (order_index[node_id], node_id))

    result: list[str] = []
    while ready:
        _, node_id = heappop(ready)
        result.append(node_id)
        for target in sorted(outgoing[node_id], key=order_index.__getitem__):
            indegree[target] -= 1
            if indegree[target] == 0:
                heappush(ready, (order_index[target], target))

    if len(result) != len(nodes):
        raise WorkflowValidationError("工作流存在环，无法执行")
    return result


__all__ = ["WorkflowValidationError", "topological_node_ids", "validate_workflow"]

