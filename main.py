from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from research_flow.graph import ResearchGraph, ResearchGraphConfig
from research_flow.schema import ResearchResult


def run_query(
    query: str,
    *,
    config: ResearchGraphConfig | dict[str, Any] | None = None,
    llm_client: Any | None = None,
    search_client: Any | None = None,
    progress_callback: Any | None = None,
    **task_options: Any,
) -> ResearchResult:
    """Run one user sentence through the five-layer research workflow."""

    graph = ResearchGraph(config, llm_client=llm_client, search_client=search_client, progress_callback=progress_callback)
    return graph.propagate(query, **task_options)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the five-layer investment research agent.")
    parser.add_argument("query", nargs="*", help="一句自然语言投研问题，例如：深度研究宁德时代是否值得进一步研究")
    parser.add_argument("--symbols", help="逗号分隔 ticker/symbol，例如 300750.SZ,NVDA")
    parser.add_argument("--market", help="市场，例如 A_share/HK/US/private/thematic/macro")
    parser.add_argument("--horizon", help="投资周期，例如 6-12个月")
    parser.add_argument("--time-range", help="研究日期/时间范围，例如 2026-05-09 或 2025Q4-2026Q1")
    parser.add_argument("--question-type", choices=["single_stock_deep_dive", "industry_comparison", "event_impact", "portfolio_risk_review", "trading_decision_assist"])
    parser.add_argument("--depth", dest="research_depth", choices=["quick", "standard", "deep"])
    parser.add_argument("--risk", dest="risk_preference", choices=["conservative", "neutral", "aggressive"])
    parser.add_argument("--agents", help="逗号分隔 analyst，例如 macro,industry,fundamentals,valuation,news_event,technical_positioning")
    parser.add_argument("--model-profile", default="default", help="模型配置名，会写入 ResearchTask")
    parser.add_argument("--quick-model", help="信息抽取、任务解析、计划生成使用的快模型")
    parser.add_argument("--deep-model", help="专项分析、辩论、裁决和报告判断使用的强模型")
    parser.add_argument("--output-language", default="zh-CN", help="输出语言，例如 zh-CN 或 English")
    parser.add_argument("--max-debate-rounds", type=int, default=2, help="Bull/Bear 多空辩论轮数")
    parser.add_argument("--max-risk-rounds", type=int, default=1, help="Aggressive/Conservative/Neutral 风控辩论轮数")
    parser.add_argument("--max-agent-tool-rounds", type=int, default=1, help="专项 Agent 发现证据缺口后的补充检索轮数")
    parser.add_argument("--max-followup-queries", type=int, default=6, help="每轮 Agent 补检索最多 query 数，防止 LLM 生成过多搜索")
    parser.add_argument("--max-followup-categories", type=int, default=3, help="每轮 Agent 补检索最多数据源类别数")
    parser.add_argument("--search-max-results", type=int, default=5, help="每类数据源最多检索结果数")
    parser.add_argument("--fetch-source-content", action="store_true", help="对搜索结果 URL 继续抓取网页/PDF 全文；默认关闭以避免卡在慢站点")
    parser.add_argument("--source-fetch-timeout", type=float, default=5.0, help="启用 --fetch-source-content 时单个 URL 抓取超时秒数")
    parser.add_argument("--llm-timeout", type=float, help="单次 LLM 请求超时秒数，会覆盖 LLM_TIMEOUT_SECONDS")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--markdown", action="store_true", help="只输出 Markdown 报告")
    parser.add_argument("--checkpoint", action="store_true", help="写入断点文件，便于后续恢复/排查")
    parser.add_argument("--quiet", action="store_true", help="关闭运行进度日志，只输出最终结果")
    return parser


def _task_options(args: argparse.Namespace) -> dict[str, Any]:
    options = {
        "symbols": [item.strip() for item in args.symbols.split(",")] if args.symbols else None,
        "market": args.market,
        "time_range": args.time_range,
        "horizon": args.horizon,
        "question_type": args.question_type,
        "research_depth": args.research_depth,
        "risk_preference": args.risk_preference,
    }
    return {key: value for key, value in options.items() if value is not None}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = " ".join(args.query).strip()
    if not query:
        query = input("请输入投研问题：").strip()
    if args.llm_timeout is not None:
        os.environ["RESEARCH_AGENT_LLM_TIMEOUT_SECONDS"] = str(args.llm_timeout)
    progress_callback = None if args.quiet else _stderr_progress
    result = run_query(
        query,
        config=ResearchGraphConfig(
            checkpoint_enabled=args.checkpoint,
            selected_agents=[item.strip() for item in args.agents.split(",")] if args.agents else None,
            model_profile=args.model_profile,
            quick_model=args.quick_model,
            deep_model=args.deep_model,
            output_language=args.output_language,
            max_debate_rounds=args.max_debate_rounds,
            max_risk_discuss_rounds=args.max_risk_rounds,
            max_agent_tool_rounds=args.max_agent_tool_rounds,
            max_followup_queries_per_round=args.max_followup_queries,
            max_followup_categories_per_round=args.max_followup_categories,
            search_max_results=args.search_max_results,
            fetch_source_content=args.fetch_source_content,
            source_fetch_timeout_seconds=args.source_fetch_timeout,
        ),
        progress_callback=progress_callback,
        **_task_options(args),
    )
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    elif args.markdown:
        print(result.report.markdown)
    else:
        print(f"任务类型：{result.task.question_type}")
        print(f"标的：{', '.join(result.task.symbols) or result.task.entity or '未识别'}")
        print(f"建议：{result.portfolio_decision.action}")
        print(f"评级：{result.manager_decision.rating} / {result.manager_decision.confidence}")
        print(f"报告路径：data/research_logs/{result.task.id}.json")
        print("流程：" + " -> ".join(stage.name for stage in result.stage_trace))
    return 0


def _stderr_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
