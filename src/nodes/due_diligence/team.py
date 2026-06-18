from __future__ import annotations

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import CapabilityRating, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview, TeamDueDiligence
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你在做一级市场投资项目的"团队尽调"。

公司：{company_name}　融资轮次：{funding_round}　所属行业：{industry}

已知创始团队背景（来自项目概况节点）：
{founder_summary}

行业背景（来自行业深度分析节点，供你判断团队背景是否匹配行业要求）：
{industry_context}

用户上传的创始团队资料解析文本（节选，可能为空）：
{team_file_text}

公开检索结果（节选）：
{search_text}

任务：
1. founder_profiles：创始人履历画像
2. team_capability_matrix：团队能力矩阵（技术/产品/市场/管理等维度覆盖情况，结合行业背景判断团队能力是否匹配赛道要求）
3. equity_stability_analysis：股权稳定性分析（创始人持股、是否有股权纠纷迹象等，没有依据写"资料不足"）
4. key_person_risk：关键人风险提示
5. capability_rating：团队能力评估，只能是"强"/"中"/"弱"

没有依据的内容要在 missing_info 中说明，不要编造履历细节。
"""


class _TeamLLM(BaseModel):
    founder_profiles: str
    team_capability_matrix: str
    equity_stability_analysis: str
    key_person_risk: str
    capability_rating: CapabilityRating
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_team_due_diligence(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    *,
    team_files: list[str] | None = None,
    llm_client: RealLLMClient | None = None,
    search_client: RealSearchClient | None = None,
) -> TeamDueDiligence:
    """Node 4 sub-report — 团队尽调."""

    parsed = parse_files(team_files or [])
    team_file_text = truncate("\n\n".join(p.text for p in parsed if p.text), 6000)

    search_client = search_client or RealSearchClient()
    names = ", ".join(f.name for f in project_overview.founder_team) or project_input.company_name
    search_text, sources = collect_evidence(search_client, [f"{names} 创业 履历 背景"], category="team_dd", max_results=4)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            funding_round=project_input.funding_round or "未提供",
            industry=project_input.industry or "未提供",
            founder_summary=project_overview.founder_team_summary or "未提供",
            industry_context=industry_analysis.opportunities_and_barriers,
            team_file_text=team_file_text or "(用户未上传团队资料)",
            search_text=search_text[:5000] or "(无检索结果)",
        ),
        _TeamLLM,
    )

    meta = result.meta.to_meta(sources)
    markdown = f"""# 团队尽调报告

## 1. 创始人履历画像
{result.founder_profiles}

## 2. 团队能力矩阵
{result.team_capability_matrix}

## 3. 股权稳定性分析
{result.equity_stability_analysis}

## 4. 关键人风险提示
{result.key_person_risk}

## 5. 团队能力评估
{result.capability_rating}
""" + render_meta_section(meta)

    return TeamDueDiligence(
        founder_profiles=result.founder_profiles,
        team_capability_matrix=result.team_capability_matrix,
        equity_stability_analysis=result.equity_stability_analysis,
        key_person_risk=result.key_person_risk,
        capability_rating=result.capability_rating,
        markdown=markdown,
        meta=meta,
    )
