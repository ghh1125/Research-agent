from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Question(BaseModel):
    """A decomposed sub-question for analysis."""

    id: str
    topic_id: str
    search_query: str | None = None
    content: str
    priority: int
    framework_type: Literal[
        "financial",
        "credit",
        "valuation",
        "business_model",
        "industry",
        "moat",
        "risk",
        "governance",
        "compliance",
        "adversarial",
        "catalyst",
        "gap",
        "general",
    ] = "general"
    covered: bool = False
    coverage_level: Literal["uncovered", "partial", "covered"] = "uncovered"
