from __future__ import annotations

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import BusinessDueDiligence, BusinessScore, CompetitorAnalysis, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview

_PROMPT = """\
你在做一级市场投资项目的"业务尽调"。

公司：{company_name}　融资轮次：{funding_round}

项目概况：
主营业务：{core_business}
落地场景与价值：{use_cases_and_value}

行业市场规模与增长驱动（来自行业深度分析节点）：
{market_size_and_drivers}

竞品分析定位判断（参考）：
{positioning_judgment}

用户上传的业务规划书/商业计划书解析文本（节选，可能为空）：
{business_file_text}

其他尽调维度已完成的初步发现（供你判断跨领域风险，例如关键人风险是否影响增长可持续性，不要照抄，只在结论里体现交叉影响）：
{peer_findings}

任务：
1. business_model_analysis：商业模式分析
2. market_analysis：市场分析（结合行业市场规模与增长驱动判断业务所处赛道是否处于上升期）
3. growth_model：增长模型
4. competitive_landscape_analysis：结合竞品定位判断的竞争格局分析
5. risk_notes：业务风险提示列表（如果团队尽调发现的关键人风险会影响业务可持续性，在这里体现）
6. business_score：业务评分，只能是"优"/"良"/"中"/"差"

没有依据的内容写"资料不足"，不要编造具体的增长数字。
"""


class _BusinessLLM(BaseModel):
    business_model_analysis: str
    market_analysis: str
    growth_model: str
    competitive_landscape_analysis: str
    risk_notes: list[str] = Field(default_factory=list)
    business_score: BusinessScore
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_business_due_diligence(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    competitor_analysis: CompetitorAnalysis,
    *,
    business_plan_files: list[str] | None = None,
    llm_client: RealLLMClient | None = None,
    peer_findings: str | None = None,
) -> BusinessDueDiligence:
    """Node 4 sub-report — 业务尽调. peer_findings lets earlier-completed due-diligence agents (typically 团队尽调)
    share their preliminary findings so this report can account for cross-domain risk."""

    parsed = parse_files(business_plan_files or [])
    business_file_text = truncate("\n\n".join(p.text for p in parsed if p.text), 8000)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            funding_round=project_input.funding_round or "未提供",
            core_business=project_overview.core_business,
            use_cases_and_value=project_overview.use_cases_and_value,
            market_size_and_drivers=industry_analysis.market_size_and_drivers,
            positioning_judgment=competitor_analysis.positioning_judgment or "未提供",
            business_file_text=business_file_text or "(用户未上传业务规划书)",
            peer_findings=peer_findings or "(暂无其他尽调维度的初步发现)",
        ),
        _BusinessLLM,
    )

    meta = result.meta.to_meta([])
    risk_lines = "\n".join(f"- {r}" for r in result.risk_notes) or "- 无明显风险提示"
    markdown = f"""# 业务尽调报告

## 1. 商业模式分析
{result.business_model_analysis}

## 2. 市场分析
{result.market_analysis}

## 3. 增长模型
{result.growth_model}

## 4. 竞争格局分析
{result.competitive_landscape_analysis}

## 5. 风险提示
{risk_lines}

## 6. 业务评分
{result.business_score}
""" + render_meta_section(meta)

    return BusinessDueDiligence(
        business_model_analysis=result.business_model_analysis,
        market_analysis=result.market_analysis,
        growth_model=result.growth_model,
        competitive_landscape_analysis=result.competitive_landscape_analysis,
        risk_notes=result.risk_notes,
        business_score=result.business_score,
        markdown=markdown,
        meta=meta,
    )
