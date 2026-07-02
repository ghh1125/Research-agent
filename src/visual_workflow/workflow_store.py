from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.visual_workflow.registry import NodeDefinition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_workflow(
    workflow: dict[str, Any],
    registry: Mapping[str, NodeDefinition],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for raw_node in workflow.get("nodes", []):
        node_type = str(raw_node.get("type") or "")
        definition = registry.get(node_type)
        file_keys = {field.key for field in definition.file_fields} if definition else set()
        config = copy.deepcopy(raw_node.get("config") or {})
        for key in file_keys:
            config.pop(key, None)
        nodes.append(
            {
                "id": str(raw_node.get("id") or ""),
                "type": node_type,
                "x": raw_node.get("x", 30),
                "y": raw_node.get("y", 30),
                "config": config,
            }
        )
    edges = [
        {"source": str(edge.get("source") or ""), "target": str(edge.get("target") or "")}
        for edge in workflow.get("edges", [])
    ]
    return {"nodes": nodes, "edges": edges}


class WorkflowStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    graph_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM workflows
                ORDER BY updated_at DESC, name ASC
                """
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, workflow_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, description, graph_json, created_at, updated_at
                FROM workflows
                WHERE id = ?
                """,
                (workflow_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"工作流不存在: {workflow_id}")
        return self._record(row)

    def create(
        self,
        *,
        name: str,
        description: str,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_name = self._name(name)
        workflow_id = uuid.uuid4().hex
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (id, name, description, graph_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    normalized_name,
                    description.strip(),
                    json.dumps(workflow, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(workflow_id)

    def update(
        self,
        workflow_id: str,
        *,
        name: str,
        description: str,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_name = self._name(name)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workflows
                SET name = ?, description = ?, graph_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_name,
                    description.strip(),
                    json.dumps(workflow, ensure_ascii=False),
                    _now(),
                    workflow_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"工作流不存在: {workflow_id}")
        return self.get(workflow_id)

    def delete(self, workflow_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        if cursor.rowcount == 0:
            raise KeyError(f"工作流不存在: {workflow_id}")

    @staticmethod
    def _name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("工作流名称不能为空")
        if len(normalized) > 120:
            raise ValueError("工作流名称不能超过 120 个字符")
        return normalized

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @classmethod
    def _record(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            **cls._summary(row),
            "workflow": json.loads(row["graph_json"]),
        }


__all__ = ["WorkflowStore", "sanitize_workflow"]
