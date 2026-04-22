from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceCluster(BaseModel):
    """A reasoning cluster that captures supporting and counter evidence."""

    theme: str
    support_evidence_ids: list[str]
    counter_evidence_ids: list[str]


class RiskItem(BaseModel):
    """Evidence-backed risk statement."""

    text: str
    evidence_ids: list[str]


class BearThesis(BaseModel):
    """Actionable downside thesis for investment research."""

    title: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    transmission_path: str | None = None
    falsify_condition: str | None = None


class Catalyst(BaseModel):
    """Potential 6-12 month trigger for research timing."""

    title: str
    catalyst_type: Literal[
        "earnings",
        "product",
        "policy",
        "rate_cycle",
        "industry_inflection",
        "m_and_a",
        "buyback",
        "refinancing",
        "rating",
        "other",
    ]
    timeframe: str
    evidence_ids: list[str] = Field(default_factory=list)
    why_it_matters: str


class PressureTest(BaseModel):
    """Adversarial attack on a conclusion, not a role-play summary."""

    test_id: str
    attack_type: Literal[
        "fragile_evidence",
        "ignored_counter_evidence",
        "evidence_gap",
        "weak_source",
        "logic_gap",
    ]
    target: str
    fragile_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    weakness: str
    counter_conclusion: str
    severity: Literal["low", "medium", "high"]


class EvidenceGap(BaseModel):
    """Expected but currently missing evidence."""

    question_id: str | None
    text: str
    importance: Literal["low", "medium", "high"]


class ConfidenceBasis(BaseModel):
    """Structured basis behind the confidence level."""

    source_count: int
    source_diversity: Literal["low", "medium", "high"]
    conflict_level: Literal["none", "partial", "strong"]
    evidence_gap_level: Literal["low", "medium", "high"]
    effective_evidence_count: int = 0
    has_official_source: bool = False
    official_evidence_count: int = 0
    weak_source_only: bool = False


class ResearchAction(BaseModel):
    """Structured next-step action that can drive another research pass."""

    id: str
    priority: Literal["high", "medium", "low"]
    question: str | None = None
    objective: str
    reason: str
    required_data: list[str]
    search_query: str | None = None
    query_templates: list[str]
    target_sources: list[str] = Field(default_factory=list)
    source_targets: list[str]
    status: Literal["pending", "running", "done", "skipped"] = "pending"
    question_id: str | None = None


class AutoResearchTrace(BaseModel):
    """Trace of one bounded automatic补证 round."""

    round_index: int
    triggered: bool
    selected_action_ids: list[str] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)
    new_source_ids: list[str] = Field(default_factory=list)
    new_evidence_ids: list[str] = Field(default_factory=list)
    covered_gap_question_ids: list[str] = Field(default_factory=list)
    effectiveness_status: Literal["not_triggered", "effective", "ineffective", "no_new_data"] = "not_triggered"
    stop_reason: str


class ResearchScope(BaseModel):
    """Suggested amount of work before spending more analyst time."""

    estimated_hours: str
    urgency: Literal["low", "medium", "high"]
    depth_recommendation: Literal["quick_screen", "standard_research", "deep_dive"]
    reason: str


class TrendSignal(BaseModel):
    """Evidence-backed direction signal for an investable issue."""

    metric: str
    direction: Literal["improving", "deteriorating", "stable", "mixed", "unknown"]
    evidence_ids: list[str]


class PeerContext(BaseModel):
    """Whether the judgment has enough peer or benchmark context."""

    required: bool
    status: Literal["covered", "needs_research", "not_applicable"]
    peer_entities: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    comparison_rows: list[dict] = Field(default_factory=list)
    note: str


class InvestmentDecision(BaseModel):
    """Decision capture for one-person investment workflow."""

    decision_target: Literal[
        "research_priority",
        "deep_research_entry",
        "watchlist_entry",
        "research_action",
        "theme_tracking",
        "credit_review",
    ]
    decision: Literal[
        "deep_dive_candidate",
        "watchlist",
        "deprioritize",
        "establish_tracking",
        "monitor_for_trigger",
        "enter_credit_review",
        "high_risk_watch",
        "thematic_watch",
    ]
    rationale: str
    evidence_ids: list[str]
    decision_basis: list[str] = Field(default_factory=list)
    trigger_to_revisit: str
    caveat: str
    research_recommendation_reason: str | None = None
    next_best_research_path: str | None = None
    positioning: str | None = None


class Judgment(BaseModel):
    """Final structured research judgment."""

    topic_id: str
    conclusion: str
    conclusion_evidence_ids: list[str]
    clusters: list[EvidenceCluster]
    risk: list[RiskItem]
    bear_theses: list[BearThesis] = Field(default_factory=list)
    pressure_tests: list[PressureTest] = Field(default_factory=list)
    unknown: list[str]
    evidence_gaps: list[EvidenceGap]
    confidence: Literal["low", "medium", "high"]
    research_confidence: Literal["low", "medium", "high"] = "low"
    signal_confidence: Literal["low", "medium", "high"] = "low"
    source_confidence: Literal["low", "medium", "high"] = "low"
    confidence_basis: ConfidenceBasis
    research_actions: list[ResearchAction]
    catalysts: list[Catalyst] = Field(default_factory=list)
    positioning: str | None = None
    research_scope: ResearchScope | None = None
    trend_signals: list[TrendSignal] = Field(default_factory=list)
    peer_context: PeerContext | None = None
    investment_decision: InvestmentDecision | None = None
    reviewer_status: Literal["pending_review", "approved", "rejected", "overridden"] = "pending_review"
    reviewer_comment: str | None = None
    approved_by: str | None = None
    overridden_fields: list[str] = Field(default_factory=list)
