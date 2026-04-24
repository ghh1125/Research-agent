from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.question import Question
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable


class ReportSection(BaseModel):
    """Single report section rendered from structured judgment."""

    title: str
    body: str
    evidence_ids: list[str]
    section_type: Literal["background", "framework", "source", "role", "variable", "finding", "risk", "pressure", "gap", "judgment", "investment", "action"]


class ResearchReport(BaseModel):
    """Final report object for end users and downstream integrations."""

    id: str
    topic: Topic
    questions: list[Question]
    sources: list[Source]
    evidence: list[Evidence]
    variables: list[ResearchVariable] = Field(default_factory=list)
    roles: list[ResearchRoleOutput] = Field(default_factory=list)
    judgment: Judgment
    report_sections: list[ReportSection]
    markdown: str
    report_internal: dict[str, object] = Field(default_factory=dict)
    report_display: dict[str, object] = Field(default_factory=dict)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
