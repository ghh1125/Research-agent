from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """Structured evidence extracted from a source."""

    id: str
    topic_id: str
    question_id: str | None = None
    source_id: str
    flow_type: Literal["fact", "risk", "counter"] = "fact"
    content: str
    evidence_type: Literal["fact", "data", "claim", "risk_signal"]
    stance: Literal["support", "counter", "neutral"] = "neutral"
    grounded: bool = True
    is_noise: bool = False
    is_truncated: bool = False
    quality_score: float | None = None
    quality_notes: list[str] = Field(default_factory=list)
    source_tier: str | None = None
    source_score: float | None = None
    relevance_score: float | None = None
    clarity_score: float | None = None
    recency_score: float | None = None
    evidence_score: float | None = None
    timestamp: str | None = None
