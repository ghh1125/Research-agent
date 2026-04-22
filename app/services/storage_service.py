from __future__ import annotations

from app.db.repository import InMemoryResearchRepository
from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.question import Question
from app.models.report import ResearchReport
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable


def save_topic(repository: InMemoryResearchRepository, topic: Topic) -> None:
    """Persist a topic."""

    repository.save_topic(topic)


def save_questions(repository: InMemoryResearchRepository, questions: list[Question]) -> None:
    """Persist questions."""

    repository.save_questions(questions)


def save_sources(repository: InMemoryResearchRepository, sources: list[Source]) -> None:
    """Persist sources."""

    repository.save_sources(sources)


def save_evidence(repository: InMemoryResearchRepository, evidence_list: list[Evidence]) -> None:
    """Persist evidence."""

    repository.save_evidence(evidence_list)


def save_variables(repository: InMemoryResearchRepository, variables: list[ResearchVariable]) -> None:
    """Persist normalized research variables."""

    repository.save_variables(variables)


def save_roles(repository: InMemoryResearchRepository, roles: list[ResearchRoleOutput]) -> None:
    """Persist explicit research role outputs."""

    repository.save_roles(roles)


def save_judgment(repository: InMemoryResearchRepository, judgment: Judgment) -> None:
    """Persist judgment."""

    repository.save_judgment(judgment)


def save_report(repository: InMemoryResearchRepository, report: ResearchReport) -> None:
    """Persist report."""

    repository.save_report(report)


def get_judgment_by_topic_id(
    repository: InMemoryResearchRepository,
    topic_id: str,
) -> Judgment | None:
    """Load a judgment by topic id."""

    return repository.get_judgment_by_topic_id(topic_id)
