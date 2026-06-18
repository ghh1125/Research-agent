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
