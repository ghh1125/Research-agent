from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import CompetitorAnalysis, CompetitorDiscovery, CompetitorProfile, IndustryAnalysis, NodeMetaJudgment, ProjectInput, ProjectOverview
from src.search import RealSearchClient, collect_evidence

_PROMPT = """\
你是一级市场投资机构的竞争战略分析师。请对目标公司和投资人最终确认的竞品 shortlist
进行证据驱动的竞品矩阵分析。该报告将直接作为后续业务尽调、估值分析和投资建议的输入，
因此结论必须可追溯、比较口径一致，并明确暴露信息缺口。

目标公司：{company_name}
官网：{website}
所属行业：{industry}
主营业务：{core_business}
产品/服务体系：{product_service}
落地场景与核心价值：{use_cases_and_value}

行业深度分析结论：
- 行业竞争格局：{competitive_landscape}
- 行业机会与进入壁垒：{opportunities_and_barriers}
- 目标公司与行业机会的映射：{opportunity_mapping_to_target}

用户最终确认的竞品 shortlist 及公开检索证据（节选）：
{competitor_text}

硬性分析规则：
1. 只分析用户最终确认的竞品，不得自行新增、替换或遗漏；competitor_profiles 必须逐家覆盖 shortlist。
2. 目标公司与所有竞品必须采用完全一致的比较口径，禁止一方写产品、另一方写公司宣传口号。
3. 每项结论都要区分事实、推断和资料不足：事实须有证据，推断须说明依据。没有依据时明确写"未公开/资料不足"，不得补全常识性猜测。
4. 不得把融资规模、品牌知名度或公司规模直接等同于产品能力、商业化能力或技术壁垒。
5. strengths 和 weaknesses 必须说明相对于目标公司的具体比较依据，避免"技术领先"等无证据评价。
6. SWOT 的 S/W 聚焦目标公司内部能力，O/T 结合行业外部环境和竞品动作，不得简单重复竞品画像。
7. 涉及融资、客户、收入、市场份额和技术指标等时效性事实时，只使用提供的证据；证据不充分则标记信息缺口。

输出要求：
1. overview：说明竞争边界、竞争层级、主要竞争变量和目标公司的相对位置，不超过 300 字。
2. competitor_profiles：逐个竞品输出 capability_summary、business_model、customer_and_scene、
   tech_barrier、funding_and_progress、strengths、weaknesses。优势和劣势均以目标公司为参照。
3. capability_matrix：必须包含目标公司和每个选中竞品。固定输出"产品能力/商业模式/客户与场景/
   技术壁垒/商业化与融资进展"五行；每行是 dict，使用 "dimension" 标记维度，其他 key 使用公司全称。
   每个单元格写"结论；依据/状态"，资料不足也要保留该公司单元格。
4. swot_strengths、swot_weaknesses、swot_opportunities、swot_threats：输出目标公司的相对 SWOT，
   每一点均应具体、互不重复。
5. positioning_judgment：形成可被下游直接引用的综合判断，必须包含目标定位、核心差异化、关键短板、
   竞争风险，以及对后续业务尽调和估值可比性的影响。
6. meta：assumptions 记录推断前提，missing_info 记录会影响竞争判断的缺失资料，
   risk_flags 记录可能改变投资结论的竞争风险，并据证据完整性给出 confidence。
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
    evidence_chars_per_competitor = max(600, 8000 // len(selected))
    for candidate in selected:
        queries = [
            f"{candidate.name} 官网 产品 客户案例 商业模式",
            f"{candidate.name} 融资 收入 商业化进展",
            f"{candidate.name} 技术 专利 核心壁垒",
        ]
        text, sources = collect_evidence(search_client, queries, category="competitor_analysis", max_results=search_max_results)
        all_sources.extend(sources)
        competitor_blocks.append(
            f"### {candidate.name}\n"
            f"官网：{candidate.website or '未提供'}\n"
            f"竞争关系：{candidate.relationship}\n"
            f"发现阶段产品/服务：{candidate.product_or_service}\n"
            f"纳入理由：{candidate.reason}\n"
            f"公开检索证据：\n{text[:evidence_chars_per_competitor]}"
        )

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _PROMPT.format(
            company_name=project_input.company_name,
            website=project_input.website or "未提供",
            industry=project_input.industry or "未提供",
            core_business=project_overview.core_business,
            product_service=project_overview.product_service_system,
            use_cases_and_value=project_overview.use_cases_and_value,
            competitive_landscape=industry_analysis.competitive_landscape,
            opportunities_and_barriers=industry_analysis.opportunities_and_barriers,
            opportunity_mapping_to_target=industry_analysis.opportunity_mapping_to_target,
            competitor_text="\n\n".join(competitor_blocks) or "(无资料)",
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
    matrix_rows = _render_capability_matrix(r.capability_matrix)
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


def _render_capability_matrix(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- （无可用矩阵数据）"

    companies: list[str] = []
    for row in rows:
        for key in row:
            if key != "dimension" and key not in companies:
                companies.append(key)

    def escape(value: Any) -> str:
        return str(value or "资料不足").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")

    headers = ["对比维度", *companies]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = [escape(row.get("dimension")), *(escape(row.get(company)) for company in companies)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
