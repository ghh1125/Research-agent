from __future__ import annotations

from src.llm_config import LLMCallConfig
from src.nodes.competitor_analysis import run_competitor_analysis
from src.nodes.due_diligence.team import run_team_due_diligence
from src.nodes.project_overview import run_project_overview
from src.nodes.start import run_start
from src.pipeline import BPPipeline
from src.schema import ProjectInput


def test_start_and_overview_accept_prompt_and_model_overrides(fake_llm_client, fake_search_client) -> None:
    project_input = run_start(
        company_name="示例科技",
        industry="人工智能",
        llm_client=fake_llm_client,
        llm_config=LLMCallConfig(
            model="qwen3.6-flash",
            prompt="START_MARKER {raw_input} {bp_text}",
        ),
    )

    run_project_overview(
        project_input,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
        llm_config=LLMCallConfig(
            model="qwen3.5-plus",
            prompt="OVERVIEW_MARKER {company_name} {feedback_section}",
        ),
    )

    assert fake_llm_client.prompts[0].startswith("START_MARKER")
    assert fake_llm_client.contexts[0] == {"model": "qwen3.6-flash", "provider": "dashscope"}
    assert fake_llm_client.prompts[1].startswith("OVERVIEW_MARKER")
    assert fake_llm_client.contexts[1] == {"model": "qwen3.5-plus", "provider": "dashscope"}


def test_competitor_single_and_synthesis_use_independent_configs(fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    fake_llm_client.prompts.clear()
    fake_llm_client.contexts.clear()

    run_competitor_analysis(
        project_input,
        overview,
        industry,
        discovery,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
        single_llm_config=LLMCallConfig(
            model="qwen3.6-flash",
            prompt="SINGLE_MARKER {candidate_name} {evidence_text}",
        ),
        synthesis_llm_config=LLMCallConfig(
            model="qwen3.7-plus",
            prompt="SYNTHESIS_MARKER {company_name} {individual_results_json}",
        ),
    )

    assert fake_llm_client.prompts[0].startswith("SINGLE_MARKER")
    assert fake_llm_client.contexts[0] == {"model": "qwen3.6-flash", "provider": "dashscope"}
    assert fake_llm_client.prompts[1].startswith("SYNTHESIS_MARKER")
    assert fake_llm_client.contexts[1] == {"model": "qwen3.7-plus", "provider": "dashscope"}


def test_due_diligence_specialist_accepts_its_own_config(fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    project_input, overview, industry, _ = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    fake_llm_client.prompts.clear()
    fake_llm_client.contexts.clear()

    run_team_due_diligence(
        project_input,
        overview,
        industry,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
        llm_config=LLMCallConfig(
            model="qwen-plus",
            prompt="TEAM_MARKER {company_name} {search_text}",
        ),
    )

    assert fake_llm_client.prompts[0].startswith("TEAM_MARKER")
    assert "fake result:" in fake_llm_client.prompts[0]
    assert fake_llm_client.contexts == [{"model": "qwen-plus", "provider": "dashscope"}]
