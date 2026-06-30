from __future__ import annotations

from pathlib import Path

from src.pipeline import BPPipeline, BPPipelineConfig, select_all_competitors
from src.schema import CompetitorCandidate, CompetitorDiscovery


def test_select_all_competitors_returns_every_id() -> None:
    discovery = CompetitorDiscovery(
        candidates=[
            CompetitorCandidate(id="c1", name="A", product_or_service="x", relationship="直接竞品", reason="r"),
            CompetitorCandidate(id="c2", name="B", product_or_service="y", relationship="潜在竞品", reason="r"),
        ]
    )
    assert select_all_competitors(discovery) == ["c1", "c2"]


def test_competitor_analysis_step_does_not_start_due_diligence(tmp_path: Path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    fake_llm_client.calls.clear()

    report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )

    assert report.markdown
    assert fake_llm_client.calls == ["_SingleCompetitorAnalysisLLM", "_CompetitorSynthesisLLM"]


def test_after_competitor_analysis_does_not_regenerate_competitor_report(
    tmp_path: Path, fake_llm_client, fake_search_client
) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    competitor_report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )
    fake_llm_client.calls.clear()

    due_diligence, valuation, final_report = pipeline.run_after_competitor_analysis(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        competitor_analysis=competitor_report,
    )

    assert due_diligence.markdown
    assert valuation.markdown
    assert final_report.markdown
    assert "_CompetitorAnalysisLLM" not in fake_llm_client.calls


def test_feedback_resynthesis_reuses_individual_results_without_search(tmp_path: Path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技", industry="人工智能", project_description="企业级 AI 软件"
    )
    report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )
    fake_llm_client.calls.clear()
    fake_llm_client.prompts.clear()
    fake_search_client.queries.clear()

    revised = pipeline.run_competitor_synthesis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        competitor_analysis=report,
        feedback="SWOT 威胁需要补充价格竞争影响",
    )

    assert revised.individual_results == report.individual_results
    assert fake_llm_client.calls == ["_CompetitorSynthesisLLM"]
    assert fake_search_client.queries == []
    assert "SWOT 威胁需要补充价格竞争影响" in fake_llm_client.prompts[0]


def test_full_reanalysis_uses_feedback_and_current_individual_result(tmp_path: Path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技", industry="人工智能", project_description="企业级 AI 软件"
    )
    selected_ids = [discovery.candidates[0].id]
    report = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=selected_ids,
    )
    report.individual_results[0].profile.capability_summary = "CURRENT_RESULT_MARKER"
    fake_llm_client.calls.clear()
    fake_llm_client.prompts.clear()
    fake_search_client.queries.clear()

    pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=selected_ids,
        feedback="重点复核价格竞争",
        current_analysis=report,
    )

    assert "CURRENT_RESULT_MARKER" in fake_llm_client.prompts[0]
    assert "重点复核价格竞争" in fake_llm_client.prompts[0]
    assert any("重点复核价格竞争" in query for query in fake_search_client.queries)


def test_full_pipeline_runs_all_seven_nodes(tmp_path: Path, fake_llm_client, fake_search_client) -> None:
    pipeline = BPPipeline(
        config=BPPipelineConfig(output_dir=tmp_path / "reports", search_max_results=1),
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    state = pipeline.run(
        company_name="示例科技",
        website="https://example.com",
        funding_round="A轮",
        funding_amount="1000万元",
        industry="人工智能",
        project_description="一句话项目描述",
        competitor_selector=select_all_competitors,
    )

    assert state.project_input is not None
    assert state.project_overview is not None
    assert state.industry_analysis is not None
    assert state.competitor_discovery is not None
    assert state.competitor_analysis is not None
    assert state.due_diligence is not None
    assert state.valuation_analysis is not None
    assert state.final_report is not None

    assert (tmp_path / "reports" / "01_project_overview" / "report.md").exists()
    assert (tmp_path / "reports" / "06_final_report" / "report.md").exists()
    assert (tmp_path / "reports" / "04_due_diligence" / "team.md").exists()
    assert (tmp_path / "reports" / "04_due_diligence" / "financial.md").exists()

    assert "项目投研报告" in state.final_report.markdown
    assert "退出路径与收益测算" in state.final_report.markdown
    assert state.due_diligence.risk_register, "risk register should aggregate at least the team risk item"
