from __future__ import annotations

from app.agent.orchestrator import ResearchAgent
from app.db.repository import InMemoryResearchRepository

_repository = InMemoryResearchRepository()
_agent = ResearchAgent(repository=_repository)


def get_repository() -> InMemoryResearchRepository:
    """Return the singleton repository used by the demo app."""

    return _repository


def get_agent() -> ResearchAgent:
    """Return the singleton research agent used by the demo app."""

    return _agent
