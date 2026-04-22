from __future__ import annotations

from typing import Any

from app.agent.pipeline import research_pipeline
from app.db.repository import InMemoryResearchRepository


class ResearchAgent:
    """Public agent entry point."""

    def __init__(self, repository: InMemoryResearchRepository | None = None) -> None:
        self.repository = repository or InMemoryResearchRepository()

    def run(self, query: str) -> dict[str, Any]:
        """Execute the end-to-end research pipeline."""

        return research_pipeline(query=query, repository=self.repository)
