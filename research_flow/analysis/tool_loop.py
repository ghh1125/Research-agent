from __future__ import annotations

from dataclasses import dataclass

from research_flow.analysis.reports import AGENT_CATEGORY_SCOPE, build_analyst_reports
from research_flow.evidence.data_registry import DataToolRegistry
from research_flow.schema import AnalystReport, EvidenceBundle, ResearchPlan, ResearchTask

VALID_DATA_CATEGORIES = {
    "market_data",
    "financial_statements",
    "filings",
    "news",
    "macro",
    "industry",
    "valuation",
}

CATEGORY_KEYWORDS = (
    ("financial_statements", ("利润表", "现金流", "资产负债", "财务", "营收", "收入", "毛利率", "净利率", "净利润", "财报", "年报", "annual report")),
    ("valuation", ("估值", "pe", "pb", "ev/ebitda", "目标价", "券商", "评级", "市盈率", "市净率", "comparable", "dcf")),
    ("market_data", ("基金", "持仓", "北向", "融资融券", "资金流", "技术指标", "日频", "股价", "成交", "换手", "positioning")),
    ("macro", ("国家统计局", "gdp", "工业增加值", "宏观", "通胀", "利率", "汇率", "政策", "周期")),
    ("industry", ("行业", "销量", "渗透率", "市占率", "市场份额", "竞争", "供需", "产能", "sne", "供应链")),
    ("filings", ("公告", "重大合同", "交易所", "深交所", "巨潮", "sec", "filing", "hkex", "investor relations")),
    ("news", ("新闻", "事件", "催化", "订单", "制裁", "风险", "latest", "recent")),
)


@dataclass
class AnalystToolLoopResult:
    reports: list[AnalystReport]
    bundle: EvidenceBundle


def build_analyst_reports_with_tool_loop(
    task: ResearchTask,
    plan: ResearchPlan,
    bundle: EvidenceBundle,
    registry: DataToolRegistry,
    llm_client,
    *,
    max_rounds: int | None = None,
    allow_fallback: bool = False,
) -> AnalystToolLoopResult:
    rounds = registry.config.max_agent_tool_rounds if max_rounds is None else max_rounds
    reports = build_analyst_reports(task, plan, bundle, llm_client, allow_fallback=allow_fallback)
    for _ in range(max(rounds, 0)):
        followup_requests = _normalize_followup_requests(reports, plan, registry.config)
        if not followup_requests:
            break
        for category, queries in followup_requests.items():
            followup = registry.collect_followup(task, plan, [category], queries)
            bundle = _merge_bundle(bundle, followup)
        reports = build_analyst_reports(task, plan, bundle, llm_client, allow_fallback=allow_fallback)
    return AnalystToolLoopResult(reports=reports, bundle=bundle)


def _merge_bundle(left: EvidenceBundle, right: EvidenceBundle) -> EvidenceBundle:
    return EvidenceBundle(
        artifacts=[*left.artifacts, *right.artifacts],
        evidence=[*left.evidence, *right.evidence],
        tool_counts={**left.tool_counts, **right.tool_counts},
        tool_errors={**left.tool_errors, **right.tool_errors},
    )


def _normalize_followup_requests(
    reports: list[AnalystReport],
    plan: ResearchPlan,
    config,
) -> dict[str, list[str]]:
    plan_categories = {item for item in plan.data_sources if item in VALID_DATA_CATEGORIES}
    if not plan_categories:
        plan_categories = set(VALID_DATA_CATEGORIES)
    requests: dict[str, list[str]] = {}
    seen_queries: set[tuple[str, str]] = set()
    max_queries = max(0, config.max_followup_queries_per_round)
    max_categories = max(1, config.max_followup_categories_per_round)
    query_count = 0

    for report in reports:
        allowed = _allowed_categories(report.role_id, plan_categories)
        requested = [_normalize_category(source, allowed) for source in report.requested_data_sources]
        requested = [category for category in requested if category]
        queries = _unique_non_empty(report.followup_queries)

        if not queries:
            for category in requested[:max_categories]:
                requests.setdefault(category, [])
            continue

        for query in queries:
            if query_count >= max_queries:
                break
            category = _normalize_category(query, allowed) or (requested[0] if requested else _fallback_category(allowed))
            if category is None:
                continue
            key = (category, query)
            if key in seen_queries:
                continue
            seen_queries.add(key)
            requests.setdefault(category, []).append(query)
            query_count += 1

    return {category: queries for category, queries in list(requests.items())[:max_categories]}


def _allowed_categories(role_id: str, plan_categories: set[str]) -> set[str]:
    scoped = set(AGENT_CATEGORY_SCOPE.get(role_id, sorted(VALID_DATA_CATEGORIES)))
    allowed = scoped & plan_categories
    return allowed or plan_categories


def _normalize_category(raw: str, allowed: set[str]) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if value in VALID_DATA_CATEGORIES and value in allowed:
        return value
    lowered = value.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if category in allowed and any(keyword in lowered or keyword in value for keyword in keywords):
            return category
    return None


def _fallback_category(allowed: set[str]) -> str | None:
    for preferred in ("news", "filings", "financial_statements", "market_data", "macro", "industry", "valuation"):
        if preferred in allowed:
            return preferred
    return sorted(allowed)[0] if allowed else None


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
