from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import CompetitorAnalysis, CompetitorDiscovery, CompetitorProfile, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你在为一级市场投资项目做"竞品矩阵分析"，对比目标公司与已确认的竞品 shortlist。

目标公司：{company_name}
主营业务：{core_business}
产品/服务体系：{product_service}

竞品 shortlist 及检索资料（节选）：
{competitor_text}

任务：
1. overview：竞争格局总览一段话
2. competitor_profiles：逐个竞品输出 capability_summary/business_model/customer_and_scene/tech_barrier/funding_and_progress/strengths/weaknesses
3. capability_matrix：把目标公司和每个竞品放进同一张对比矩阵，每行是一个维度（产品能力/商业模式/客户场景/技术壁垒/融资进展），每行用 dict 表示，key 为公司名，value 为该维度下的简要评价，并包含一个 "dimension" key 标明维度名
4. swot_strengths/weaknesses/opportunities/threats：目标公司相对于这些竞品的 SWOT
5. positioning_judgment：目标公司在这个竞争格局里的定位判断

只基于提供的资料下结论，没有依据的内容写"未公开/资料不足"。
"""


class _CompetitorProfileLLM(BaseModel):
    name: str
    capability_summary: str
    business_model: str
    customer_and_scene: str
    tech_barrier: str
    funding_and_progress: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class _CompetitorAnalysisLLM(BaseModel):
    overview: str
    competitor_profiles: list[_CompetitorProfileLLM] = Field(default_factory=list)
    capability_matrix: list[dict[str, Any]] = Field(default_factory=list)
    swot_strengths: list[str] = Field(default_factory=list)
    swot_weaknesses: list[str] = Field(default_factory=list)
    swot_opportunities: list[str] = Field(default_factory=list)
    swot_threats: list[str] = Field(default_factory=list)
    positioning_judgment: str = ""
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_competitor_analysis(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    discovery: CompetitorDiscovery,
    *,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
    search_max_results: int = 4,
) -> CompetitorAnalysis:
    """Node 3.2 — 竞品矩阵分析, runs only on the user-confirmed shortlist (discovery.selected_ids)."""

    selected = discovery.selected()
    if not selected:
        raise ValueError("没有已选定的竞品；请先在竞品发现节点确认 selected_ids")

    search_client = search_client or RealSearchClient()
    all_sources = []
    competitor_blocks = []
    for candidate in selected:
        queries = [f"{candidate.name} 产品 商业模式 融资"]
        text, sources = collect_evidence(search_client, queries, category="competitor_analysis", max_results=search_max_results)
        all_sources.extend(sources)
        competitor_blocks.append(f"### {candidate.name}\n关系：{candidate.relationship}\n产品：{candidate.product_or_service}\n检索资料：\n{text}")

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            core_business=project_overview.core_business,
            product_service=project_overview.product_service_system,
            competitor_text="\n\n".join(competitor_blocks)[:9000] or "(无资料)",
        ),
        _CompetitorAnalysisLLM,
    )

    meta = result.meta.to_meta(all_sources)
    markdown = _render_markdown(project_input.company_name, result) + render_meta_section(meta)

    return CompetitorAnalysis(
        overview=result.overview,
        competitor_profiles=[CompetitorProfile(**p.model_dump()) for p in result.competitor_profiles],
        capability_matrix=result.capability_matrix,
        swot_strengths=result.swot_strengths,
        swot_weaknesses=result.swot_weaknesses,
        swot_opportunities=result.swot_opportunities,
        swot_threats=result.swot_threats,
        positioning_judgment=result.positioning_judgment,
        markdown=markdown,
        meta=meta,
    )


def _render_markdown(company_name: str, r: _CompetitorAnalysisLLM) -> str:
    profiles = "\n\n".join(
        f"### {p.name}\n- 能力概述：{p.capability_summary}\n- 商业模式：{p.business_model}\n- 客户/场景：{p.customer_and_scene}\n"
        f"- 技术壁垒：{p.tech_barrier}\n- 融资进展：{p.funding_and_progress}\n"
        f"- 优势：{', '.join(p.strengths) or '无'}\n- 劣势：{', '.join(p.weaknesses) or '无'}"
        for p in r.competitor_profiles
    )
    matrix_rows = "\n".join(f"- {row}" for row in r.capability_matrix) or "- (无)"
    return f"""# {company_name} 竞品矩阵分析

## 1. 竞争格局总览
{r.overview}

## 2. 主要竞争对手概览
{profiles}

## 3. 产品能力对比矩阵
{matrix_rows}

## 4. SWOT 综合分析
- 优势（S）：{', '.join(r.swot_strengths) or '无'}
- 劣势（W）：{', '.join(r.swot_weaknesses) or '无'}
- 机会（O）：{', '.join(r.swot_opportunities) or '无'}
- 威胁（T）：{', '.join(r.swot_threats) or '无'}

## 5. 目标公司定位判断
{r.positioning_judgment}
"""
