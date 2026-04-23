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
    cross_entity_contamination: bool = False
    can_enter_main_chain: bool = True
    quality_score: float | None = None
    quality_notes: list[str] = Field(default_factory=list)
    source_tier: str | None = None
    source_score: float | None = None
    relevance_score: float | None = None
    clarity_score: float | None = None
    recency_score: float | None = None
    evidence_score: float | None = None
    metric_name: str | None = None
    metric_value: str | float | None = None
    unit: str | None = None
    period: str | None = None
    segment: str | None = None
    comparison_type: str | None = None
    source_page: int | None = None
    source_table_id: str | None = None
    extraction_confidence: float | None = None
    timestamp: str | None = None
