from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FundingRound = Literal["种子轮", "天使轮", "A轮", "B轮", "C轮", "Pre-IPO"]
Confidence = Literal["low", "medium", "high"]
RiskLevel = Literal["低", "中", "高"]
CapabilityRating = Literal["强", "中", "弱"]
BusinessScore = Literal["优", "良", "中", "差"]


class Source(BaseModel):
    title: str
    url: str | None = None
    provider: str | None = None
    note: str | None = None


class NodeMeta(BaseModel):
    """Standard envelope every node attaches to its output: sources/assumptions/confidence/missing_info/risk_flags."""

    sources: list[Source] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    missing_info: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class NodeMetaJudgment(BaseModel):
    """Subset of NodeMeta the LLM is asked to judge; sources are attached separately from real search results."""

    assumptions: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    missing_info: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

    def to_meta(self, sources: list[Source]) -> NodeMeta:
        return NodeMeta(sources=sources, assumptions=self.assumptions, confidence=self.confidence, missing_info=self.missing_info, risk_flags=self.risk_flags)


# ---------------------------------------------------------------------------
# Node 0: 开始 / intake
# ---------------------------------------------------------------------------


class FileManifestEntry(BaseModel):
    path: str
    kind: str
    category: str
    chars_extracted: int = 0
    error: str | None = None


class ProjectInput(BaseModel):
    company_name: str
    website: str | None = None
    funding_round: FundingRound | None = None
    funding_amount: str | None = None
    industry: str | None = None
    project_description: str = ""
    bp_parsed_content: str = ""
    file_manifest: list[FileManifestEntry] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    data_quality_check: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Node 1: 项目基本概况
# ---------------------------------------------------------------------------


class FounderProfile(BaseModel):
    name: str
    role: str
    background: str


class ProjectOverview(BaseModel):
    company_registration_info: str
    development_milestones: str
    core_business: str
    product_service_system: str
    use_cases_and_value: str
    org_structure_and_operations: str
    founder_team: list[FounderProfile] = Field(default_factory=list)
    founder_team_summary: str = ""
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Node 2: 行业深度分析
# ---------------------------------------------------------------------------


class IndustryAnalysis(BaseModel):
    industry_definition: str
    development_trends: str
    market_size_and_drivers: str
    industry_chain_structure: str
    competitive_landscape: str
    policy_environment: str
    opportunities_and_barriers: str
    opportunity_mapping_to_target: str
    key_assumptions: list[str] = Field(default_factory=list)
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Node 3.1 / 3.2: 竞品发现 + 竞品矩阵分析
# ---------------------------------------------------------------------------


class CompetitorCandidate(BaseModel):
    id: str
    name: str
    website: str | None = None
    region: str | None = None
    product_or_service: str
    relationship: str
    reason: str
    source: Source | None = None


class CompetitorDiscovery(BaseModel):
    candidates: list[CompetitorCandidate] = Field(default_factory=list)
    selected_ids: list[str] = Field(default_factory=list)
    meta: NodeMeta = Field(default_factory=NodeMeta)

    def selected(self) -> list[CompetitorCandidate]:
        ids = set(self.selected_ids) or {c.id for c in self.candidates}
        return [c for c in self.candidates if c.id in ids]


class CompetitorProfile(BaseModel):
    name: str
    capability_summary: str
    business_model: str
    customer_and_scene: str
    tech_barrier: str
    funding_and_progress: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class CompetitorAnalysis(BaseModel):
    overview: str
    competitor_profiles: list[CompetitorProfile] = Field(default_factory=list)
    capability_matrix: list[dict[str, Any]] = Field(default_factory=list)
    swot_strengths: list[str] = Field(default_factory=list)
    swot_weaknesses: list[str] = Field(default_factory=list)
    swot_opportunities: list[str] = Field(default_factory=list)
    swot_threats: list[str] = Field(default_factory=list)
    positioning_judgment: str = ""
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Node 4: 深度尽调 (5 sub-reports)
# ---------------------------------------------------------------------------


class TeamDueDiligence(BaseModel):
    founder_profiles: str
    team_capability_matrix: str
    equity_stability_analysis: str
    key_person_risk: str
    capability_rating: CapabilityRating
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


class RiskNote(BaseModel):
    description: str
    severity: RiskLevel


class BusinessDueDiligence(BaseModel):
    business_model_analysis: str
    market_analysis: str
    growth_model: str
    competitive_landscape_analysis: str
    risk_notes: list[RiskNote] = Field(default_factory=list)
    business_score: BusinessScore
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


class FinancialRatios(BaseModel):
    revenue: dict[str, float] = Field(default_factory=dict)
    cost: dict[str, float] = Field(default_factory=dict)
    gross_margin_pct: float | None = None
    net_margin_pct: float | None = None
    operating_cash_flow: float | None = None
    revenue_yoy_growth_pct: float | None = None
    computed_from: str = ""


class FinancialDueDiligence(BaseModel):
    revenue_structure: str
    cost_structure: str
    unit_economics: str
    cash_flow_health: str
    financial_health_summary: str
    ratios: FinancialRatios = Field(default_factory=FinancialRatios)
    risk_notes: list[RiskNote] = Field(default_factory=list)
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


class TechIPDueDiligence(BaseModel):
    architecture_review: str
    rd_team_assessment: str
    core_tech_barrier: str
    risk_notes: list[RiskNote] = Field(default_factory=list)
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


class LegalDueDiligence(BaseModel):
    entity_compliance: str
    equity_structure_analysis: str
    contracts_and_agreements: str
    risk_notes: list[str] = Field(default_factory=list)
    legal_risk_level: RiskLevel
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


class RiskRegisterItem(BaseModel):
    category: Literal["团队", "业务", "财务", "技术与知识产权", "法律"]
    description: str
    severity: RiskLevel


class DueDiligenceBundle(BaseModel):
    team: TeamDueDiligence
    business: BusinessDueDiligence
    financial: FinancialDueDiligence
    tech_ip: TechIPDueDiligence
    legal: LegalDueDiligence
    risk_register: list[RiskRegisterItem] = Field(default_factory=list)
    evidence_index: list[Source] = Field(default_factory=list)
    markdown: str = ""


# ---------------------------------------------------------------------------
# Node 5: 估值分析
# ---------------------------------------------------------------------------


class ScenarioValuation(BaseModel):
    scenario: Literal["保守", "基准", "乐观"]
    valuation: str
    key_assumption: str


class ValuationAnalysis(BaseModel):
    implied_valuation_from_round: str
    comparable_company_method: str
    comparable_transaction_method: str
    revenue_profit_multiple_method: str
    risk_adjusted_range: str
    scenarios: list[ScenarioValuation] = Field(default_factory=list)
    investor_ownership_estimate: str
    reasonableness_judgment: str
    key_assumptions: list[str] = Field(default_factory=list)
    sensitivity_notes: str = ""
    methodology_weighting_note: str = ""
    markdown: str = ""
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Node 6: 综合研判与报告输出
# ---------------------------------------------------------------------------


class FinalInvestmentReport(BaseModel):
    investment_summary: str
    project_overview_section: str
    industry_section: str
    business_model_section: str
    team_and_governance_section: str
    financial_section: str
    competitor_section: str
    risk_section: str
    valuation_section: str
    core_logic_and_recommendation: str
    risk_response_and_post_investment: str
    exit_path_and_return: str
    markdown: str = ""
    sources: list[Source] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risk_register: list[RiskRegisterItem] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    meta: NodeMeta = Field(default_factory=NodeMeta)


# ---------------------------------------------------------------------------
# Top-level pipeline state
# ---------------------------------------------------------------------------


class PipelineState(BaseModel):
    project_input: ProjectInput | None = None
    project_overview: ProjectOverview | None = None
    industry_analysis: IndustryAnalysis | None = None
    competitor_discovery: CompetitorDiscovery | None = None
    competitor_analysis: CompetitorAnalysis | None = None
    due_diligence: DueDiligenceBundle | None = None
    valuation_analysis: ValuationAnalysis | None = None
    final_report: FinalInvestmentReport | None = None
