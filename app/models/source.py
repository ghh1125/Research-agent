from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SourceTier(str, Enum):
    """Investment-research source quality tiers."""

    TIER1 = "official"
    TIER2 = "professional"
    TIER3 = "content"


class Source(BaseModel):
    """Retrieved information source."""

    id: str
    question_id: str
    flow_type: Literal["fact", "risk", "counter"] = "fact"
    search_query: str | None = None
    title: str
    url: str | None = None
    source_type: Literal["news", "report", "regulatory", "company", "website", "other"]
    provider: str
    source_origin_type: Literal[
        "official_disclosure",
        "company_ir",
        "regulatory",
        "professional_media",
        "research_media",
        "aggregator",
        "community",
        "self_media",
        "unknown",
    ] = "unknown"
    credibility_tier: Literal["tier1", "tier2", "tier3"] = "tier3"
    tier: SourceTier = SourceTier.TIER3
    source_score: float | None = None
    source_rank_reason: str | None = None
    contains_entity: bool = False
    is_recent: bool | None = None
    date_source: Literal["provider", "url_extracted", "content_extracted", "unknown"] = "unknown"
    is_pdf: bool = False
    is_official_pdf: bool = False
    is_official_target_source: bool = False
    target_reason: str | None = None
    rejected_reason: str | None = None
    page_score: float | None = None
    page_type: str | None = None
    pdf_parse_status: Literal["not_pdf", "not_attempted", "parsed", "failed"] = "not_pdf"
    parsed_tables: list[dict] = Field(default_factory=list)
    parsed_pages: list[dict] = Field(default_factory=list)
    structured_metrics: list[dict] = Field(default_factory=list)
    ocr_required: bool = False
    published_at: str | None = None
    content: str
    fetched_content: str | None = None
    enriched_content: str | None = None
