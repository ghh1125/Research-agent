from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from research_flow.analysis.debate import run_investment_debate
from research_flow.analysis.tool_loop import build_analyst_reports_with_tool_loop
from research_flow.continuity.memory import ResearchMemoryLog
from research_flow.continuity.reporting import build_memory_entry, build_report, write_result_state
from research_flow.continuity.watchlist import build_tracking_alerts
from research_flow.decision.synthesis import (
    build_manager_decision,
    build_manager_decision_with_llm,
    build_portfolio_decision,
    build_portfolio_decision_with_llm,
    build_risk_review,
    build_risk_review_with_debate,
    build_risk_review_with_llm,
    build_scenario_analysis,
    build_scenario_analysis_with_llm,
)
from research_flow.evidence.data_registry import DataToolRegistry
from research_flow.evidence.knowledge_store import LocalKnowledgeStore
from research_flow.evidence.search import RealSearchClient
from research_flow.llm import RealLLMClient
from research_flow.schema import (
    AnalystReport,
    DebateCase,
    DebateTurn,
    EvidenceBundle,
    ManagerDecision,
    PortfolioDecision,
    ResearchGraphConfig,
    ResearchMemoryEntry,
    ResearchReport,
    ResearchResult,
    RiskReview,
    ScenarioAnalysis,
    StageTrace,
)
from research_flow.understanding.planner import build_research_plan, build_research_plan_with_llm
from research_flow.understanding.task_parser import parse_task, parse_task_with_llm


class ResearchGraph:
    """Five-layer investment research workflow.

    One normalized entry point receives a user sentence and runs the whole
    research chain through task planning, evidence, analysis, decision, and
    continuity layers.
    """

    def __init__(
        self,
        config: ResearchGraphConfig | dict[str, Any] | None = None,
        *,
        llm_client: Any | None = None,
        search_client: Any | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config if isinstance(config, ResearchGraphConfig) else ResearchGraphConfig.model_validate(config or {})
        self.progress_callback = progress_callback
        self.llm_client = llm_client or (RealLLMClient(progress_callback=self._emit) if self.config.enable_llm else None)
        if llm_client is not None and hasattr(llm_client, "progress_callback") and getattr(llm_client, "progress_callback", None) is None:
            setattr(llm_client, "progress_callback", self._emit)
        self.search_client = search_client or RealSearchClient()
        self.memory_log = ResearchMemoryLog(self.config.memory_path)
        self.knowledge_store = LocalKnowledgeStore(self.config.knowledge_dir)
        self.data_registry = DataToolRegistry(
            self.knowledge_store,
            search_client=self.search_client,
            llm_client=self.llm_client,
            config=self.config,
            progress_callback=self._emit,
        )
        self._emit(f"[runtime] LLM {self._llm_runtime_summary()}")
        self._emit(f"[runtime] Search {self._search_runtime_summary()}")

    def propagate(self, query: str, **task_options: Any) -> ResearchResult:
        trace: list[StageTrace] = []
        memory_context: str = ""

        self._emit("[step 1/5] 任务理解与研究规划 start")
        self._emit("  - parsing ResearchTask")
        task = self._parse_task(query, task_options)
        self._emit(
            f"  - task type={task.question_type} symbols={','.join(task.symbols) or '-'} "
            f"market={task.market} horizon={task.horizon} risk={task.risk_preference}"
        )
        self._resolve_memory_if_possible(task)
        memory_context = self.memory_log.context_for(task.entity, limit=3) if task.entity else ""
        self._emit("  - generating ResearchPlan")
        plan = self._build_plan(task, memory_context=memory_context or None)
        self._emit(f"  - plan agents={','.join(plan.selected_agents)} data_sources={','.join(plan.data_sources)}")
        completed = self._checkpoint_completed(task.id)
        if self.config.resume_from_checkpoint and "报告输出、记忆复盘与持续跟踪" in completed:
            self._emit("[resume] final ResearchResult loaded from checkpoint")
            return ResearchResult.model_validate(completed["报告输出、记忆复盘与持续跟踪"])
        trace.append(StageTrace(name="任务理解与研究规划", summary=f"{task.question_type}; agents={','.join(plan.selected_agents)}"))
        self._checkpoint(task.id, "任务理解与研究规划", {"task": task.model_dump(), "plan": plan.model_dump()})
        self._emit("[step 1/5] 任务理解与研究规划 done")

        self._emit("[step 2/5] 数据检索与证据沉淀 start")
        if self.config.resume_from_checkpoint and "数据检索与证据沉淀" in completed:
            evidence_bundle = EvidenceBundle.model_validate(completed["数据检索与证据沉淀"])
            self._emit("  - loaded evidence bundle from checkpoint")
        else:
            evidence_bundle = self.data_registry.collect(task, plan)
        trace.append(StageTrace(name="数据检索与证据沉淀", summary=f"artifacts={len(evidence_bundle.artifacts)}, evidence={len(evidence_bundle.evidence)}"))
        self._checkpoint(task.id, "数据检索与证据沉淀", evidence_bundle.model_dump())
        self._emit(f"[step 2/5] 数据检索与证据沉淀 done artifacts={len(evidence_bundle.artifacts)} evidence={len(evidence_bundle.evidence)}")

        self._emit("[step 3/5] 多 Agent 专项分析 start")
        if self.config.resume_from_checkpoint and "多 Agent 专项分析" in completed:
            payload = completed["多 Agent 专项分析"]
            analyst_reports = [AnalystReport.model_validate(item) for item in payload["analyst_reports"]]
            bull_case = DebateCase.model_validate(payload["bull_case"])
            bear_case = DebateCase.model_validate(payload["bear_case"])
            investment_debate_history = [DebateTurn.model_validate(item) for item in payload.get("investment_debate_history", [])]
            self._emit("  - loaded analyst reports and debate from checkpoint")
        else:
            self._emit(f"  - running analysts={','.join(plan.selected_agents)}")
            loop_result = build_analyst_reports_with_tool_loop(
                task,
                plan,
                evidence_bundle,
                self.data_registry,
                self.llm_client,
                max_rounds=self.config.max_agent_tool_rounds,
                allow_fallback=self.config.allow_heuristic_fallback,
            )
            analyst_reports = loop_result.reports
            evidence_bundle = loop_result.bundle
            self._emit(f"  - analyst reports done count={len(analyst_reports)}")
            if self.llm_client is not None:
                self._emit(f"  - bull/bear debate start rounds={self.config.max_debate_rounds}")
                debate = run_investment_debate(
                    analyst_reports,
                    task,
                    evidence_bundle,
                    self.llm_client,
                    max_rounds=self.config.max_debate_rounds,
                    allow_fallback=self.config.allow_heuristic_fallback,
                )
                bull_case = debate.bull_case
                bear_case = debate.bear_case
                investment_debate_history = debate.history
                self._emit(f"  - bull/bear debate done turns={len(investment_debate_history)}")
            elif self.config.allow_heuristic_fallback:
                self._emit(f"  - heuristic bull/bear debate start rounds={self.config.max_debate_rounds}")
                debate = run_investment_debate(
                    analyst_reports,
                    task,
                    evidence_bundle,
                    None,
                    max_rounds=self.config.max_debate_rounds,
                    allow_fallback=True,
                )
                bull_case = debate.bull_case
                bear_case = debate.bear_case
                investment_debate_history = debate.history
                self._emit(f"  - heuristic bull/bear debate done turns={len(investment_debate_history)}")
            else:
                raise RuntimeError("LLM debate agents are required but no LLM client is configured")
        trace.append(StageTrace(name="多 Agent 专项分析", summary=f"reports={len(analyst_reports)}; debate=bull/bear"))
        self._checkpoint(
            task.id,
            "多 Agent 专项分析",
            {
                "analyst_reports": [report.model_dump() for report in analyst_reports],
                "bull_case": bull_case.model_dump(),
                "bear_case": bear_case.model_dump(),
                "investment_debate_history": [turn.model_dump() for turn in investment_debate_history],
            },
        )
        self._emit("[step 3/5] 多 Agent 专项分析 done")

        self._emit("[step 4/5] 投资判断、估值与风险裁决 start")
        if self.config.resume_from_checkpoint and "投资判断、估值与风险裁决" in completed:
            payload = completed["投资判断、估值与风险裁决"]
            manager_decision = ManagerDecision.model_validate(payload["manager_decision"])
            scenario_analysis = ScenarioAnalysis.model_validate(payload["scenario_analysis"])
            risk_review = RiskReview.model_validate(payload["risk_review"])
            portfolio_decision = PortfolioDecision.model_validate(payload["portfolio_decision"])
            self._emit("  - loaded decision package from checkpoint")
        elif self.llm_client is not None:
            self._emit("  - Research Manager decision")
            manager_decision = build_manager_decision_with_llm(task, analyst_reports, bull_case, bear_case, self.llm_client, memory_context=memory_context or None)
            self._emit("  - Valuation / Scenario analysis")
            scenario_analysis = build_scenario_analysis_with_llm(task, manager_decision, analyst_reports, self.llm_client, evidence_bundle)
            self._emit(f"  - Risk team debate rounds={self.config.max_risk_discuss_rounds}")
            risk_review = build_risk_review_with_debate(
                task,
                manager_decision,
                scenario_analysis,
                self.llm_client,
                max_rounds=self.config.max_risk_discuss_rounds,
                bundle=evidence_bundle,
            )
            self._emit("  - Portfolio Manager decision")
            portfolio_decision = build_portfolio_decision_with_llm(task, manager_decision, risk_review, scenario_analysis, self.llm_client)
        elif self.config.allow_heuristic_fallback:
            self._emit("  - heuristic decision package")
            manager_decision = build_manager_decision(task, analyst_reports, bull_case, bear_case)
            scenario_analysis = build_scenario_analysis(task, manager_decision, evidence_bundle)
            risk_review = build_risk_review(task, manager_decision, scenario_analysis, evidence_bundle)
            portfolio_decision = build_portfolio_decision(task, manager_decision, risk_review)
        else:
            raise RuntimeError("LLM decision agents are required but no LLM client is configured")
        trace.append(StageTrace(name="投资判断、估值与风险裁决", summary=f"{manager_decision.rating}; {portfolio_decision.action}"))
        self._checkpoint(
            task.id,
            "投资判断、估值与风险裁决",
            {
                "manager_decision": manager_decision.model_dump(),
                "scenario_analysis": scenario_analysis.model_dump(),
                "risk_review": risk_review.model_dump(),
                "portfolio_decision": portfolio_decision.model_dump(),
            },
        )
        self._emit(f"[step 4/5] 投资判断、估值与风险裁决 done rating={manager_decision.rating} action={portfolio_decision.action}")

        self._emit("[step 5/5] 报告输出、记忆复盘与持续跟踪 start")
        provisional = ResearchResult(
            task=task,
            plan=plan,
            evidence_bundle=evidence_bundle,
            analyst_reports=analyst_reports,
            bull_case=bull_case,
            bear_case=bear_case,
            investment_debate_history=investment_debate_history,
            manager_decision=manager_decision,
            scenario_analysis=scenario_analysis,
            risk_review=risk_review,
            portfolio_decision=portfolio_decision,
            report=ResearchReport(markdown=""),
            memory_entry=ResearchMemoryEntry(
                task_id=task.id,
                entity=task.entity,
                symbols=task.symbols,
                conclusion=portfolio_decision.action,
                rating=manager_decision.rating,
            ),
            tracking_alerts=[],
            stage_trace=trace,
        )
        self._emit("  - rendering institutional report")
        report = build_report(provisional)
        self._emit("  - writing memory entry and tracking alerts")
        memory_entry = build_memory_entry(provisional)
        alerts = build_tracking_alerts(manager_decision, portfolio_decision, entity=task.entity)
        final_trace = [
            *trace,
            StageTrace(name="报告输出、记忆复盘与持续跟踪", summary=f"report_sections={len(report.sections)}; alerts={len(alerts)}"),
        ]
        result = provisional.model_copy(
            update={
                "report": report,
                "memory_entry": memory_entry,
                "tracking_alerts": alerts,
                "stage_trace": final_trace,
            }
        )
        self.memory_log.append(memory_entry)
        self._emit(f"  - writing result state dir={self.config.results_dir}")
        write_result_state(result, self.config.results_dir)
        self._checkpoint(task.id, "报告输出、记忆复盘与持续跟踪", result.model_dump(mode="json"))
        if self.config.checkpoint_enabled and self.config.clear_checkpoint_on_success:
            self._checkpoint_path(task.id).unlink(missing_ok=True)
        self._emit(f"[step 5/5] 报告输出、记忆复盘与持续跟踪 done task_id={task.id}")
        return result

    def _parse_task(self, query: str, task_options: dict[str, Any]):
        options = {
            "model_profile": self.config.model_profile,
            "quick_model": self.config.quick_model,
            "deep_model": self.config.deep_model,
            "output_language": self.config.output_language,
            **task_options,
        }
        if self.llm_client is not None:
            return parse_task_with_llm(query, self.llm_client, **options)
        if self.config.allow_heuristic_fallback:
            return parse_task(query, **options)
        raise RuntimeError("LLM task parser is required but no LLM client is configured")

    def _build_plan(self, task, *, memory_context: str | None = None):
        if self.llm_client is not None:
            return build_research_plan_with_llm(task, self.llm_client, self.config.selected_agents, memory_context=memory_context)
        if self.config.allow_heuristic_fallback:
            return build_research_plan(task, self.config.selected_agents)
        raise RuntimeError("LLM research planner is required but no LLM client is configured")

    def _resolve_memory_if_possible(self, task) -> None:
        if not self.config.resolve_memory_on_start or not task.symbols:
            return
        self._emit(f"  - resolving prior memory for symbol={task.symbols[0]}")
        price = self._latest_price(task.symbols[0])
        if price is None:
            self._emit("  - prior memory skipped: latest price unavailable")
            return
        reflection = "自动复盘：已按最新价格更新历史判断表现，后续报告会把该结果作为研究记忆。"
        self.memory_log.resolve_pending(task.symbols[0], current_price=price, benchmark_return=0.0, reflection=reflection)
        self._emit("  - prior memory resolved")

    def _latest_price(self, symbol: str) -> float | None:
        try:
            import contextlib
            import io

            import yfinance as yf

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                history = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
            if history is None or history.empty:
                return None
            return float(history["Close"].dropna().iloc[-1])
        except Exception:
            return None

    def _checkpoint_path(self, task_id: str) -> Path:
        return Path(self.config.checkpoint_dir) / f"{task_id}.json"

    def _checkpoint_completed(self, task_id: str) -> dict[str, Any]:
        if not self.config.checkpoint_enabled:
            return {}
        path = self._checkpoint_path(task_id)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data.get("completed", {})

    def _checkpoint(self, task_id: str, stage: str, payload: dict[str, Any]) -> None:
        if not self.config.checkpoint_enabled:
            return
        path = self._checkpoint_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {"task_id": task_id, "completed": {}}
        else:
            data = {"task_id": task_id, "completed": {}}
        data["task_id"] = task_id
        data["last_stage"] = stage
        data["payload"] = payload
        data.setdefault("completed", {})[stage] = payload
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _emit(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    def _llm_runtime_summary(self) -> str:
        if self.llm_client is None:
            return "disabled"
        if hasattr(self.llm_client, "provider_candidates"):
            try:
                quick = self.llm_client.provider_candidates(role="quick", explicit_model=self.config.quick_model)
                deep = self.llm_client.provider_candidates(role="deep", explicit_model=self.config.deep_model)
                quick_text = ",".join(f"{item.name}:{item.model}" for item in quick) or "none"
                deep_text = ",".join(f"{item.name}:{item.model}" for item in deep) or "none"
                return f"quick=[{quick_text}] deep=[{deep_text}]"
            except Exception as exc:
                return f"{self.llm_client.__class__.__name__} summary_error={exc}"
        return self.llm_client.__class__.__name__

    def _search_runtime_summary(self) -> str:
        settings = getattr(self.search_client, "settings", None)
        if settings is None:
            return self.search_client.__class__.__name__
        providers = []
        if getattr(settings, "tavily_api_key", ""):
            providers.append("tavily")
        if getattr(settings, "serper_api_key", ""):
            providers.append("serper")
        if getattr(settings, "google_search_api_key", "") and getattr(settings, "google_search_cx", ""):
            providers.append("google_cse")
        return ",".join(providers) or "none"


__all__ = ["ResearchGraph", "ResearchGraphConfig", "EvidenceBundle"]
