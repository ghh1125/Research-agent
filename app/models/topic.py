from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Topic(BaseModel):
    """Structured representation of a user research query."""

    id: str
    query: str
    entity: str | None = None
    topic: str
    goal: str
    type: Literal["company", "theme", "compliance", "general"]
    hypothesis: str | None = None
    research_object_type: Literal[
        "listed_company",
        "private_company",
        "industry_theme",
        "credit_issuer",
        "macro_theme",
        "event",
        "concept_theme",
        "fund_etf",
        "commodity",
        "unknown",
    ] = "unknown"
    listing_status: Literal["listed", "private", "unlisted", "not_applicable", "concept", "asset", "unknown"] = "unknown"
    market_type: Literal["A_share", "HK", "US", "bond", "private", "thematic", "macro", "commodity", "fund", "other"] = "other"
    listing_note: str | None = None
