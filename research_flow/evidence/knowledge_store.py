from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from research_flow.schema import DataArtifact, Evidence, ResearchTask


class KnowledgeRecord(BaseModel):
    id: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocalKnowledgeStore:
    """Local knowledge directory for artifacts and extracted evidence.

    It is intentionally plain JSONL here: the interface is the important product
    boundary, and a LanceDB/embedding backend can replace the storage later.
    """

    def __init__(self, root: str | Path, *, search_mode: str = "keyword") -> None:
        self.root = Path(root)
        self.path = self.root / "records.jsonl"
        self.search_mode = search_mode

    def add(self, record: KnowledgeRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")

    def add_artifact(self, task: ResearchTask, artifact: DataArtifact) -> None:
        self.add(
            KnowledgeRecord(
                id=f"artifact:{artifact.id}",
                kind="artifact",
                title=artifact.title,
                content=artifact.content,
                metadata={
                    "task_id": task.id,
                    "category": artifact.category,
                    "provider": artifact.provider,
                    "url": artifact.url,
                    **artifact.metadata,
                },
            )
        )

    def add_evidence(self, task: ResearchTask, evidence: Evidence) -> None:
        self.add(
            KnowledgeRecord(
                id=f"evidence:{evidence.id}",
                kind="evidence",
                title=evidence.metric_name or evidence.category,
                content=evidence.claim,
                metadata={
                    "task_id": task.id,
                    "artifact_id": evidence.artifact_id,
                    "category": evidence.category,
                    "quality": evidence.quality,
                    "source_url": evidence.source_url,
                },
            )
        )

    def ingest_file(self, path: str | Path, *, title: str | None = None, metadata: dict[str, Any] | None = None) -> KnowledgeRecord:
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(source)
        content = self._read_source(source)
        record = KnowledgeRecord(
            id=f"upload:{source.name}",
            kind="user_upload",
            title=title or source.name,
            content=content,
            metadata={"path": str(source), **(metadata or {})},
        )
        self.add(record)
        return record

    def load(self) -> list[KnowledgeRecord]:
        if not self.path.exists():
            return []
        records: list[KnowledgeRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(KnowledgeRecord.model_validate_json(line))
        return records

    def search(self, query: str, limit: int = 10) -> list[KnowledgeRecord]:
        tokens = _tokens(query)
        scored: list[tuple[int, KnowledgeRecord]] = []
        for record in self.load():
            haystack = f"{record.title}\n{record.content}".lower()
            score = sum(1 for token in tokens if token in haystack)
            if query.lower() in haystack:
                score += 3
            if self.search_mode in {"vector", "hybrid"}:
                score += int(10 * _jaccard(tokens, _tokens(haystack)))
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def _read_source(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8", errors="ignore")


def _tokens(text: str) -> list[str]:
    raw = text.lower()
    words = [token for token in raw.split() if token]
    if words:
        return words + [raw[idx : idx + 3] for idx in range(max(len(raw) - 2, 0))]
    return [raw[idx : idx + 2] for idx in range(max(len(raw) - 1, 0))]


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)
