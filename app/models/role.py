from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResearchRoleOutput(BaseModel):
    """Explicit role view for a multi-perspective research workflow."""

    role_id: Literal[
        "fact_researcher",
        "risk_officer",
        "counter_analyst",
        "synthesis_analyst",
        "investment_manager",
    ]
    role_name: str
    role_description: str
    cognitive_bias: Literal["neutral", "risk_first", "contrarian", "synthesis", "action"]
    objective: str
    role_prompt: str
    operating_rules: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    variable_names: list[str] = Field(default_factory=list)
    framework_types: list[str] = Field(default_factory=list)
    pressure_test_ids: list[str] = Field(default_factory=list)
    output_summary: str
