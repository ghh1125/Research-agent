from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchVariable(BaseModel):
    """Normalized investment variable derived from one or more evidence items."""

    name: str
    category: Literal["financial", "operation", "industry", "governance", "valuation", "risk"]
    value_summary: str
    direction: Literal["improving", "deteriorating", "stable", "mixed", "unknown"]
    evidence_ids: list[str]
    direction_notes: list[str] = Field(default_factory=list)
