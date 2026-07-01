from __future__ import annotations

from src.llm_config import LLMCallConfig
from src.pipeline import BPPipeline


def test_overview_feedback_regeneration_reuses_node_llm_config(fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    project_input = pipeline.run_start_step(company_name="示例科技")
    config = LLMCallConfig(
        model="qwen3.6-flash",
        prompt="OVERRIDE {company_name} {feedback_section}",
    )
    fake_llm_client.prompts.clear()
    fake_llm_client.contexts.clear()

    pipeline.run_project_overview_step(project_input, llm_config=config)
    pipeline.run_project_overview_step(project_input, feedback="复核工商信息", llm_config=config)

    assert fake_llm_client.contexts == [
        {"model": "qwen3.6-flash", "provider": "dashscope"},
        {"model": "qwen3.6-flash", "provider": "dashscope"},
    ]
    assert "复核工商信息" in fake_llm_client.prompts[1]


def test_competitor_resynthesis_uses_only_synthesis_config(fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )
    fake_llm_client.prompts.clear()
    fake_llm_client.contexts.clear()

    pipeline.run_competitor_synthesis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        competitor_analysis=report,
        feedback="统一比较口径",
        llm_config=LLMCallConfig(
            model="qwen3.5-plus",
            prompt="RESYNTH {company_name} {feedback} {individual_results_json}",
        ),
    )

    assert fake_llm_client.prompts[0].startswith("RESYNTH")
    assert fake_llm_client.contexts == [{"model": "qwen3.5-plus", "provider": "dashscope"}]
