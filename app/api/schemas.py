from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.evidence import Evidence
from app.models.financial import FinancialSnapshot
from app.models.judgment import AutoResearchTrace, Judgment
from app.models.question import Question
from app.models.report import ResearchReport
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.summary import ExecutiveSummary
from app.models.topic import Topic
from app.models.variable import ResearchVariable


class ResearchRequest(BaseModel):
    """Incoming research request payload."""

    query: str = Field(min_length=1)


class ResearchResponse(BaseModel):
    """Outgoing full research process payload."""

    topic: Topic
    questions: list[Question]
    sources: list[Source]
    evidence: list[Evidence]
    variables: list[ResearchVariable]
    roles: list[ResearchRoleOutput]
    judgment: Judgment
    auto_research_trace: list[AutoResearchTrace]
    executive_summary: ExecutiveSummary
    financial_snapshot: FinancialSnapshot
    early_stop_reason: str | None = None
    report: ResearchReport
