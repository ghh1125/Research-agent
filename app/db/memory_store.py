from __future__ import annotations

from dataclasses import dataclass, field

from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.question import Question
from app.models.report import ResearchReport
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable


@dataclass
class MemoryStore:
    """Simple in-memory store for demo persistence."""

    topics: dict[str, Topic] = field(default_factory=dict)
    questions: dict[str, Question] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    variables: dict[str, ResearchVariable] = field(default_factory=dict)
    roles: dict[str, ResearchRoleOutput] = field(default_factory=dict)
    judgments: dict[str, Judgment] = field(default_factory=dict)
    reports: dict[str, ResearchReport] = field(default_factory=dict)
