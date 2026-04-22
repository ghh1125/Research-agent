from __future__ import annotations

from app.db.memory_store import MemoryStore
from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.question import Question
from app.models.report import ResearchReport
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable


class InMemoryResearchRepository:
    """Repository abstraction backed by an in-memory store."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def save_topic(self, topic: Topic) -> None:
        self.store.topics[topic.id] = topic

    def save_questions(self, questions: list[Question]) -> None:
        for question in questions:
            self.store.questions[question.id] = question

    def save_sources(self, sources: list[Source]) -> None:
        for source in sources:
            self.store.sources[source.id] = source

    def save_evidence(self, evidence_list: list[Evidence]) -> None:
        for evidence in evidence_list:
            self.store.evidence[evidence.id] = evidence

    def save_variables(self, variables: list[ResearchVariable]) -> None:
        for variable in variables:
            key = f"{variable.category}:{variable.name}"
            self.store.variables[key] = variable

    def save_roles(self, roles: list[ResearchRoleOutput]) -> None:
        for role in roles:
            self.store.roles[role.role_id] = role

    def save_judgment(self, judgment: Judgment) -> None:
        self.store.judgments[judgment.topic_id] = judgment

    def save_report(self, report: ResearchReport) -> None:
        self.store.reports[report.id] = report

    def get_judgment_by_topic_id(self, topic_id: str) -> Judgment | None:
        return self.store.judgments.get(topic_id)

    def get_report_by_id(self, report_id: str) -> ResearchReport | None:
        return self.store.reports.get(report_id)
