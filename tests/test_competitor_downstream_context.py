from __future__ import annotations

from src.pipeline import BPPipeline, BPPipelineConfig
from src.schema import (
    CompetitorAnalysis,
    CompetitorProfile,
    NodeMeta,
    SingleCompetitorAnalysis,
    Source,
)


def test_business_valuation_and_final_prompts_receive_complete_competitor_analysis(
    tmp_path, fake_llm_client, fake_search_client
) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, _ = pipeline.run_intake_through_discovery(
        company_name="示例科技", industry="人工智能", project_description="企业级 AI 软件"
    )
    profile = CompetitorProfile(
        name="竞品完整标记",
        capability_summary="画像标记 PROFILE_FULL_MARKER",
        business_model="订阅",
        customer_and_scene="企业客户",
        tech_barrier="专利",
        funding_and_progress="A轮",
    )
    competitor_analysis = CompetitorAnalysis(
        overview="总览标记 OVERVIEW_FULL_MARKER",
        individual_results=[
            SingleCompetitorAnalysis(
                candidate_id="c1",
                profile=profile,
                matrix_values={"产品能力": "单体矩阵标记 INDIVIDUAL_MATRIX_MARKER"},
                meta=NodeMeta(assumptions=["单体假设 INDIVIDUAL_META_MARKER"]),
            )
        ],
        competitor_profiles=[profile],
        capability_matrix=[{"dimension": "产品能力", "竞品完整标记": "矩阵标记 MATRIX_FULL_MARKER"}],
        swot_strengths=["优势标记 SWOT_FULL_MARKER"],
        positioning_judgment="定位标记 POSITION_FULL_MARKER",
        markdown="# 报告\n\n正文标记 MARKDOWN_FULL_MARKER",
        meta=NodeMeta(
            sources=[Source(title="来源标记 SOURCE_FULL_MARKER")],
            assumptions=["假设标记 ASSUMPTION_FULL_MARKER"],
            missing_info=["缺口标记 MISSING_FULL_MARKER"],
            risk_flags=["风险标记 RISK_FULL_MARKER"],
        ),
    )
    fake_llm_client.calls.clear()
    fake_llm_client.prompts.clear()

    pipeline.run_after_competitor_analysis(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        competitor_analysis=competitor_analysis,
    )

    prompts = dict(zip(fake_llm_client.calls, fake_llm_client.prompts))
    required_markers = [
        "OVERVIEW_FULL_MARKER",
        "PROFILE_FULL_MARKER",
        "INDIVIDUAL_MATRIX_MARKER",
        "MATRIX_FULL_MARKER",
        "SWOT_FULL_MARKER",
        "POSITION_FULL_MARKER",
        "MARKDOWN_FULL_MARKER",
        "SOURCE_FULL_MARKER",
        "ASSUMPTION_FULL_MARKER",
        "MISSING_FULL_MARKER",
        "RISK_FULL_MARKER",
    ]
    for schema_name in ("_BusinessLLM", "_ValuationLLM", "_FinalReportLLM"):
        for marker in required_markers:
            assert marker in prompts[schema_name]
