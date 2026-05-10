from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

QuestionType = Literal[
    "single_stock_deep_dive",
    "industry_comparison",
    "event_impact",
    "portfolio_risk_review",
    "trading_decision_assist",
]
RiskPreference = Literal["conservative", "neutral", "aggressive"]
ResearchDepth = Literal["quick", "standard", "deep"]
PortfolioAction = Literal["值得进一步研究", "观察", "回避", "减仓", "可小仓位跟踪"]


class ResearchTask(BaseModel):
    id: str
    raw_query: str
    symbols: list[str] = Field(default_factory=list)
    entity: str | None = None
    market: str = "other"
    time_range: str = Field(default_factory=lambda: date.today().isoformat())
    horizon: str = "6-12个月"
    question_type: QuestionType
    output_format: str = "institutional_research_report"
    risk_preference: RiskPreference = "neutral"
    research_depth: ResearchDepth = "standard"
    model_profile: str = "default"
    quick_model: str | None = None
    deep_model: str | None = None
    output_language: str = "zh-CN"


class ResearchDimension(BaseModel):
    name: str
    objective: str
    data_sources: list[str] = Field(default_factory=list)
    hypotheses_to_test: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    task_id: str
    objective: str
    boundary: str
    dimensions: list[ResearchDimension]
    selected_agents: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    assumptions_to_verify: list[str] = Field(default_factory=list)


class DataArtifact(BaseModel):
    id: str
    category: str
    title: str
    source_type: str
    provider: str
    url: str | None = None
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    id: str
    artifact_id: str
    category: str
    claim: str
    metric_name: str | None = None
    metric_value: float | str | None = None
    unit: str | None = None
    period: str | None = None
    source_title: str
    source_url: str | None = None
    quality: Literal["high", "medium", "low"] = "medium"


class EvidenceBundle(BaseModel):
    artifacts: list[DataArtifact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    tool_counts: dict[str, int] = Field(default_factory=dict)
    tool_errors: dict[str, str] = Field(default_factory=dict)


class AnalystReport(BaseModel):
    role_id: str
    role_name: str
    conclusion: str
    key_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    open_questions: list[str] = Field(default_factory=list)
    requested_data_sources: list[str] = Field(default_factory=list)
    followup_queries: list[str] = Field(default_factory=list)


class DebateCase(BaseModel):
    side: Literal["bull", "bear"]
    thesis: str
    arguments: list[str] = Field(default_factory=list)
    key_disagreements: list[str] = Field(default_factory=list)
    falsification_tests: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DebateTurn(BaseModel):
    side: Literal["bull", "bear"]
    round_index: int
    thesis: str
    arguments: list[str] = Field(default_factory=list)
    key_disagreements: list[str] = Field(default_factory=list)
    falsification_tests: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class InvestmentDebate(BaseModel):
    bull_case: DebateCase
    bear_case: DebateCase
    history: list[DebateTurn] = Field(default_factory=list)


class ManagerDecision(BaseModel):
    rating: str
    core_logic: list[str] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    fragile_assumption: str
    confidence: Literal["low", "medium", "high"]
    variant_perception: str
    tracking_metrics: list[str] = Field(default_factory=list)
    verification_path: list[str] = Field(default_factory=list)


class ScenarioAnalysis(BaseModel):
    base_case: str
    bull_case: str
    bear_case: str
    target_price_range: str
    margin_of_safety: str
    key_drivers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    valuation_methodologies: list[str] = Field(default_factory=list)
    scenario_table: list[dict[str, Any]] = Field(default_factory=list)
    computed_target_prices: dict[str, float] = Field(default_factory=dict)


class RiskReview(BaseModel):
    aggressive_view: str
    neutral_view: str
    conservative_view: str
    risk_flags: list[str] = Field(default_factory=list)
    portfolio_context: str
    debate_history: list["RiskDebateTurn"] = Field(default_factory=list)
    portfolio_metrics: dict[str, Any] = Field(default_factory=dict)


class RiskDebateTurn(BaseModel):
    speaker: Literal["aggressive", "conservative", "neutral"]
    round_index: int
    view: str
    risk_flags: list[str] = Field(default_factory=list)


class PortfolioDecision(BaseModel):
    action: PortfolioAction
    position_hint: str
    rationale: str
    risk_level: Literal["low", "medium", "high"]
    revisit_trigger: str


class ResearchReport(BaseModel):
    markdown: str
    sections: dict[str, str] = Field(default_factory=dict)
    data_sources: list[str] = Field(default_factory=list)


class ResearchMemoryEntry(BaseModel):
    task_id: str
    entity: str | None = None
    symbols: list[str] = Field(default_factory=list)
    conclusion: str
    rating: str
    price_context: str | None = None
    key_assumptions: list[str] = Field(default_factory=list)
    revisit_triggers: list[str] = Field(default_factory=list)
    status: Literal["pending", "resolved"] = "pending"
    resolved_at: str | None = None
    current_price: float | None = None
    benchmark_return: float | None = None
    raw_return: float | None = None
    alpha_return: float | None = None
    reflection: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class TriggeredAlert(BaseModel):
    label: str
    reason: str


class StageTrace(BaseModel):
    name: str
    summary: str


class ResearchResult(BaseModel):
    task: ResearchTask
    plan: ResearchPlan
    evidence_bundle: EvidenceBundle
    analyst_reports: list[AnalystReport]
    bull_case: DebateCase
    bear_case: DebateCase
    investment_debate_history: list[DebateTurn] = Field(default_factory=list)
    manager_decision: ManagerDecision
    scenario_analysis: ScenarioAnalysis
    risk_review: RiskReview
    portfolio_decision: PortfolioDecision
    report: ResearchReport
    memory_entry: ResearchMemoryEntry
    tracking_alerts: list[TriggeredAlert] = Field(default_factory=list)
    stage_trace: list[StageTrace] = Field(default_factory=list)


class ResearchGraphConfig(BaseModel):
    enable_llm: bool = True
    selected_agents: list[str] | None = None
    model_profile: str = "default"
    quick_model: str | None = None
    deep_model: str | None = None
    output_language: str = "zh-CN"
    results_dir: Path = Path("data/research_logs")
    memory_path: Path = Path("data/research_memory/memory.jsonl")
    knowledge_dir: Path = Path("data/knowledge")
    checkpoint_enabled: bool = False
    checkpoint_dir: Path = Path("data/checkpoints")
    clear_checkpoint_on_success: bool = True
    resume_from_checkpoint: bool = True
    max_debate_rounds: int = 2
    max_risk_discuss_rounds: int = 1
    max_agent_tool_rounds: int = 1
    max_followup_queries_per_round: int = 6
    max_followup_categories_per_round: int = 3
    resolve_memory_on_start: bool = True
    search_max_results: int = 5
    fetch_source_content: bool = False
    source_fetch_timeout_seconds: float = 5.0
    evidence_extraction_batch_size: int = 4
    evidence_context_chars_per_artifact: int = 1000
    allow_heuristic_fallback: bool = False
    require_search_results: bool = True
