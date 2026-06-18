from __future__ import annotations

import argparse
import json
import sys

from src.pipeline import BPPipeline, BPPipelineConfig
from src.schema import CompetitorDiscovery


def _stderr_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _interactive_competitor_selector(discovery: CompetitorDiscovery) -> list[str]:
    if not discovery.candidates:
        return []
    print("\n竞品候选列表（竞品发现节点）：", file=sys.stderr)
    for idx, candidate in enumerate(discovery.candidates, start=1):
        print(f"  [{idx}] {candidate.name} | {candidate.relationship} | {candidate.product_or_service}", file=sys.stderr)
    raw = input(f"请输入要纳入竞品矩阵分析的编号（逗号分隔，留空=全选，1-{len(discovery.candidates)}）：").strip()
    if not raw:
        return [c.id for c in discovery.candidates]
    indices = {int(item.strip()) for item in raw.split(",") if item.strip().isdigit()}
    return [c.id for i, c in enumerate(discovery.candidates, start=1) if i in indices]


def _auto_competitor_selector(max_competitors: int) -> object:
    def _selector(discovery: CompetitorDiscovery) -> list[str]:
        return [c.id for c in discovery.candidates[:max_competitors]]

    return _selector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the 7-node VC due-diligence pipeline (BP evaluation).")
    parser.add_argument("company_name", help="目标公司名称")
    parser.add_argument("--website", help="公司官网")
    parser.add_argument("--bp-file", dest="bp_files", action="append", default=[], help="BP 文件路径（PDF/PPT/Word），可重复传入多个")
    parser.add_argument("--funding-round", help="融资轮次，例如 A轮/B轮/Pre-IPO")
    parser.add_argument("--funding-amount", help="融资金额")
    parser.add_argument("--industry", help="所属行业")
    parser.add_argument("--description", dest="project_description", help="项目描述")
    parser.add_argument("--team-file", dest="team_files", action="append", default=[], help="创始团队资料文件，可重复")
    parser.add_argument("--financial-file", dest="financial_files", action="append", default=[], help="财务报表文件（建议 xlsx），可重复")
    parser.add_argument("--business-plan-file", dest="business_plan_files", action="append", default=[], help="业务规划书文件，可重复")
    parser.add_argument("--tech-ip-file", dest="tech_ip_files", action="append", default=[], help="技术与知识产权资料文件，可重复")
    parser.add_argument("--legal-file", dest="legal_files", action="append", default=[], help="法律文件摘要文件，可重复")
    parser.add_argument("--auto-select-competitors", action="store_true", help="跳过人工确认竞品环节，自动选取前 N 个候选竞品")
    parser.add_argument("--max-competitors", type=int, default=5, help="--auto-select-competitors 时自动选取的竞品数量上限")
    parser.add_argument("--output-dir", default="data/bp_reports", help="每个节点报告（markdown+docx）写入的目录")
    parser.add_argument("--search-max-results", type=int, default=5, help="每类检索最多结果数")
    parser.add_argument("--json", action="store_true", help="额外输出完整 PipelineState JSON")
    parser.add_argument("--quiet", action="store_true", help="关闭运行进度日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress_callback = None if args.quiet else _stderr_progress
    competitor_selector = _auto_competitor_selector(args.max_competitors) if args.auto_select_competitors else _interactive_competitor_selector

    pipeline = BPPipeline(
        config=BPPipelineConfig(
            output_dir=args.output_dir,
            search_max_results=args.search_max_results,
        ),
        progress_callback=progress_callback,
    )
    state = pipeline.run(
        company_name=args.company_name,
        website=args.website,
        bp_files=args.bp_files,
        funding_round=args.funding_round,
        funding_amount=args.funding_amount,
        industry=args.industry,
        project_description=args.project_description,
        team_files=args.team_files,
        financial_files=args.financial_files,
        business_plan_files=args.business_plan_files,
        tech_ip_files=args.tech_ip_files,
        legal_files=args.legal_files,
        competitor_selector=competitor_selector,
    )

    print(state.final_report.markdown if state.final_report else "(无最终报告)")
    if args.json:
        print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"\n报告已写入：{args.output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
