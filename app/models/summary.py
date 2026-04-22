from __future__ import annotations

from pydantic import BaseModel


class ExecutiveSummary(BaseModel):
    """Single-screen summary for one-person research workflows."""

    one_line_conclusion: str
    top_risk: str
    next_action: str
    confidence: str
    research_time_minutes: int
    why_continue: str | None = None
    why_not_stronger: str | None = None
    top_bear_thesis: str | None = None
    key_evidence_gap: str | None = None
    next_research_focus: str | None = None
