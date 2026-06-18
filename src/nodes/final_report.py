from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import (
    CompetitorAnalysis,
    DueDiligenceBundle,
    FinalInvestmentReport,
    IndustryAnalysis,
    NodeMetaJudgment,
    ProjectInput,
    ProjectOverview,
    ValuationAnalysis,
)

_PROMPT = """\
你在为一级市场投资项目撰写"综合研判与报告输出"里需要二次分析/综合生成的部分。
项目概况、行业分析、竞品分析、估值分析这四块已经在别的节点直接复用，不需要你重写。

公司：{company_name}
融资轮次：{funding_round}
融资金额：{funding_amount}

项目概况要点：{overview_brief}
行业要点：{industry_brief}
竞品定位判断：{positioning_judgment}
估值要点：{valuation_brief}

团队尽调：{team_summary}
业务尽调：{business_summary}
财务尽调：{financial_summary}
技术与知识产权尽调：{tech_ip_summary}
法律尽调：{legal_summary}
风险清单：{risk_register}

任务，输出以下 8 个字段：
1. investment_summary：投资摘要（结论先行，3-5 句话）
2. business_model_section：项目商业模式二次分析（结合业务尽调和项目概况）
3. team_and_governance_section：核心团队与公司治理二次分析（结合团队尽调和法律尽调里的股权结构）
4. financial_section：财务经营数据分析二次分析（结合财务尽调）
5. risk_section：全方位风险尽调与风险提示汇总（汇总 risk_register，按团队/业务/财务/技术/法律分类）
6. core_logic_and_recommendation：核心投资逻辑与投资建议
7. risk_response_and_post_investment：风险应对措施与投后管控建议
8. exit_path_and_return：退出路径与收益测算（说明潜在退出方式，不要编造具体收益倍数，给区间和假设）

结论要能追溯到前面给的尽调要点，不要引入新的、没有依据的事实。
"""


class _FinalReportLLM(BaseModel):
    investment_summary: str
    business_model_section: str
    team_and_governance_section: str
    financial_section: str
    risk_section: str
    core_logic_and_recommendation: str
    risk_response_and_post_investment: str
    exit_path_and_return: str
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_final_report(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    competitor_analysis: CompetitorAnalysis,
    due_diligence: DueDiligenceBundle,
    valuation_analysis: ValuationAnalysis,
    *,
    llm_client: RealLLMClient | None = None,
) -> FinalInvestmentReport:
    """Node 6 — 综合研判与报告输出.

    直接复用: project_overview_section / industry_section / competitor_section / valuation_section
    综合生成: investment_summary / core_logic_and_recommendation / risk_response_and_post_investment
    二次分析: business_model_section / team_and_governance_section / financial_section / risk_section
    """

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            funding_round=project_input.funding_round or "未提供",
            funding_amount=project_input.funding_amount or "未提供",
            overview_brief=project_overview.core_business,
            industry_brief=industry_analysis.opportunity_mapping_to_target,
            positioning_judgment=competitor_analysis.positioning_judgment,
            valuation_brief=valuation_analysis.risk_adjusted_range,
            team_summary=due_diligence.team.key_person_risk + " | " + due_diligence.team.capability_rating,
            business_summary=due_diligence.business.business_model_analysis + " | 评分:" + due_diligence.business.business_score,
            financial_summary=due_diligence.financial.financial_health_summary,
            tech_ip_summary=due_diligence.tech_ip.core_tech_barrier,
            legal_summary=due_diligence.legal.legal_risk_level,
            risk_register=[item.model_dump() for item in due_diligence.risk_register],
        ),
        _FinalReportLLM,
    )

    all_sources = list(project_overview.meta.sources) + list(industry_analysis.meta.sources) + list(competitor_analysis.meta.sources) + list(valuation_analysis.meta.sources) + list(due_diligence.evidence_index)
    all_assumptions = list(industry_analysis.key_assumptions) + list(valuation_analysis.key_assumptions)
    all_missing_info = (
        list(project_overview.meta.missing_info)
        + list(industry_analysis.meta.missing_info)
        + list(competitor_analysis.meta.missing_info)
        + list(valuation_analysis.meta.missing_info)
        + list(due_diligence.team.meta.missing_info)
        + list(due_diligence.business.meta.missing_info)
        + list(due_diligence.financial.meta.missing_info)
        + list(due_diligence.tech_ip.meta.missing_info)
        + list(due_diligence.legal.meta.missing_info)
    )
    meta = result.meta.to_meta(all_sources)
    meta.missing_info = list(dict.fromkeys(all_missing_info + meta.missing_info))

    report = FinalInvestmentReport(
        investment_summary=result.investment_summary,
        project_overview_section=_embed_subsection(project_overview.markdown),
        industry_section=_embed_subsection(industry_analysis.markdown),
        business_model_section=result.business_model_section,
        team_and_governance_section=result.team_and_governance_section,
        financial_section=result.financial_section,
        competitor_section=_embed_subsection(competitor_analysis.markdown),
        risk_section=result.risk_section,
        valuation_section=_embed_subsection(valuation_analysis.markdown),
        core_logic_and_recommendation=result.core_logic_and_recommendation,
        risk_response_and_post_investment=result.risk_response_and_post_investment,
        exit_path_and_return=result.exit_path_and_return,
        sources=all_sources,
        assumptions=list(dict.fromkeys(all_assumptions)),
        risk_register=due_diligence.risk_register,
        missing_info=meta.missing_info,
        meta=meta,
    )
    report.markdown = _render_markdown(project_input.company_name, report) + render_meta_section(meta)
    return report


def _embed_subsection(markdown: str) -> str:
    """Strip the child report's H1 title and demote its remaining headers by one level so they
    nest under this report's own numbered sections instead of colliding with them (both use ##)."""

    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(f"#{line}" if line.startswith("#") else line for line in lines)


def _render_markdown(company_name: str, r: FinalInvestmentReport) -> str:
    risk_lines = "\n".join(f"- [{item.severity}] {item.category}：{item.description}" for item in r.risk_register) or "- 无"
    missing_lines = "\n".join(f"- {item}" for item in r.missing_info) or "- 无"
    return f"""# {company_name} 项目投研报告

## 1. 投资摘要
{r.investment_summary}

## 2. 项目基本概况
{r.project_overview_section}

## 3. 行业赛道分析
{r.industry_section}

## 4. 项目商业模式
{r.business_model_section}

## 5. 核心团队与公司治理
{r.team_and_governance_section}

## 6. 财务经营数据分析
{r.financial_section}

## 7. 竞品分析
{r.competitor_section}

## 8. 全方位风险尽调与风险提示
{r.risk_section}

### 风险清单
{risk_lines}

## 9. 估值测算
{r.valuation_section}

## 10. 核心投资逻辑与投资建议
{r.core_logic_and_recommendation}

## 11. 风险应对措施与投后管控建议
{r.risk_response_and_post_investment}

## 12. 退出路径与收益测算
{r.exit_path_and_return}

## 附录：信息缺口
{missing_lines}
"""
