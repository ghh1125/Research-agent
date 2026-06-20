from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import FounderProfile, NodeMetaJudgment, ProjectInput, ProjectOverview
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你在做一级市场投资项目的"项目基本概况"分析。

公司名称：{company_name}
官网：{website}
所属行业：{industry}
项目描述：{project_description}

BP/补充材料解析文本（节选）：
{bp_text}

公开检索结果（节选，可能不完整）：
{search_text}

任务：基于以上材料，输出公司基本概况，覆盖以下模块：
1. company_registration_info：公司基本工商信息（成立时间、注册资本、股权结构摘要等，没有依据就写"未公开/未在材料中找到"）
2. development_milestones：发展历程与关键里程碑
3. core_business：主营业务
4. product_service_system：核心产品/服务体系
5. use_cases_and_value：业务落地场景与核心价值
6. org_structure_and_operations：公司组织架构与运营模式
7. founder_team：创始团队背景列表，每人含 name/role/background
8. founder_team_summary：创始团队背景一句话总结

严格区分"公开事实"（必须能在材料或检索结果中找到依据）和"合理推断"（基于产品/商业模式归纳）。
找不到依据的内容要明确写"未公开"或加入 missing_info，不要编造。

{feedback_section}
"""


class _ProjectOverviewLLM(BaseModel):
    company_registration_info: str
    development_milestones: str
    core_business: str
    product_service_system: str
    use_cases_and_value: str
    org_structure_and_operations: str
    founder_team: list[FounderProfile] = Field(default_factory=list)
    founder_team_summary: str = ""
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_project_overview(
    project_input: ProjectInput,
    *,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
    search_max_results: int = 5,
    feedback: str | None = None,
) -> ProjectOverview:
    """Node 1 — 项目基本概况. `feedback` carries a human reviewer's correction request for a
    regeneration pass (e.g. "公司注册信息那段写错了，再确认一下"); omit it for the first pass."""

    search_client = search_client or RealSearchClient()
    queries = [f"{project_input.company_name} 公司简介 工商信息"]
    if project_input.website:
        queries.append(f"{project_input.company_name} {project_input.website}")
    queries.append(f"{project_input.company_name} 创始人 团队")
    queries.append(f"{project_input.company_name} 融资 历程")
    search_text, sources = collect_evidence(search_client, queries, category="project_overview", max_results=search_max_results)

    feedback_section = f"人工复核反馈（这是对上一版本的修改要求，必须按这个反馈调整，不要忽略）：\n{feedback}" if feedback else ""

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            website=project_input.website or "未提供",
            industry=project_input.industry or "未提供",
            project_description=project_input.project_description or "未提供",
            bp_text=project_input.bp_parsed_content[:4000] or "(无)",
            search_text=search_text[:6000] or "(无检索结果)",
            feedback_section=feedback_section,
        ),
        _ProjectOverviewLLM,
    )

    markdown = _render_markdown(project_input.company_name, result)
    meta = result.meta.to_meta(sources)
    markdown += render_meta_section(meta)

    return ProjectOverview(
        company_registration_info=result.company_registration_info,
        development_milestones=result.development_milestones,
        core_business=result.core_business,
        product_service_system=result.product_service_system,
        use_cases_and_value=result.use_cases_and_value,
        org_structure_and_operations=result.org_structure_and_operations,
        founder_team=result.founder_team,
        founder_team_summary=result.founder_team_summary,
        markdown=markdown,
        meta=meta,
    )


def _render_markdown(company_name: str, r: _ProjectOverviewLLM) -> str:
    founder_lines = "\n".join(f"- **{f.name}**（{f.role}）：{f.background}" for f in r.founder_team) or "- 未公开"
    return f"""# {company_name} 项目基本概况

## 1. 公司基本工商信息
{r.company_registration_info}

## 2. 发展历程与关键里程碑
{r.development_milestones}

## 3. 主营业务
{r.core_business}

## 4. 核心产品/服务体系
{r.product_service_system}

## 5. 业务落地场景与核心价值
{r.use_cases_and_value}

## 6. 公司组织架构与运营模式
{r.org_structure_and_operations}

## 7. 创始团队背景
{founder_lines}

{r.founder_team_summary}
"""
