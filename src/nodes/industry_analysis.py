from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import NodeMetaJudgment, ProjectInput, ProjectOverview, IndustryAnalysis
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你在做一级市场投资项目的"行业深度分析"。

目标公司：{company_name}
所属行业：{industry}
主营业务：{core_business}
核心产品/落地场景：{product_and_scene}

行业相关公开检索结果（节选）：
{search_text}

任务：输出行业分析报告，覆盖：
1. industry_definition：行业定义与边界
2. development_trends：行业发展趋势
3. market_size_and_drivers：市场规模与增长驱动
4. industry_chain_structure：产业链结构
5. competitive_landscape：市场竞争格局
6. policy_environment：政策环境分析
7. opportunities_and_barriers：市场机会与进入壁垒
8. opportunity_mapping_to_target：把行业机会映射到目标公司所处的细分位置，回答"这个赛道为什么现在值得看，目标公司在哪个细分位置"
9. key_assumptions：本次分析依赖的关键假设列表

只用检索结果和常识支持的内容下结论；没有数据支撑的市场规模数字要在 missing_info 里注明，不要编造具体数字。

{feedback_section}
"""


class _IndustryAnalysisLLM(BaseModel):
    industry_definition: str
    development_trends: str
    market_size_and_drivers: str
    industry_chain_structure: str
    competitive_landscape: str
    policy_environment: str
    opportunities_and_barriers: str
    opportunity_mapping_to_target: str
    key_assumptions: list[str] = Field(default_factory=list)
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_industry_analysis(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    *,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
    search_max_results: int = 5,
    feedback: str | None = None,
) -> IndustryAnalysis:
    """Node 2 — 行业深度分析. `feedback` carries a human reviewer's correction request for a
    regeneration pass; omit it for the first pass."""

    search_client = search_client or RealSearchClient()
    industry = project_input.industry or "未提供"
    queries = [
        f"{industry} 行业 发展趋势 市场规模",
        f"{industry} 行业 竞争格局",
        f"{industry} 行业 政策 监管",
        f"{industry} 产业链 上下游",
    ]
    search_text, sources = collect_evidence(search_client, queries, category="industry", max_results=search_max_results)

    feedback_section = f"人工复核反馈（这是对上一版本的修改要求，必须按这个反馈调整，不要忽略）：\n{feedback}" if feedback else ""

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            industry=industry,
            core_business=project_overview.core_business,
            product_and_scene=project_overview.use_cases_and_value,
            search_text=search_text[:7000] or "(无检索结果)",
            feedback_section=feedback_section,
        ),
        _IndustryAnalysisLLM,
    )

    meta = result.meta.to_meta(sources)
    markdown = _render_markdown(industry, result) + render_meta_section(meta)

    return IndustryAnalysis(
        industry_definition=result.industry_definition,
        development_trends=result.development_trends,
        market_size_and_drivers=result.market_size_and_drivers,
        industry_chain_structure=result.industry_chain_structure,
        competitive_landscape=result.competitive_landscape,
        policy_environment=result.policy_environment,
        opportunities_and_barriers=result.opportunities_and_barriers,
        opportunity_mapping_to_target=result.opportunity_mapping_to_target,
        key_assumptions=result.key_assumptions,
        markdown=markdown,
        meta=meta,
    )


def _render_markdown(industry: str, r: _IndustryAnalysisLLM) -> str:
    assumptions = "\n".join(f"- {a}" for a in r.key_assumptions) or "- 无"
    return f"""# {industry} 行业深度分析

## 1. 行业定义与边界
{r.industry_definition}

## 2. 行业发展趋势
{r.development_trends}

## 3. 市场规模与增长驱动
{r.market_size_and_drivers}

## 4. 产业链结构
{r.industry_chain_structure}

## 5. 市场竞争格局
{r.competitive_landscape}

## 6. 政策环境分析
{r.policy_environment}

## 7. 市场机会与进入壁垒
{r.opportunities_and_barriers}

## 8. 机会映射到目标公司
{r.opportunity_mapping_to_target}

## 9. 行业关键假设
{assumptions}
"""
