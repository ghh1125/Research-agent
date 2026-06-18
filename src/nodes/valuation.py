from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import (
    CompetitorAnalysis,
    DueDiligenceBundle,
    IndustryAnalysis,
    NodeMetaJudgment,
    ProjectInput,
    ProjectOverview,
    ScenarioValuation,
    ValuationAnalysis,
)
from src.search import RealSearchClient, collect_evidence

_ROUND_WEIGHTING = {
    "种子轮": "团队、市场天花板、技术可行性权重最高；财务倍数法基本不适用，估值以可比早期案例和里程碑定价为主。",
    "天使轮": "团队、市场天花板、技术可行性权重最高；财务倍数法基本不适用，估值以可比早期案例和里程碑定价为主。",
    "A轮": "收入增长、客户验证、单位经济模型权重上升；可比公司法/可比交易法开始有意义。",
    "B轮": "收入增长、客户验证、单位经济模型权重上升；可比公司法/可比交易法开始有意义。",
    "C轮": "财务质量、利润路径、退出可比性权重最高；收入/利润倍数法和可比上市公司法是主要方法。",
    "Pre-IPO": "财务质量、利润路径、退出可比性权重最高；收入/利润倍数法和可比上市公司法是主要方法。",
}

_PROMPT = """\
你在做一级市场投资项目的"估值分析"。

公司：{company_name}
本轮融资轮次：{funding_round}
本轮融资金额：{funding_amount}
所属行业：{industry}

项目概况（主营业务/产品服务体系/落地场景，供你判断业务复杂度和可比性）：
主营业务：{core_business}
核心产品/服务体系：{product_service_system}
业务落地场景与核心价值：{use_cases_and_value}

本轮次估值方法权重建议：{weighting_note}

行业市场规模/竞争格局（参考）：
{industry_summary}

竞品矩阵定位判断（参考）：
{positioning_judgment}

尽调摘要：
- 业务评分：{business_score}
- 财务健康度：{financial_health_summary}
- 团队能力评估：{team_rating}
- 法律风险等级：{legal_risk_level}

可比公司/可比交易公开检索结果（节选）：
{search_text}

任务：
1. implied_valuation_from_round：根据本轮融资金额反推隐含估值（说明计算方式和假设的持股比例区间，不要假装精确）
2. comparable_company_method：可比公司估值法
3. comparable_transaction_method：可比交易法
4. revenue_profit_multiple_method：收入/利润倍数法（如果财务数据不足，说明为什么这个方法目前不适用）
5. risk_adjusted_range：综合尽调风险后的估值区间判断
6. scenarios：保守/基准/乐观三档情景，每档给出 valuation 和 key_assumption
7. investor_ownership_estimate：投资人持股比例测算
8. reasonableness_judgment：估值合理性判断
9. key_assumptions：估值依赖的关键假设
10. sensitivity_notes：敏感性分析说明（哪个假设变化对估值影响最大）

不要编造没有依据的可比公司估值倍数，找不到就在 missing_info 说明，用定性区间代替具体数字。
"""


class _ValuationLLM(BaseModel):
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
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_valuation_analysis(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    competitor_analysis: CompetitorAnalysis,
    due_diligence: DueDiligenceBundle,
    *,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
    search_max_results: int = 5,
) -> ValuationAnalysis:
    """Node 5 — 估值分析. Method weighting depends on funding_round (seed/A-B vs C/Pre-IPO)."""

    weighting_note = _ROUND_WEIGHTING.get(project_input.funding_round or "", "未提供融资轮次，按通用方法平均权重处理。")

    search_client = search_client or RealSearchClient()
    queries = [f"{project_input.industry or ''} 可比公司 估值 倍数", f"{project_input.industry or ''} 融资 估值 案例"]
    search_text, sources = collect_evidence(search_client, queries, category="valuation", max_results=search_max_results)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            funding_round=project_input.funding_round or "未提供",
            funding_amount=project_input.funding_amount or "未提供",
            industry=project_input.industry or "未提供",
            core_business=project_overview.core_business,
            product_service_system=project_overview.product_service_system,
            use_cases_and_value=project_overview.use_cases_and_value,
            weighting_note=weighting_note,
            industry_summary=industry_analysis.market_size_and_drivers,
            positioning_judgment=competitor_analysis.positioning_judgment or "未提供",
            business_score=due_diligence.business.business_score,
            financial_health_summary=due_diligence.financial.financial_health_summary,
            team_rating=due_diligence.team.capability_rating,
            legal_risk_level=due_diligence.legal.legal_risk_level,
            search_text=search_text[:6000] or "(无检索结果)",
        ),
        _ValuationLLM,
    )

    meta = result.meta.to_meta(sources)
    markdown = _render_markdown(project_input.company_name, weighting_note, result) + render_meta_section(meta)

    return ValuationAnalysis(
        implied_valuation_from_round=result.implied_valuation_from_round,
        comparable_company_method=result.comparable_company_method,
        comparable_transaction_method=result.comparable_transaction_method,
        revenue_profit_multiple_method=result.revenue_profit_multiple_method,
        risk_adjusted_range=result.risk_adjusted_range,
        scenarios=result.scenarios,
        investor_ownership_estimate=result.investor_ownership_estimate,
        reasonableness_judgment=result.reasonableness_judgment,
        key_assumptions=result.key_assumptions,
        sensitivity_notes=result.sensitivity_notes,
        methodology_weighting_note=weighting_note,
        markdown=markdown,
        meta=meta,
    )


def _render_markdown(company_name: str, weighting_note: str, r: _ValuationLLM) -> str:
    scenarios = "\n".join(f"- **{s.scenario}**：{s.valuation}（假设：{s.key_assumption}）" for s in r.scenarios) or "- 无"
    assumptions = "\n".join(f"- {a}" for a in r.key_assumptions) or "- 无"
    return f"""# {company_name} 估值分析报告

## 0. 本轮次方法权重说明
{weighting_note}

## 1. 本轮融资隐含估值反推
{r.implied_valuation_from_round}

## 2. 可比公司估值法
{r.comparable_company_method}

## 3. 可比交易法
{r.comparable_transaction_method}

## 4. 收入/利润倍数法
{r.revenue_profit_multiple_method}

## 5. 风险调整估值区间
{r.risk_adjusted_range}

## 6. 情景分析
{scenarios}

## 7. 投资人持股比例测算
{r.investor_ownership_estimate}

## 8. 估值合理性判断
{r.reasonableness_judgment}

## 9. 关键假设
{assumptions}

## 10. 敏感性分析
{r.sensitivity_notes}
"""
