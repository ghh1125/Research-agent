from __future__ import annotations

from pydantic import BaseModel, Field

from src.files import parse_files, truncate
from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview, TechIPDueDiligence

_PROMPT = """\
你在做一级市场投资项目的"技术与知识产权尽调"。

公司：{company_name}　所属行业：{industry}
核心产品/服务体系：{product_service}

行业竞争格局（来自行业深度分析节点，供你判断技术壁垒在该行业里是否真正构成竞争优势）：
{competitive_landscape}

用户上传的技术与知识产权资料解析文本（节选，可能为空）：
{tech_file_text}

其他尽调维度已完成的初步发现（供你判断研发团队评估是否要交叉验证团队尽调的结论，不要照抄，只在结论里体现交叉影响）：
{peer_findings}

任务：
1. architecture_review：技术架构评审
2. rd_team_assessment：研发团队评估（如果团队尽调认为团队能力偏弱，结合判断研发团队是否同样存在能力缺口）
3. core_tech_barrier：核心技术壁垒（结合行业竞争格局判断这个壁垒是否足够构成优势；如果资料中提到专利/软著/商标等知识产权资产，作为壁垒的一部分在这里说明，没有就写"资料不足"）
4. risk_notes：技术与知识产权相关风险提示

没有依据的内容写"资料不足"，不要编造专利号或具体技术细节。
"""


class _TechIPLLM(BaseModel):
    architecture_review: str
    rd_team_assessment: str
    core_tech_barrier: str
    risk_notes: list[str] = Field(default_factory=list)
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


def run_tech_ip_due_diligence(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    *,
    tech_ip_files: list[str] | None = None,
    llm_client: RealLLMClient | None = None,
    peer_findings: str | None = None,
) -> TechIPDueDiligence:
    """Node 4 sub-report — 技术与知识产权尽调. peer_findings typically carries 团队尽调 preliminary findings
    so the R&D team assessment can cross-check the team capability rating."""

    parsed = parse_files(tech_ip_files or [])
    tech_file_text = truncate("\n\n".join(p.text for p in parsed if p.text), 8000)

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            industry=project_input.industry or "未提供",
            product_service=project_overview.product_service_system,
            competitive_landscape=industry_analysis.competitive_landscape,
            tech_file_text=tech_file_text or "(用户未上传技术与知识产权资料)",
            peer_findings=peer_findings or "(暂无其他尽调维度的初步发现)",
        ),
        _TechIPLLM,
    )

    meta = result.meta.to_meta([])
    risk_lines = "\n".join(f"- {r}" for r in result.risk_notes) or "- 无明显风险提示"
    markdown = f"""# 技术与知识产权尽调报告

## 1. 技术架构评审
{result.architecture_review}

## 2. 研发团队评估
{result.rd_team_assessment}

## 3. 核心技术壁垒
{result.core_tech_barrier}

## 4. 风险提示
{risk_lines}
""" + render_meta_section(meta)

    return TechIPDueDiligence(
        architecture_review=result.architecture_review,
        rd_team_assessment=result.rd_team_assessment,
        core_tech_barrier=result.core_tech_barrier,
        risk_notes=result.risk_notes,
        markdown=markdown,
        meta=meta,
    )
