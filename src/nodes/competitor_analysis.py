from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.report import render_meta_section
from src.schema import (
    CompetitorAnalysis,
    CompetitorDiscovery,
    CompetitorProfile,
    IndustryAnalysis,
    NodeMeta,
    NodeMetaJudgment,
    ProjectInput,
    ProjectOverview,
    SingleCompetitorAnalysis,
    Source,
)
from src.search import RealSearchClient, collect_evidence

MATRIX_DIMENSIONS = ["产品能力", "商业模式", "客户与场景", "技术壁垒", "商业化与融资进展"]

_SINGLE_PROMPT = """\
你是一级市场投资机构的竞争情报分析师。当前只分析一个竞品，不做多竞品汇总。

目标公司：
- 名称：{company_name}
- 官网：{website}
- 行业：{industry}
- 主营业务：{core_business}
- 产品/服务：{product_service}
- 落地场景与核心价值：{use_cases_and_value}

行业背景：
- 竞争格局：{competitive_landscape}
- 机会与壁垒：{opportunities_and_barriers}
- 目标公司机会映射：{opportunity_mapping_to_target}

当前竞品：
- ID：{candidate_id}
- 名称：{candidate_name}
- 官网：{candidate_website}
- 竞争关系：{relationship}
- 发现阶段产品/服务：{candidate_product}
- 纳入理由：{candidate_reason}

当前竞品公开检索证据（完整保留搜索接口返回文本）：
{evidence_text}

当前竞品已有结构化结果（首次分析时为“无”）：
{current_result}

人工审核修改指令（首次分析时为“无”）：
{feedback}

硬性规则：
1. 只分析当前竞品“{candidate_name}”，不得引入或猜测其他竞品。
2. profile.name 必须等于“{candidate_name}”。
3. strengths/weaknesses 必须以目标公司为参照，说明具体比较依据。
4. matrix_values 必须包含“产品能力、商业模式、客户与场景、技术壁垒、商业化与融资进展”五个 key。
5. 每个矩阵值使用“结论；证据或信息状态”的格式。
6. 严格区分事实、推断和资料不足。事实须有证据；推断须说明依据；无依据写“未公开/资料不足”。
7. 不得把融资额、知名度或公司规模直接等同于产品、商业化或技术优势。
8. 不得补造客户、收入、份额、融资、专利或技术指标。
9. 有人工反馈时，逐条处理与当前竞品相关的指令；与反馈无关且证据充分的字段保持稳定。
10. 反馈与证据冲突时指出冲突；反馈缺少证据时写入 missing_info，不得迎合反馈编造。

输出 profile、matrix_values 和 meta。meta 必须反映假设、置信度、信息缺口和竞争风险。
"""

_SYNTHESIS_PROMPT = """\
你是一级市场投资机构的竞争战略负责人。下面的逐家竞品结果已经分别基于公开证据生成，
能力矩阵也已由程序按统一维度确定性合并。你只负责全局综合判断，不得新增事实。

目标公司：{company_name}
行业：{industry}
主营业务：{core_business}
产品/服务：{product_service}
落地场景与价值：{use_cases_and_value}
行业竞争格局：{competitive_landscape}
行业机会与壁垒：{opportunities_and_barriers}
目标公司机会映射：{opportunity_mapping_to_target}

逐家结构化结果：
{individual_results_json}

确定性能力矩阵：
{capability_matrix_json}

当前汇总结论（首次汇总时为“无”）：
{current_summary}

人工审核修改指令（首次汇总时为“无”）：
{feedback}

硬性规则：
1. 只分析用户最终确认的竞品，必须覆盖逐家结果中的全部竞品，不得新增、替换或遗漏。
2. 只能根据逐家结构化结果、能力矩阵和行业上下文汇总，不得新增客户、收入、融资、专利等事实。
3. 明确区分事实、推断和资料不足；推断必须保留依据，资料不足不得改写成确定事实。
4. overview 必须说明竞争边界、竞争层级、关键竞争变量和目标公司的相对位置。
5. SWOT 中 S/W 聚焦目标公司内部相对能力，O/T 聚焦行业外部环境和竞品动作。
6. positioning_judgment 必须包含目标定位、证据支持的差异化、关键短板、竞争风险，
   并明确对后续业务尽调和估值可比性的影响，包括验证要求、可比公司选择和折溢价。
7. 逐家结果冲突时明确指出，不强行形成确定结论。
8. 有人工反馈时逐条定向修订；与反馈无关且有依据的结论保持稳定。
9. 反馈缺少证据时写入 missing_info，不得为了迎合反馈而编造。
10. meta 必须综合逐家信息缺口、假设和风险，并据证据完整性判断 confidence。
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


class _SingleCompetitorAnalysisLLM(BaseModel):
    profile: _CompetitorProfileLLM
    matrix_values: dict[str, str] = Field(default_factory=dict)
    meta: NodeMetaJudgment = Field(default_factory=NodeMetaJudgment)


class _CompetitorSynthesisLLM(BaseModel):
    overview: str
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
    feedback: str | None = None,
    current_analysis: CompetitorAnalysis | None = None,
) -> CompetitorAnalysis:
    """Analyze each selected competitor sequentially, then synthesize one matrix report."""

    selected = discovery.selected()
    if not selected:
        raise ValueError("没有已选定的竞品；请先在竞品发现节点确认 selected_ids")

    client = llm_client or RealLLMClient()
    search = search_client or RealSearchClient()
    individual_results: list[SingleCompetitorAnalysis] = []
    current_results = {
        item.candidate_id: item for item in (current_analysis.individual_results if current_analysis is not None else [])
    }

    for candidate in selected:
        queries = [
            f"{candidate.name} 官网 产品 客户案例 商业模式",
            f"{candidate.name} 融资 收入 商业化进展",
            f"{candidate.name} 技术 专利 核心壁垒",
        ]
        if feedback and feedback.strip():
            queries.append(f"{candidate.name} {feedback.strip()}")
        evidence_text, sources = collect_evidence(search, queries, category="competitor_analysis", max_results=search_max_results)
        try:
            result = client.complete_json(
                _SINGLE_PROMPT.format(
                    company_name=project_input.company_name,
                    website=project_input.website or "未提供",
                    industry=project_input.industry or "未提供",
                    core_business=project_overview.core_business,
                    product_service=project_overview.product_service_system,
                    use_cases_and_value=project_overview.use_cases_and_value,
                    competitive_landscape=industry_analysis.competitive_landscape,
                    opportunities_and_barriers=industry_analysis.opportunities_and_barriers,
                    opportunity_mapping_to_target=industry_analysis.opportunity_mapping_to_target,
                    candidate_id=candidate.id,
                    candidate_name=candidate.name,
                    candidate_website=candidate.website or "未提供",
                    relationship=candidate.relationship,
                    candidate_product=candidate.product_or_service,
                    candidate_reason=candidate.reason,
                    evidence_text=evidence_text or "(无检索结果)",
                    current_result=(
                        current_results[candidate.id].model_dump_json(indent=2)
                        if candidate.id in current_results
                        else "无"
                    ),
                    feedback=feedback.strip() if feedback and feedback.strip() else "无",
                ),
                _SingleCompetitorAnalysisLLM,
            )
        except Exception as exc:
            raise RuntimeError(f"竞品“{candidate.name}”分析失败：{exc}") from exc

        profile_data = result.profile.model_dump()
        profile_data["name"] = candidate.name
        matrix_values = {dimension: result.matrix_values.get(dimension, "资料不足") for dimension in MATRIX_DIMENSIONS}
        individual_results.append(
            SingleCompetitorAnalysis(
                candidate_id=candidate.id,
                profile=CompetitorProfile(**profile_data),
                matrix_values=matrix_values,
                meta=result.meta.to_meta(sources),
            )
        )

    return synthesize_competitor_analysis(
        project_input,
        project_overview,
        industry_analysis,
        individual_results,
        llm_client=client,
        feedback=feedback,
    )


def synthesize_competitor_analysis(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    industry_analysis: IndustryAnalysis,
    individual_results: list[SingleCompetitorAnalysis],
    *,
    llm_client: RealLLMClient | None = None,
    feedback: str | None = None,
    current_analysis: CompetitorAnalysis | None = None,
) -> CompetitorAnalysis:
    if not individual_results:
        raise ValueError("缺少逐家竞品结构化结果，无法汇总")

    profiles = [item.profile for item in individual_results]
    matrix = _build_capability_matrix(project_input, project_overview, individual_results)
    current_summary = "无"
    if current_analysis is not None:
        current_summary = current_analysis.model_dump_json(
            include={
                "overview",
                "swot_strengths",
                "swot_weaknesses",
                "swot_opportunities",
                "swot_threats",
                "positioning_judgment",
            },
            indent=2,
        )

    client = llm_client or RealLLMClient()
    result = client.complete_json(
        _SYNTHESIS_PROMPT.format(
            company_name=project_input.company_name,
            industry=project_input.industry or "未提供",
            core_business=project_overview.core_business,
            product_service=project_overview.product_service_system,
            use_cases_and_value=project_overview.use_cases_and_value,
            competitive_landscape=industry_analysis.competitive_landscape,
            opportunities_and_barriers=industry_analysis.opportunities_and_barriers,
            opportunity_mapping_to_target=industry_analysis.opportunity_mapping_to_target,
            individual_results_json=_individual_results_json(individual_results),
            capability_matrix_json=str(matrix),
            current_summary=current_summary,
            feedback=feedback.strip() if feedback and feedback.strip() else "无",
        ),
        _CompetitorSynthesisLLM,
    )

    sources = _dedupe_sources([source for item in individual_results for source in item.meta.sources])
    meta = result.meta.to_meta(sources)
    meta.assumptions = _dedupe_strings([value for item in individual_results for value in item.meta.assumptions] + meta.assumptions)
    meta.missing_info = _dedupe_strings([value for item in individual_results for value in item.meta.missing_info] + meta.missing_info)
    meta.risk_flags = _dedupe_strings([value for item in individual_results for value in item.meta.risk_flags] + meta.risk_flags)

    analysis = CompetitorAnalysis(
        overview=result.overview,
        individual_results=individual_results,
        competitor_profiles=profiles,
        capability_matrix=matrix,
        swot_strengths=result.swot_strengths,
        swot_weaknesses=result.swot_weaknesses,
        swot_opportunities=result.swot_opportunities,
        swot_threats=result.swot_threats,
        positioning_judgment=result.positioning_judgment,
        meta=meta,
    )
    analysis.markdown = _render_markdown(project_input.company_name, analysis) + render_meta_section(meta)
    return analysis


def serialize_competitor_analysis(analysis: CompetitorAnalysis) -> str:
    return analysis.model_dump_json(indent=2)


def _build_capability_matrix(
    project_input: ProjectInput,
    project_overview: ProjectOverview,
    individual_results: list[SingleCompetitorAnalysis],
) -> list[dict[str, Any]]:
    target_values = {
        "产品能力": project_overview.product_service_system,
        "商业模式": project_overview.core_business,
        "客户与场景": project_overview.use_cases_and_value,
        "技术壁垒": f"基于现有产品/服务资料：{project_overview.product_service_system}",
        "商业化与融资进展": f"融资轮次：{project_input.funding_round or '未提供'}；融资金额：{project_input.funding_amount or '未提供'}",
    }
    rows: list[dict[str, Any]] = []
    for dimension in MATRIX_DIMENSIONS:
        row: dict[str, Any] = {"dimension": dimension, project_input.company_name: target_values[dimension]}
        for item in individual_results:
            row[item.profile.name] = item.matrix_values.get(dimension, "资料不足")
        rows.append(row)
    return rows


def _individual_results_json(results: list[SingleCompetitorAnalysis]) -> str:
    return "[" + ",\n".join(item.model_dump_json(indent=2) for item in results) + "]"


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_sources(values: list[Source]) -> list[Source]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[Source] = []
    for value in values:
        key = (value.title, value.url, value.provider)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _render_markdown(company_name: str, analysis: CompetitorAnalysis) -> str:
    profiles = "\n\n".join(
        f"### {p.name}\n- 能力概述：{p.capability_summary}\n- 商业模式：{p.business_model}\n- 客户/场景：{p.customer_and_scene}\n"
        f"- 技术壁垒：{p.tech_barrier}\n- 融资进展：{p.funding_and_progress}\n"
        f"- 优势：{', '.join(p.strengths) or '无'}\n- 劣势：{', '.join(p.weaknesses) or '无'}"
        for p in analysis.competitor_profiles
    )
    return f"""# {company_name} 竞品矩阵分析

## 1. 竞争格局总览
{analysis.overview}

## 2. 主要竞争对手概览
{profiles}

## 3. 产品能力对比矩阵
{_render_capability_matrix(analysis.capability_matrix)}

## 4. SWOT 综合分析
- 优势（S）：{', '.join(analysis.swot_strengths) or '无'}
- 劣势（W）：{', '.join(analysis.swot_weaknesses) or '无'}
- 机会（O）：{', '.join(analysis.swot_opportunities) or '无'}
- 威胁（T）：{', '.join(analysis.swot_threats) or '无'}

## 5. 目标公司定位判断
{analysis.positioning_judgment}
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
