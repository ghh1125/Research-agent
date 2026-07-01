from __future__ import annotations

from src.nodes.due_diligence import build_due_diligence_bundle, run_team_due_diligence
from src.nodes.final_report import run_final_report
from src.nodes.valuation import run_valuation_analysis
from src.pipeline import BPPipeline


def prepare_core_reports(fake_llm_client, fake_search_client):
    pipeline = BPPipeline(llm_client=fake_llm_client, search_client=fake_search_client)
    project_input, overview, industry, discovery = pipeline.run_intake_through_discovery(
        company_name="示例科技",
        industry="人工智能",
        project_description="企业级 AI 软件",
    )
    competitor = pipeline.run_competitor_analysis_step(
        project_input=project_input,
        project_overview=overview,
        industry_analysis=industry,
        discovery=discovery,
        selected_ids=[discovery.candidates[0].id],
    )
    return project_input, overview, industry, competitor


def test_bundle_accepts_only_team_report(fake_llm_client, fake_search_client) -> None:
    project_input, overview, industry, _ = prepare_core_reports(fake_llm_client, fake_search_client)
    team = run_team_due_diligence(
        project_input,
        overview,
        industry,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )

    bundle = build_due_diligence_bundle(team=team)

    assert bundle.completed_categories == ["团队"]
    assert bundle.missing_categories == ["业务", "财务", "技术与知识产权", "法律"]
    assert "未执行专项尽调：业务、财务、技术与知识产权、法律" in bundle.markdown
    assert bundle.business is None


def test_empty_bundle_is_valid_and_lists_all_missing_categories() -> None:
    bundle = build_due_diligence_bundle()

    assert bundle.completed_categories == []
    assert bundle.missing_categories == ["团队", "业务", "财务", "技术与知识产权", "法律"]
    assert bundle.risk_register == []


def test_partial_bundle_still_generates_valuation_and_final_report(fake_llm_client, fake_search_client) -> None:
    project_input, overview, industry, competitor = prepare_core_reports(fake_llm_client, fake_search_client)
    team = run_team_due_diligence(
        project_input,
        overview,
        industry,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    bundle = build_due_diligence_bundle(team=team)
    fake_llm_client.prompts.clear()

    valuation = run_valuation_analysis(
        project_input,
        overview,
        industry,
        competitor,
        bundle,
        llm_client=fake_llm_client,
        search_client=fake_search_client,
    )
    final = run_final_report(
        project_input,
        overview,
        industry,
        competitor,
        bundle,
        valuation,
        llm_client=fake_llm_client,
    )

    assert "未执行专项尽调：业务、财务、技术与知识产权、法律" in fake_llm_client.prompts[0]
    assert "未执行专项尽调：业务、财务、技术与知识产权、法律" in fake_llm_client.prompts[1]
    assert set(final.missing_info) >= {
        "未执行业务尽调",
        "未执行财务尽调",
        "未执行技术与知识产权尽调",
        "未执行法律尽调",
    }
