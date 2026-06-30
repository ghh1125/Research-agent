from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from src.llm import RealLLMClient
from src.nodes.competitor_analysis import run_competitor_analysis, synthesize_competitor_analysis
from src.nodes.competitor_discovery import run_competitor_discovery
from src.nodes.due_diligence import (
    build_due_diligence_bundle,
    run_business_due_diligence,
    run_financial_due_diligence,
    run_legal_due_diligence,
    run_team_due_diligence,
    run_tech_ip_due_diligence,
    summarize_business,
    summarize_financial,
    summarize_team,
)
from src.nodes.final_report import run_final_report
from src.nodes.industry_analysis import run_industry_analysis
from src.nodes.project_overview import run_project_overview
from src.nodes.start import run_start
from src.nodes.valuation import run_valuation_analysis
from src.report import write_node_report
from src.schema import (
    CompetitorAnalysis,
    CompetitorDiscovery,
    DueDiligenceBundle,
    FinalInvestmentReport,
    IndustryAnalysis,
    NodeMeta,
    PipelineState,
    ProjectInput,
    ProjectOverview,
    ValuationAnalysis,
)
from src.search import RealSearchClient

CompetitorSelector = Callable[[CompetitorDiscovery], list[str]]
# Given the freshly generated report, return None to approve/continue, or a feedback string to
# regenerate that same step with the feedback folded into the prompt.
ReviewCallback = Callable[[Any], "str | None"]


def select_all_competitors(discovery: CompetitorDiscovery) -> list[str]:
    return [c.id for c in discovery.candidates]


def empty_competitor_analysis() -> CompetitorAnalysis:
    """Used when the user confirms zero competitors at the 竞品发现 human-in-the-loop step."""

    return CompetitorAnalysis(
        overview="未选择任何竞品，跳过竞品矩阵分析。",
        positioning_judgment="无竞品对比数据，建议至少选择 1 个竞品以获得定位判断。",
        markdown="# 竞品矩阵分析\n\n未选择任何竞品，跳过分析。\n",
        meta=NodeMeta(confidence="low", missing_info=["未选择竞品，无竞品对比数据"]),
    )


class BPPipelineConfig(BaseModel):
    output_dir: Path = Path("data/bp_reports")
    search_max_results: int = 5


class BPPipeline:
    """Orchestrates the 7-node VC due-diligence pipeline end to end.

    Exposes stage methods for intake/discovery, competitor analysis, and post-analysis due
    diligence so a web UI can pause at both human interaction boundaries without duplicating
    node wiring. `run_after_competitor_selection()` and `run()` remain single-shot convenience
    wrappers for CLI and other non-interactive callers.
    """

    NODE_ORDER = [
        "开始",
        "项目基本概况",
        "行业深度分析",
        "竞品发现",
        "竞品矩阵分析",
        "深度尽调",
        "估值分析",
        "综合研判与报告输出",
    ]

    def __init__(
        self,
        config: BPPipelineConfig | dict[str, Any] | None = None,
        *,
        llm_client: Any | None = None,
        search_client: Any | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config if isinstance(config, BPPipelineConfig) else BPPipelineConfig.model_validate(config or {})
        self.progress_callback = progress_callback
        self.llm_client = llm_client or RealLLMClient(progress_callback=self._emit)
        self.search_client = search_client or RealSearchClient()

    def run_start_step(
        self,
        *,
        company_name: str,
        website: str | None = None,
        bp_files: list[str] | None = None,
        funding_round: str | None = None,
        funding_amount: str | None = None,
        industry: str | None = None,
        project_description: str | None = None,
    ) -> ProjectInput:
        """Node 0 — 开始. No review checkpoint after this one (it's just intake normalization)."""

        self._emit("[node 0/7] 开始 start")
        project_input = run_start(
            company_name=company_name,
            website=website,
            bp_files=bp_files,
            funding_round=funding_round,
            funding_amount=funding_amount,
            industry=industry,
            project_description=project_description,
            llm_client=self.llm_client,
        )
        self._emit("[node 0/7] 开始 done")
        return project_input

    def run_project_overview_step(self, project_input: ProjectInput, *, feedback: str | None = None) -> ProjectOverview:
        """Node 1 — 项目基本概况. Pass `feedback` to regenerate after a human review rejects the first pass."""

        self._emit("[node 1/7] 项目基本概况 start" + (" (按反馈重新生成)" if feedback else ""))
        overview = run_project_overview(
            project_input, llm_client=self.llm_client, search_client=self.search_client, search_max_results=self.config.search_max_results, feedback=feedback
        )
        self._emit("[node 1/7] 项目基本概况 done")
        return overview

    def run_project_overview_with_review(
        self, project_input: ProjectInput, *, review_callback: ReviewCallback | None = None
    ) -> ProjectOverview:
        """CLI-style convenience: loops `run_project_overview_step` until `review_callback` approves
        (returns None) or there is no callback at all (auto-approve, used by non-interactive callers)."""

        feedback: str | None = None
        while True:
            overview = self.run_project_overview_step(project_input, feedback=feedback)
            if review_callback is None:
                return overview
            feedback = review_callback(overview)
            if feedback is None:
                return overview

    def run_industry_analysis_step(
        self, project_input: ProjectInput, project_overview: ProjectOverview, *, feedback: str | None = None
    ) -> IndustryAnalysis:
        """Node 2 — 行业深度分析. Pass `feedback` to regenerate after a human review rejects the first pass."""

        self._emit("[node 2/7] 行业深度分析 start" + (" (按反馈重新生成)" if feedback else ""))
        analysis = run_industry_analysis(
            project_input,
            project_overview,
            llm_client=self.llm_client,
            search_client=self.search_client,
            search_max_results=self.config.search_max_results,
            feedback=feedback,
        )
        self._emit("[node 2/7] 行业深度分析 done")
        return analysis

    def run_industry_analysis_with_review(
        self, project_input: ProjectInput, project_overview: ProjectOverview, *, review_callback: ReviewCallback | None = None
    ) -> IndustryAnalysis:
        """CLI-style convenience: loops `run_industry_analysis_step` until approved (see
        `run_project_overview_with_review` for the same pattern)."""

        feedback: str | None = None
        while True:
            analysis = self.run_industry_analysis_step(project_input, project_overview, feedback=feedback)
            if review_callback is None:
                return analysis
            feedback = review_callback(analysis)
            if feedback is None:
                return analysis

    def run_competitor_discovery_step(
        self, project_input: ProjectInput, project_overview: ProjectOverview, industry_analysis: IndustryAnalysis
    ) -> CompetitorDiscovery:
        """Node 3.1 — 竞品发现 (longlist, before the 竞品确认 human-in-the-loop point)."""

        self._emit("[node 3.1/7] 竞品发现 start")
        discovery = run_competitor_discovery(
            project_input, project_overview, industry_analysis, llm_client=self.llm_client, search_client=self.search_client, search_max_results=self.config.search_max_results
        )
        self._emit(f"[node 3.1/7] 竞品发现 done candidates={len(discovery.candidates)}")
        return discovery

    def run_intake_through_discovery(
        self,
        *,
        company_name: str,
        website: str | None = None,
        bp_files: list[str] | None = None,
        funding_round: str | None = None,
        funding_amount: str | None = None,
        industry: str | None = None,
        project_description: str | None = None,
        overview_review_callback: ReviewCallback | None = None,
        industry_review_callback: ReviewCallback | None = None,
    ) -> tuple[ProjectInput, ProjectOverview, IndustryAnalysis, CompetitorDiscovery]:
        """Convenience wrapper chaining nodes 0, 1, 2, 3.1 with optional review loops on 1 and 2.
        Pass review_callback=None (the default) to auto-approve and run straight through."""

        project_input = self.run_start_step(
            company_name=company_name,
            website=website,
            bp_files=bp_files,
            funding_round=funding_round,
            funding_amount=funding_amount,
            industry=industry,
            project_description=project_description,
        )
        project_overview = self.run_project_overview_with_review(project_input, review_callback=overview_review_callback)
        industry_analysis = self.run_industry_analysis_with_review(project_input, project_overview, review_callback=industry_review_callback)
        discovery = self.run_competitor_discovery_step(project_input, project_overview, industry_analysis)
        return project_input, project_overview, industry_analysis, discovery

    def run_after_competitor_selection(
        self,
        *,
        project_input: ProjectInput,
        project_overview: ProjectOverview,
        industry_analysis: IndustryAnalysis,
        discovery: CompetitorDiscovery,
        selected_ids: list[str],
        team_files: list[str] | None = None,
        financial_files: list[str] | None = None,
        business_plan_files: list[str] | None = None,
        tech_ip_files: list[str] | None = None,
        legal_files: list[str] | None = None,
    ) -> tuple[CompetitorAnalysis, DueDiligenceBundle, ValuationAnalysis, FinalInvestmentReport]:
        """Compatibility wrapper that runs nodes 3.2-6 without pausing."""

        competitor_analysis = self.run_competitor_analysis_step(
            project_input=project_input,
            project_overview=project_overview,
            industry_analysis=industry_analysis,
            discovery=discovery,
            selected_ids=selected_ids,
        )
        due_diligence, valuation_analysis, final_report = self.run_after_competitor_analysis(
            project_input=project_input,
            project_overview=project_overview,
            industry_analysis=industry_analysis,
            competitor_analysis=competitor_analysis,
            team_files=team_files,
            financial_files=financial_files,
            business_plan_files=business_plan_files,
            tech_ip_files=tech_ip_files,
            legal_files=legal_files,
        )
        return competitor_analysis, due_diligence, valuation_analysis, final_report

    def run_competitor_analysis_step(
        self,
        *,
        project_input: ProjectInput,
        project_overview: ProjectOverview,
        industry_analysis: IndustryAnalysis,
        discovery: CompetitorDiscovery,
        selected_ids: list[str],
        feedback: str | None = None,
        current_analysis: CompetitorAnalysis | None = None,
    ) -> CompetitorAnalysis:
        """Node 3.2 only: generate the report for the user's confirmed shortlist."""

        discovery.selected_ids = selected_ids
        if selected_ids:
            self._emit("[node 3.2/7] 竞品矩阵分析 start")
            competitor_analysis = run_competitor_analysis(
                project_input,
                project_overview,
                industry_analysis,
                discovery,
                llm_client=self.llm_client,
                search_client=self.search_client,
                search_max_results=self.config.search_max_results,
                feedback=feedback,
                current_analysis=current_analysis,
            )
            self._emit("[node 3.2/7] 竞品矩阵分析 done")
            return competitor_analysis
        return empty_competitor_analysis()

    def run_competitor_synthesis_step(
        self,
        *,
        project_input: ProjectInput,
        project_overview: ProjectOverview,
        industry_analysis: IndustryAnalysis,
        competitor_analysis: CompetitorAnalysis,
        feedback: str,
    ) -> CompetitorAnalysis:
        """Re-synthesize the final competitor report without searching or re-running individual analyses."""

        if not feedback.strip():
            raise ValueError("按反馈重新汇总前必须填写具体审核意见")
        self._emit("[node 3.2/7] 竞品矩阵重新汇总 start")
        result = synthesize_competitor_analysis(
            project_input,
            project_overview,
            industry_analysis,
            competitor_analysis.individual_results,
            llm_client=self.llm_client,
            feedback=feedback.strip(),
            current_analysis=competitor_analysis,
        )
        self._emit("[node 3.2/7] 竞品矩阵重新汇总 done")
        return result

    def run_after_competitor_analysis(
        self,
        *,
        project_input: ProjectInput,
        project_overview: ProjectOverview,
        industry_analysis: IndustryAnalysis,
        competitor_analysis: CompetitorAnalysis,
        team_files: list[str] | None = None,
        financial_files: list[str] | None = None,
        business_plan_files: list[str] | None = None,
        tech_ip_files: list[str] | None = None,
        legal_files: list[str] | None = None,
    ) -> tuple[DueDiligenceBundle, ValuationAnalysis, FinalInvestmentReport]:
        """Run nodes 4-6 using an already generated competitor report."""

        self._emit("[node 4/7] 深度尽调 start")
        team = run_team_due_diligence(
            project_input, project_overview, industry_analysis, team_files=team_files, llm_client=self.llm_client, search_client=self.search_client
        )
        business = run_business_due_diligence(
            project_input,
            project_overview,
            industry_analysis,
            competitor_analysis,
            business_plan_files=business_plan_files,
            llm_client=self.llm_client,
            peer_findings=summarize_team(team),
        )
        financial = run_financial_due_diligence(project_input, project_overview, industry_analysis, financial_files=financial_files, llm_client=self.llm_client)
        peer_for_legal = "\n".join([summarize_team(team), summarize_business(business), summarize_financial(financial)])
        legal = run_legal_due_diligence(
            project_input, project_overview, industry_analysis, legal_files=legal_files, llm_client=self.llm_client, peer_findings=peer_for_legal
        )
        tech_ip = run_tech_ip_due_diligence(
            project_input, project_overview, industry_analysis, tech_ip_files=tech_ip_files, llm_client=self.llm_client, peer_findings=summarize_team(team)
        )
        due_diligence = build_due_diligence_bundle(team, business, financial, tech_ip, legal)
        self._emit(f"[node 4/7] 深度尽调 done risk_items={len(due_diligence.risk_register)}")

        self._emit("[node 5/7] 估值分析 start")
        valuation_analysis = run_valuation_analysis(
            project_input,
            project_overview,
            industry_analysis,
            competitor_analysis,
            due_diligence,
            llm_client=self.llm_client,
            search_client=self.search_client,
            search_max_results=self.config.search_max_results,
        )
        self._emit("[node 5/7] 估值分析 done")

        self._emit("[node 6/7] 综合研判与报告输出 start")
        final_report = run_final_report(project_input, project_overview, industry_analysis, competitor_analysis, due_diligence, valuation_analysis, llm_client=self.llm_client)
        self._emit("[node 6/7] 综合研判与报告输出 done")

        return due_diligence, valuation_analysis, final_report

    def run(
        self,
        *,
        company_name: str,
        website: str | None = None,
        bp_files: list[str] | None = None,
        funding_round: str | None = None,
        funding_amount: str | None = None,
        industry: str | None = None,
        project_description: str | None = None,
        team_files: list[str] | None = None,
        financial_files: list[str] | None = None,
        business_plan_files: list[str] | None = None,
        tech_ip_files: list[str] | None = None,
        legal_files: list[str] | None = None,
        competitor_selector: CompetitorSelector | None = None,
        overview_review_callback: ReviewCallback | None = None,
        industry_review_callback: ReviewCallback | None = None,
    ) -> PipelineState:
        """Single-shot convenience wrapper used by the CLI: runs both phases back to back and writes
        every node's report to self.config.output_dir. overview_review_callback/industry_review_callback
        default to None (auto-approve, no pause) so non-interactive callers are unaffected."""

        out = self.config.output_dir
        competitor_selector = competitor_selector or select_all_competitors

        project_input, project_overview, industry_analysis, discovery = self.run_intake_through_discovery(
            company_name=company_name,
            website=website,
            bp_files=bp_files,
            funding_round=funding_round,
            funding_amount=funding_amount,
            industry=industry,
            project_description=project_description,
            overview_review_callback=overview_review_callback,
            industry_review_callback=industry_review_callback,
        )
        self._write(out / "00_start", "project_input", project_input.model_dump_json(indent=2))
        write_node_report(project_overview.markdown, out / "01_project_overview", "report")
        write_node_report(industry_analysis.markdown, out / "02_industry_analysis", "report")

        selected_ids = competitor_selector(discovery)
        self._write(out / "03_competitor_discovery", "candidates", discovery.model_dump_json(indent=2))

        competitor_analysis, due_diligence, valuation_analysis, final_report = self.run_after_competitor_selection(
            project_input=project_input,
            project_overview=project_overview,
            industry_analysis=industry_analysis,
            discovery=discovery,
            selected_ids=selected_ids,
            team_files=team_files,
            financial_files=financial_files,
            business_plan_files=business_plan_files,
            tech_ip_files=tech_ip_files,
            legal_files=legal_files,
        )
        write_node_report(competitor_analysis.markdown, out / "03_competitor_analysis", "report")
        for name, report in (
            ("team", due_diligence.team),
            ("business", due_diligence.business),
            ("financial", due_diligence.financial),
            ("tech_ip", due_diligence.tech_ip),
            ("legal", due_diligence.legal),
        ):
            write_node_report(report.markdown, out / "04_due_diligence", name)
        write_node_report(due_diligence.markdown, out / "04_due_diligence", "summary")
        write_node_report(valuation_analysis.markdown, out / "05_valuation", "report")
        write_node_report(final_report.markdown, out / "06_final_report", "report")

        return PipelineState(
            project_input=project_input,
            project_overview=project_overview,
            industry_analysis=industry_analysis,
            competitor_discovery=discovery,
            competitor_analysis=competitor_analysis,
            due_diligence=due_diligence,
            valuation_analysis=valuation_analysis,
            final_report=final_report,
        )

    def _write(self, out_dir: Path, name: str, content: str) -> None:
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text(content, encoding="utf-8")

    def _emit(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


__all__ = ["BPPipeline", "BPPipelineConfig", "select_all_competitors", "empty_competitor_analysis", "CompetitorSelector", "ReviewCallback"]
