from __future__ import annotations

import re
from collections import Counter, defaultdict

from app.models.evidence import Evidence
from app.models.financial import FinancialSnapshot
from app.models.judgment import Judgment
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable
from app.services.display_formatters import format_display_value, humanize_unit, sanitize_display_text
from app.services.evidence_registry import EvidenceRegistry
from app.services.llm_dashboard_summarizer import summarize_dashboard
from app.services.llm_research_depth_qa import assess_research_depth

_NUMERIC_METRICS = {
    "revenue",
    "revenue_growth",
    "gross_margin",
    "gross_margins",
    "profit_margins",
    "net_profit_margin",
    "net_income",
    "operating_cash_flow",
    "free_cash_flow",
    "capex",
    "capital_expenditure",
    "buybacks",
    "share_buyback",
    "dividends",
    "forward_pe",
    "trailing_pe",
    "pe",
    "pb",
    "ev_ebitda",
    "price_to_sales",
    "ps",
    "fcf_yield",
    "peg",
    "market_share",
    "take_rate",
    "active_buyers",
    "nrr",
    "cac_payback",
    "rule_of_40",
    "nim",
    "cet1",
    "npl",
    "combined_ratio",
    "solvency",
    "float",
    "same_store_sales",
    "utilization",
    "order_growth",
    "backlog",
}

_METRIC_LABELS = {
    "revenue": "收入",
    "gross_margin": "利润率",
    "gross_margins": "利润率",
    "profit_margins": "利润率",
    "net_profit_margin": "净利率",
    "operating_cash_flow": "经营现金流",
    "free_cash_flow": "自由现金流",
    "capex": "资本开支",
    "capital_expenditure": "资本开支",
    "buybacks": "回购",
    "share_buyback": "回购",
    "dividends": "分红",
    "forward_pe": "预期市盈率",
    "trailing_pe": "P/E",
    "pe": "P/E",
    "pb": "P/B",
    "ev_ebitda": "EV / EBITDA",
    "price_to_sales": "市销率",
    "ps": "市销率",
    "fcf_yield": "自由现金流收益率",
    "peg": "PEG",
    "market_share": "市场份额",
    "take_rate": "货币化率",
    "active_buyers": "活跃买家",
    "nrr": "NRR",
    "cac_payback": "CAC Payback",
    "rule_of_40": "Rule of 40",
    "nim": "NIM",
    "cet1": "CET1",
    "npl": "NPL",
    "combined_ratio": "Combined Ratio",
    "solvency": "Solvency",
    "float": "Float",
    "same_store_sales": "Same-store Sales",
    "utilization": "Utilization",
    "order_growth": "Order Growth",
    "backlog": "Backlog",
}

_ABSOLUTE_VALUATION_KEYS = ["forward_pe", "trailing_pe", "pe", "ev_ebitda", "price_to_sales", "ps", "fcf_yield", "peg", "pb"]
_COMPETITION_FRAMEWORK = [
    ("market_share", "市场份额"),
    ("pricing_power", "定价能力"),
    ("retention", "留存与粘性"),
    ("switching_cost", "切换成本"),
    ("innovation_velocity", "创新速度"),
    ("distribution_advantage", "分发优势"),
    ("cost_leadership", "成本优势"),
]


def _safe_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _normalize_metric_name(name: str | None) -> str:
    return re.sub(r"[\s/-]+", "_", (name or "").strip().lower())


def _format_metric_value(value: object, unit: str | None = None) -> str:
    return format_display_value(value, unit)


def _metric_display_name(metric_name: str | None) -> str:
    normalized = _normalize_metric_name(metric_name)
    return _METRIC_LABELS.get(normalized, metric_name or "指标")


def _has_decline_signal(record: dict[str, object] | None) -> bool:
    if not record:
        return False
    content = str(record.get("content") or "").lower()
    return any(token in content for token in ["decrease", "decreased", "declined", "down", "下降", "下滑", "承压"])


def _has_metric(metric_records: dict[str, list[dict[str, object]]], names: list[str]) -> bool:
    return _best_metric(metric_records, names) is not None


def _has_high_confidence_anchor(curated_evidence: list[dict[str, object]], metric_names: set[str], *, official_only: bool = False) -> bool:
    for item in curated_evidence:
        metric_name = _normalize_metric_name(str(item.get("metric_name") or ""))
        tier = str(item.get("tier") or "")
        if metric_name in metric_names and (tier == "official" or (not official_only and tier in {"official", "professional"})):
            return True
    return False


def _guard_claim_text(
    text: str,
    *,
    valuation_anchor: bool,
    competition_anchor: bool,
    capital_return_anchor: bool,
) -> str:
    guarded = sanitize_display_text(text)
    if not valuation_anchor and any(token in guarded.lower() for token in ["cheap", "低估", "便宜", "安全边际"]):
        return "已有部分估值倍数，但缺少历史区间和同行中位数，估值判断仍需进一步验证。"
    if not competition_anchor and any(token in guarded.lower() for token in ["moat", "护城河", "竞争优势", "leader", "龙头"]):
        return "竞争位置证据仍不足，暂无法判断护城河强度和份额稳固性。"
    if not capital_return_anchor and any(token in guarded.lower() for token in ["buyback", "dividend", "capital return", "净负债", "net debt", "回购", "分红", "资本回报"]):
        return "资本回报和净负债判断仍缺少同口径高可信数据，当前只能作为待验证线索。"
    return guarded


def _serialize_evidence(item: Evidence, source: Source | None) -> dict[str, object]:
    return {
        "id": item.id,
        "metric_name": _metric_display_name(item.metric_name or item.id),
        "value": _format_metric_value(item.metric_value, item.unit),
        "metric_value": _format_metric_value(item.metric_value, item.unit),
        "unit": humanize_unit(item.unit),
        "period": item.period,
        "tier": item.source_tier,
        "quote": sanitize_display_text(item.content),
        "url": source.url if source is not None else None,
        "source_title": source.title if source is not None else None,
        "source_type": source.source_origin_type if source is not None else item.source_type,
    }


def _verdict_label(judgment: Judgment) -> str:
    if judgment.investment_decision is None:
        return judgment.positioning or "观察清单"
    mapping = {
        "watchlist": "观察清单",
        "deprioritize": "暂缓研究",
        "deep_dive_candidate": "标准研究",
        "establish_tracking": "建立跟踪",
        "monitor_for_trigger": "仍需补证",
    }
    return mapping.get(judgment.investment_decision.decision, judgment.positioning or "观察清单")


def _evidence_items(registry: EvidenceRegistry, evidence_ids: list[str], source_map: dict[str, Source], *, limit: int = 2) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for evidence_id in registry.filter_existing(evidence_ids)[:limit]:
        evidence = registry.get(evidence_id)
        if evidence is None:
            continue
        items.append(_serialize_evidence(evidence, source_map.get(evidence.source_id)))
    return items


def _metric_record_priority(record: dict[str, object]) -> tuple[int, int, float]:
    source_kind = str(record.get("source_kind") or "snapshot")
    source_rank = {"evidence": 0, "snapshot": 1}.get(source_kind, 2)
    period = str(record.get("period") or "").upper()
    if period.startswith("TTM"):
        period_rank = 0
    elif period.startswith("FY") and "Q" not in period:
        period_rank = 1
    elif "Q" in period:
        period_rank = 2
    else:
        period_rank = 3
    score = float(record.get("score") or 0.0)
    return (source_rank, period_rank, -score)


def _collect_metric_records(registry: EvidenceRegistry, financial_snapshot: FinancialSnapshot | None) -> dict[str, list[dict[str, object]]]:
    records: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in registry.evidence:
        metric_name = _normalize_metric_name(item.metric_name)
        if metric_name not in _NUMERIC_METRICS:
            continue
        records[metric_name].append(
            {
                "metric_name": metric_name,
                "value": item.metric_value,
                "unit": item.unit,
                "period": item.period,
                "score": item.evidence_score or item.quality_score or item.extraction_confidence or 0.0,
                "content": item.content,
                "source_kind": "evidence",
            }
        )
    if financial_snapshot is not None:
        for metric in financial_snapshot.metrics:
            metric_name = _normalize_metric_name(metric.name)
            if metric_name not in _NUMERIC_METRICS:
                continue
            records[metric_name].append(
                {
                    "metric_name": metric_name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "period": metric.period,
                    "score": 0.65,
                    "content": "",
                    "source_kind": "snapshot",
                }
            )
    for metric_name in list(records.keys()):
        records[metric_name] = sorted(records[metric_name], key=_metric_record_priority)
    return records


def _best_metric(metric_records: dict[str, list[dict[str, object]]], names: list[str]) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []
    for name in names:
        candidates.extend(metric_records.get(_normalize_metric_name(name), []))
    return sorted(candidates, key=_metric_record_priority)[0] if candidates else None


def _period_signature(period: str | None) -> tuple[str, str] | None:
    normalized = (period or "").strip().upper()
    if not normalized:
        return None
    if normalized.startswith("TTM"):
        return ("TTM", "TTM")
    match = re.match(r"(?:FY)?(20\d{2})(Q[1-4])?$", normalized)
    if match:
        year = match.group(1)
        quarter = match.group(2)
        if quarter:
            return ("Q", f"{year}{quarter}")
        return ("FY", year)
    match = re.match(r"(20\d{2})[-/](\d{2})[-/](\d{2})", normalized)
    if match:
        return ("DATE", match.group(0))
    return ("OTHER", normalized)


def _cash_flow_alignment(ocf: dict[str, object] | None, capex: dict[str, object] | None, fcf: dict[str, object] | None) -> tuple[str, str]:
    records = [item for item in [ocf, capex, fcf] if item is not None]
    if len(records) < 2:
        return "unknown", "现金流桥所需的 OCF / Capex / FCF 数据仍不完整。"
    signatures = [_period_signature(str(item.get("period") or "")) for item in records]
    if all(signature is not None for signature in signatures) and len({signature for signature in signatures if signature is not None}) == 1:
        return "aligned", "资本开支、经营现金流与自由现金流周期基本一致，可用于同口径观察。"
    return "misaligned", "资本开支相关证据周期不一致，当前结论置信度下降。"


def _capital_return_status(fcf_value: float | None, buybacks_value: float | None, dividends_value: float | None, aligned: bool) -> tuple[str, str]:
    if not aligned:
        return "覆盖能力待验证", "口径尚未统一，资本回报覆盖能力仍需验证。"
    if fcf_value is None:
        return "覆盖能力待验证", "缺少自由现金流数据，无法判断资本回报覆盖。"
    if buybacks_value is None or dividends_value is None:
        return "覆盖能力待验证", "缺少同期回购或分红数据，资本回报覆盖能力待验证。"
    distributions = sum(item for item in [buybacks_value or 0.0, dividends_value or 0.0])
    coverage = fcf_value - distributions
    if fcf_value <= 0:
        return "难以持续", "自由现金流为负，资本回报缺乏内部现金流支撑。"
    if coverage >= 0:
        return "结构较健康", "自由现金流暂可覆盖当前回购和分红。"
    return "资本回报覆盖偏紧", "自由现金流尚不足以完全覆盖当前资本回报。"


def _cash_flow_bridge(metric_records: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    ocf = _best_metric(metric_records, ["operating_cash_flow"])
    capex = _best_metric(metric_records, ["capex", "capital_expenditure"])
    fcf = _best_metric(metric_records, ["free_cash_flow"])
    buybacks = _best_metric(metric_records, ["buybacks", "share_buyback"])
    dividends = _best_metric(metric_records, ["dividends"])
    alignment, commentary = _cash_flow_alignment(ocf, capex, fcf)
    fcf_value = _safe_float(fcf.get("value")) if fcf else None
    buybacks_value = _safe_float(buybacks.get("value")) if buybacks else None
    dividends_value = _safe_float(dividends.get("value")) if dividends else None
    capital_return_status, capital_return_comment = _capital_return_status(
        fcf_value,
        buybacks_value,
        dividends_value,
        alignment == "aligned",
    )
    fcf_declining = _has_decline_signal(fcf)
    ocf_positive = bool(ocf and (_safe_float(ocf.get("value")) or 0.0) > 0)
    if fcf_value is None:
        overall_status = "仍需补证"
        overall_comment = "自由现金流数据仍不完整，现金流质量暂无法稳定判断。"
    elif fcf_value <= 0:
        overall_status = "边际承压"
        overall_comment = "自由现金流已转弱，现金流质量需要继续关注。"
    elif ocf_positive and fcf_declining:
        overall_status = "承压但未失控"
        overall_comment = "经营现金流仍为正，但自由现金流受资本开支和投入影响承压。"
    elif ocf_positive:
        overall_status = "暂稳，仍需验证"
        overall_comment = "经营现金流仍为正，但自由现金流趋势仍需更多周期数据验证。"
    else:
        overall_status = "仍需补证"
        overall_comment = "现金流质量仍缺少足够同口径数据验证。"
    capital_return_coverage = None if fcf_value is None else fcf_value - (buybacks_value or 0.0) - (dividends_value or 0.0)
    rows = [
        {
            "metric": "经营现金流",
            "current": _format_metric_value(ocf.get("value"), ocf.get("unit")) if ocf else "N/A",
            "yoy": "待补证",
            "status": "结构较健康" if ocf_positive else "仍需补证",
        },
        {
            "metric": "资本开支",
            "current": _format_metric_value(capex.get("value"), capex.get("unit")) if capex else "N/A",
            "yoy": "待补证",
            "status": "已观察到" if capex else "待补证",
        },
        {
            "metric": "自由现金流",
            "current": _format_metric_value(fcf.get("value"), fcf.get("unit")) if fcf else "N/A",
            "yoy": "待补证",
            "status": "边际承压" if fcf_declining else overall_status if fcf else "待补证",
        },
        {
            "metric": "资本回报覆盖",
            "current": _format_metric_value(capital_return_coverage, fcf.get("unit") if fcf else None) if capital_return_coverage is not None else "N/A",
            "yoy": "待补证",
            "status": capital_return_status,
        },
    ]
    return {
        "alignment": alignment,
        "commentary": sanitize_display_text(f"现金流质量：{overall_status}。{overall_comment} {commentary} {capital_return_comment}".strip()),
        "status": overall_status,
        "rows": rows,
    }


def _financial_summary(variables: list[ResearchVariable], cash_flow_bridge: dict[str, object], metric_records: dict[str, list[dict[str, object]]]) -> str:
    relevant = [item for item in variables if item.category == "financial"][:3]
    base = "；".join(sanitize_display_text(item.value_summary) for item in relevant if item.value_summary)[:180] if relevant else "收入、盈利与现金流仍需结合更多高质量数据交叉验证。"
    revenue = _best_metric(metric_records, ["revenue"])
    margin = _best_metric(metric_records, ["gross_margin", "gross_margins", "profit_margins", "net_profit_margin"])
    headline: list[str] = []
    if revenue:
        headline.append(f"收入约为{_format_metric_value(revenue.get('value'), revenue.get('unit'))}")
    if margin:
        headline.append(f"利润率约为{_format_metric_value(margin.get('value'), margin.get('unit'))}")
    headline.append(str(cash_flow_bridge["commentary"]))
    return sanitize_display_text(f"{'；'.join(headline)}。{base}".strip())


def _absolute_valuation(metric_records: dict[str, list[dict[str, object]]], financial_snapshot: FinancialSnapshot | None, peer_rows: list[dict[str, object]]) -> dict[str, object]:
    rows = []
    available_numeric = []
    snapshot_valuation = (financial_snapshot.valuation if financial_snapshot is not None else {}) or {}
    for key in _ABSOLUTE_VALUATION_KEYS:
        metric = _best_metric(metric_records, [key])
        if metric is None and key not in {"trailing_pe", "pe"}:
            continue
        current_value = metric.get("value") if metric else snapshot_valuation.get(key)
        if current_value is not None:
            available_numeric.append(key)
        rows.append(
            {
                "metric": _METRIC_LABELS.get(key, key),
                "current": _format_metric_value(current_value, metric.get("unit") if metric else None),
                "historical": snapshot_valuation.get(f"{key}_history") or "待补证",
                "percentile": snapshot_valuation.get(f"{key}_percentile") or "待补证",
            }
        )
    peer_peers = [row.get("valuation_pe") for row in peer_rows if _safe_float(row.get("valuation_pe")) is not None]
    percentiles = [float(snapshot_valuation[f"{key}_percentile"]) for key in _ABSOLUTE_VALUATION_KEYS if snapshot_valuation.get(f"{key}_percentile") is not None]
    has_historical = bool(percentiles)
    has_peer_median = bool(peer_peers)
    assessment = "参照系缺失"
    summary = "已有估值倍数，但缺少历史区间和同行中位数，暂不能判断是否便宜。"
    if available_numeric and has_historical and has_peer_median:
        median_percentile = sorted(percentiles)[len(percentiles) // 2]
        if median_percentile <= 35:
            assessment = "相对偏低"
            summary = "绝对估值位于历史区间偏低位置，但仍需结合增长与现金流兑现情况一起判断。"
        elif median_percentile >= 65:
            assessment = "相对偏高"
            summary = "绝对估值位于历史区间偏高位置，后续更依赖增长和利润率兑现。"
        else:
            assessment = "大致中性"
            summary = "绝对估值大致处于历史与同行中性区间，仍需结合经营兑现情况观察。"
    return {"assessment": assessment, "rows": rows, "summary": summary}


def _relative_peers(financial_snapshot: FinancialSnapshot | None, judgment: Judgment) -> list[dict[str, object]]:
    rows = []
    source_rows = []
    if financial_snapshot is not None and financial_snapshot.peer_comparison:
        source_rows = financial_snapshot.peer_comparison
    elif judgment.peer_context is not None and judgment.peer_context.comparison_rows:
        source_rows = judgment.peer_context.comparison_rows
    for row in source_rows[:6]:
        rows.append(
            {
                "company": row.get("peer_name") or row.get("peer") or row.get("ticker") or row.get("symbol") or "",
                "pe": format_display_value(row.get("valuation_pe") or row.get("trailingPE"), "x"),
                "rev_growth": format_display_value(row.get("revenue_growth"), "%"),
                "margin": format_display_value(row.get("gross_margin"), "%"),
                "fcf_yield": format_display_value(row.get("fcf_yield"), "%"),
                "market_share": format_display_value(row.get("market_share"), "%"),
                "moat": sanitize_display_text(row.get("positioning", {}).get("summary") if isinstance(row.get("positioning"), dict) else row.get("peer_group") or "待补证"),
            }
        )
    return rows


def _market_implied_narrative(absolute_valuation: dict[str, object], peer_rows: list[dict[str, object]], competition_summary: str) -> str:
    assessment = absolute_valuation["assessment"]
    if assessment == "相对偏低":
        return "市场对后续增长兑现和资本开支回报仍有疑虑，定价相对保守。"
    if assessment == "相对偏高":
        return "市场对执行质量和中长期弹性已有一定预期，后续更依赖兑现。"
    if peer_rows:
        return "市场对增长兑现和资本开支回报仍有分歧。"
    return "已有估值线索，但市场定价叙事仍缺少完整参照。"


def _rerating_triggers(metric_records: dict[str, list[dict[str, object]]], top_gaps: list[dict[str, object]]) -> list[str]:
    triggers = []
    if _best_metric(metric_records, ["revenue_growth"]):
        triggers.append("增长重新加速")
    if _best_metric(metric_records, ["gross_margin", "gross_margins", "profit_margins"]):
        triggers.append("利润率修复")
    if _best_metric(metric_records, ["capex", "capital_expenditure"]):
        triggers.append("资本开支回落到可持续水平")
    if _best_metric(metric_records, ["market_share"]):
        triggers.append("核心份额稳定或回升")
    if any("product" in str(item.get("title", "")).lower() for item in top_gaps):
        triggers.append("新产品周期兑现")
    return list(dict.fromkeys(triggers or ["增长重新加速", "利润率修复", "资本开支回落到可持续水平"]))[:4]


def _competition_framework(metric_records: dict[str, list[dict[str, object]]], peer_rows: list[dict[str, object]], topic: Topic) -> dict[str, object]:
    target_row = next((row for row in peer_rows if str(row.get("peer_group")) == "target"), peer_rows[0] if peer_rows else {})
    summary_text = str(target_row.get("market_share") or "")
    framework = []
    metric_presence = {
        "market_share": _best_metric(metric_records, ["market_share"]),
        "pricing_power": _best_metric(metric_records, ["gross_margin", "gross_margins", "profit_margins", "net_profit_margin", "take_rate"]),
        "retention": _best_metric(metric_records, ["retention", "nrr", "active_buyers"]),
        "switching_cost": _best_metric(metric_records, ["switching_cost"]),
        "innovation_velocity": _best_metric(metric_records, ["r_and_d_ratio", "node_leadership"]),
        "distribution_advantage": _best_metric(metric_records, ["active_buyers", "distribution_advantage", "gmv"]),
        "cost_leadership": _best_metric(metric_records, ["gross_margin", "cost_leadership"]),
    }
    for key, label in _COMPETITION_FRAMEWORK:
        score = "待补证"
        if metric_presence.get(key):
            score = "较强" if key == "market_share" else "中等"
        elif key == "market_share" and any(token in summary_text.lower() for token in ["leader", "challenger", "incumbent"]):
            score = "中等"
        framework.append({"dimension": label, "score": score})
    missing_core = not any(
        _has_metric(metric_records, names)
        for names in [
            ["market_share"],
            ["retention", "nrr", "active_buyers"],
            ["gmv"],
            ["take_rate"],
            ["merchant_count", "merchant"],
        ]
    )
    if missing_core:
        summary = "竞争位置证据不足，暂无法判断护城河强度。"
        status = "无法判断"
    elif any(item["score"] == "较强" for item in framework[:2]):
        summary = "已有部分竞争位置证据，但仍需结合更多同行数据验证份额与盈利持续性。"
        status = "部分已验证"
    else:
        summary = f"{topic.entity or topic.topic} 的竞争位置仍需结合更多份额、留存和货币化率数据继续验证。"
        status = "仍需补证"
    return {"framework": framework, "peer_table": peer_rows[:5], "summary": summary}


def _bull_case(variables: list[ResearchVariable], judgment: Judgment, cash_flow_bridge: dict[str, object]) -> list[str]:
    items = [sanitize_display_text(item.value_summary) for item in variables if item.direction in {"improving", "stable"} and item.value_summary]
    items.extend(judgment.verified_facts[:2])
    if cash_flow_bridge["status"] in {"暂稳，仍需验证", "承压但未失控"}:
        items.append("经营现金流仍为正，短期现金流质量尚未失控。")
    return list(dict.fromkeys(item for item in items if item))[:5]


def _bear_case(judgment: Judgment, top_gaps: list[dict[str, object]], cash_flow_bridge: dict[str, object]) -> list[str]:
    items = [item.text for item in judgment.risk[:3]]
    items.extend(item.get("title") or item.get("text") or "" for item in top_gaps[:2])
    if cash_flow_bridge["alignment"] == "misaligned":
        items.append("资本开支与自由现金流口径未统一，现金流质量判断仍不稳。")
    return list(dict.fromkeys(item for item in items if item))[:5]


def _what_changes_my_mind(judgment: Judgment, valuation: dict[str, object], competition: dict[str, object], top_gaps: list[dict[str, object]]) -> dict[str, list[str]]:
    upgrade = [
        "核心电商份额稳定或回升。",
        "云业务收入增长伴随利润率改善。",
        "自由现金流回升并能覆盖回购和分红。",
        "估值低于同行或历史区间且增长未恶化。",
    ]
    downgrade = [
        "自由现金流持续恶化。",
        "资本开支继续上升但云业务利润率不改善。",
        "核心电商 GMV、货币化率或 CMR 持续放缓。",
        "净现金缓冲继续下降。",
    ]
    return {
        "upgrade_triggers": upgrade[:4],
        "downgrade_triggers": downgrade[:4],
    }


def _evidence_gaps(depth: dict[str, object], metric_records: dict[str, list[dict[str, object]]], competition: dict[str, object]) -> list[str]:
    gaps = []
    if depth["valuation_depth"] != "covered":
        gaps.append("估值仍缺 forward PE、EV/EBITDA、历史区间或同行中位数。")
    if _best_metric(metric_records, ["capex", "capital_expenditure"]) is None:
        gaps.append("资本开支指引仍待补证。")
    if _best_metric(metric_records, ["market_share"]) is None:
        gaps.append("市场份额数据仍缺失。")
    if _best_metric(metric_records, ["retention", "nrr", "active_buyers"]) is None:
        gaps.append("留存与用户粘性数据仍待补证。")
    if _best_metric(metric_records, ["segment_margin", "gross_margin", "gross_margins", "profit_margins"]) is None:
        gaps.append("分部利润率仍待补证。")
    if all(item["score"] == "待补证" for item in competition["framework"][:2]):
        gaps.append("竞争位置关键证据仍然稀缺。")
    return list(dict.fromkeys(gaps))[:6]


def _snapshot_dashboard_rows(financial_summary: str, cash_flow_bridge: dict[str, object], absolute_valuation: dict[str, object], competition: dict[str, object]) -> list[dict[str, str]]:
    profitability_status = "已观察到" if "利润率" in financial_summary else "仍需补证"
    growth_status = "已观察到" if "收入约为" in financial_summary else "仍需补证"
    return [
        {"category": "增长", "status": growth_status},
        {"category": "盈利能力", "status": profitability_status},
        {"category": "现金流", "status": cash_flow_bridge["status"]},
        {"category": "资本回报", "status": next((row["status"] for row in cash_flow_bridge["rows"] if row["metric"] == "资本回报覆盖"), "覆盖能力待验证")},
        {"category": "估值", "status": absolute_valuation["assessment"]},
        {"category": "竞争", "status": "无法判断" if "暂无法判断护城河强度" in competition["summary"] else "部分已验证"},
    ]


def _next_research_actions(summary_action: dict[str, object], top_gaps: list[dict[str, object]]) -> list[dict[str, object]]:
    actions = [
        {
            "action": summary_action.get("title") or "继续补证",
            "why": summary_action.get("why") or "关键缺口会影响结论强度。",
            "required_data": summary_action.get("required_data") or [],
            "decision_impact": summary_action.get("decision_impact") or "补齐后才能决定是否升级研究深度。",
        }
    ]
    for gap in top_gaps[:2]:
        actions.append(
            {
                "action": gap.get("title") or gap.get("text") or "补关键缺口",
                "why": gap.get("why_it_matters") or "会影响当前判断。",
                "required_data": gap.get("required_data") or [],
                "decision_impact": gap.get("decision_impact") or "补齐后再判断。",
            }
        )
    return actions[:3]


def project_dashboard_view(
    *,
    topic: Topic,
    questions: list,
    sources: list[Source],
    raw_evidence: list[Evidence],
    registry: EvidenceRegistry,
    variables: list[ResearchVariable],
    judgment: Judgment,
    report_internal: dict[str, object],
    financial_snapshot: FinancialSnapshot | None = None,
    auto_research_trace: list[object] | None = None,
) -> dict[str, object]:
    source_map = {item.id: item for item in sources}
    curated_ids = registry.filter_existing(
        judgment.conclusion_evidence_ids
        + [evidence_id for risk in judgment.risk for evidence_id in risk.evidence_ids]
        + [evidence_id for variable in variables for evidence_id in variable.evidence_ids]
    )
    if not curated_ids:
        curated_ids = [item.id for item in registry.evidence]
    curated_evidence = [
        _serialize_evidence(item, source_map.get(item.source_id))
        for item in registry.project_for_display(curated_ids, max_items=12)
    ]
    top_variables = [
        {
            "name": item.name,
            "category": item.category,
            "direction": item.direction,
            "direction_label": item.direction_label or item.direction,
            "summary": sanitize_display_text(item.value_summary),
            "evidence_count": len(registry.filter_existing(item.evidence_ids)),
            "evidence": _evidence_items(registry, item.evidence_ids, source_map),
        }
        for item in variables[:5]
    ]
    top_risks = [
        {
            "text": sanitize_display_text(item.text),
            "evidence": _evidence_items(registry, item.evidence_ids, source_map),
        }
        for item in judgment.risk[:3]
    ]
    depth = assess_research_depth(
        research_questions=[
            {"framework_type": getattr(item, "framework_type", "general"), "content": getattr(item, "content", "")}
            for item in questions
        ],
        coverage=[
            {"framework_type": getattr(item, "framework_type", "general"), "coverage_level": getattr(item, "coverage_level", "uncovered")}
            for item in questions
        ],
        curated_evidence=curated_evidence,
        variables=[
            {"name": item.name, "direction_label": item.direction_label, "evidence_ids": item.evidence_ids}
            for item in variables
        ],
        draft_conclusion=judgment.conclusion,
    )
    top_gaps = [
        {
            "title": sanitize_display_text(item.get("title") or str(item.get("text") or "")),
            "text": sanitize_display_text(item.get("title") or str(item.get("text") or "")),
            "why_it_matters": sanitize_display_text(item.get("why_it_matters") or "该缺口会限制当前结论能否升级。"),
            "required_data": [sanitize_display_text(value) for value in (item.get("required_data") or [])],
            "decision_impact": sanitize_display_text(item.get("decision_impact") or "补齐后才能判断是否提升研究优先级。"),
        }
        for item in depth.get("critical_gaps", [])
    ]
    if not top_gaps:
        top_gaps = [
            {
                "title": item.text,
                "text": item.text,
                "why_it_matters": f"重要性：{item.importance}",
                "required_data": [],
                "decision_impact": "会直接影响研究结论强度。",
            }
            for item in judgment.evidence_gaps[:3]
        ]

    action = judgment.research_actions[0] if judgment.research_actions else None
    verdict = _verdict_label(judgment)
    summary = summarize_dashboard(
        verified_facts=judgment.verified_facts,
        probable_inferences=judgment.probable_inferences,
        pending_assumptions=judgment.pending_assumptions,
        top_risks=[{"text": item.text, "evidence_ids": item.evidence_ids} for item in judgment.risk[:3]],
        top_gaps=top_gaps,
        curated_evidence=curated_evidence,
        confidence=judgment.confidence,
        verdict=verdict,
        next_action_title=action.objective if action is not None else (top_gaps[0]["title"] if top_gaps else "继续补证"),
        required_data=action.required_data if action is not None else (top_gaps[0]["required_data"] if top_gaps else []),
    )

    metric_records = _collect_metric_records(registry, financial_snapshot)
    cash_flow_bridge = _cash_flow_bridge(metric_records)
    financial_summary = _financial_summary(variables, cash_flow_bridge, metric_records)
    peer_rows = _relative_peers(financial_snapshot, judgment)
    absolute_valuation = _absolute_valuation(metric_records, financial_snapshot, peer_rows)
    competition = _competition_framework(metric_records, peer_rows, topic)
    valuation = {
        "absolute": absolute_valuation,
        "relative_peers": {"rows": peer_rows[:5]},
        "market_implied_narrative": _market_implied_narrative(absolute_valuation, peer_rows, competition["summary"]),
        "rerating_triggers": _rerating_triggers(metric_records, top_gaps),
    }
    valuation_anchor = _has_high_confidence_anchor(curated_evidence, {"forward_pe", "trailing_pe", "pe", "pb", "ev_ebitda", "price_to_sales", "ps", "fcf_yield"}, official_only=True)
    competition_anchor = _has_high_confidence_anchor(curated_evidence, {"market_share", "take_rate", "active_buyers", "retention", "nrr", "gmv", "merchant", "merchant_count"})
    capital_return_anchor = _has_high_confidence_anchor(curated_evidence, {"free_cash_flow", "buybacks", "share_buyback", "dividends"}, official_only=True)
    headline_source = depth["safe_conclusion"] if depth["unsupported_claims"] else summary["headline"]
    headline = _guard_claim_text(
        headline_source,
        valuation_anchor=valuation_anchor,
        competition_anchor=competition_anchor,
        capital_return_anchor=capital_return_anchor,
    )
    recommendation_text = {
        key: _guard_claim_text(
            str(value),
            valuation_anchor=valuation_anchor,
            competition_anchor=competition_anchor,
            capital_return_anchor=capital_return_anchor,
        )
        for key, value in summary["recommendation_text"].items()
    }
    next_action_payload = {
        "title": sanitize_display_text(summary["next_action"].get("title") or "继续补证"),
        "why": sanitize_display_text(summary["next_action"].get("why") or "关键缺口会影响结论强度。"),
        "required_data": [sanitize_display_text(item) for item in list(summary["next_action"].get("required_data") or [])[:4]],
        "decision_impact": sanitize_display_text(summary["next_action"].get("decision_impact") or "补齐后再决定是否升级研究深度。"),
    }
    evidence_gaps = _evidence_gaps(depth, metric_records, competition)
    memo = {
        "verdict": verdict,
        "confidence": {"high": "高", "medium": "中", "low": "低"}.get(judgment.confidence, judgment.confidence),
        "headline": headline,
        "snapshot_dashboard": _snapshot_dashboard_rows(financial_summary, cash_flow_bridge, absolute_valuation, competition),
        "financial_quality": {
            "summary": financial_summary,
            "revenue": _format_metric_value((_best_metric(metric_records, ["revenue"]) or {}).get("value"), (_best_metric(metric_records, ["revenue"]) or {}).get("unit")),
            "margin": _format_metric_value((_best_metric(metric_records, ["gross_margin", "gross_margins", "profit_margins", "net_profit_margin"]) or {}).get("value"), (_best_metric(metric_records, ["gross_margin", "gross_margins", "profit_margins", "net_profit_margin"]) or {}).get("unit")),
            "ocf": _format_metric_value((_best_metric(metric_records, ["operating_cash_flow"]) or {}).get("value"), (_best_metric(metric_records, ["operating_cash_flow"]) or {}).get("unit")),
            "capex": _format_metric_value((_best_metric(metric_records, ["capex", "capital_expenditure"]) or {}).get("value"), (_best_metric(metric_records, ["capex", "capital_expenditure"]) or {}).get("unit")),
            "fcf": _format_metric_value((_best_metric(metric_records, ["free_cash_flow"]) or {}).get("value"), (_best_metric(metric_records, ["free_cash_flow"]) or {}).get("unit")),
            "capex_profile": "Capex 类型未充分披露，需管理层指引补证。",
        },
        "cash_flow_bridge": cash_flow_bridge,
        "valuation": valuation,
        "competition": competition,
        "bull_case": [
            _guard_claim_text(item, valuation_anchor=valuation_anchor, competition_anchor=competition_anchor, capital_return_anchor=capital_return_anchor)
            for item in _bull_case(variables, judgment, cash_flow_bridge)
        ],
        "bear_case": [
            _guard_claim_text(item, valuation_anchor=valuation_anchor, competition_anchor=competition_anchor, capital_return_anchor=capital_return_anchor)
            for item in _bear_case(judgment, top_gaps, cash_flow_bridge)
        ],
        "what_changes_my_mind": _what_changes_my_mind(judgment, valuation, competition, top_gaps),
        "evidence_gaps": evidence_gaps,
        "next_research_actions": _next_research_actions(next_action_payload, top_gaps),
    }

    source_counter = Counter(item.tier.value for item in sources)
    official_count = source_counter.get("official", 0)
    professional_count = source_counter.get("professional", 0)
    weak_count = source_counter.get("content", 0)
    broken_refs = int(judgment.debug_observability.get("BROKEN_EVIDENCE_REF_DROPPED", 0))
    cross_entity_pollution = int(registry.debug_stats.get("OFF_TARGET_SOURCE_DROPPED", 0))

    return {
        "summary_cards": {
            "verdict": verdict,
            "confidence": judgment.confidence,
            "research_position": judgment.positioning or verdict,
            "evidence_count": len(curated_evidence),
            "official_count": official_count,
        },
        "headline": headline,
        "research_memo": memo,
        "next_action": next_action_payload,
        "financial_quality": {
            "summary": financial_summary,
            "variables": top_variables[:3],
        },
        "risk_pressure": {
            "summary": "；".join(str(item.get("text") or "") for item in top_risks[:2])[:180] if top_risks else "当前未形成高置信风险结论，但更可能意味着证据仍不足。",
            "top_risks": top_risks[:3],
        },
        "evidence_quality": {
            "summary": f"当前主链证据共 {len(curated_evidence)} 条，断裂引用为 {broken_refs}，跨主体污染为 {cross_entity_pollution}。",
            "official": official_count,
            "professional": professional_count,
            "weak": weak_count,
            "broken_refs": broken_refs,
            "cross_entity_pollution": cross_entity_pollution,
        },
        "gap_map": {
            "summary": "；".join(str(item.get("title") or item.get("text") or "") for item in top_gaps[:2])[:180] if top_gaps else "关键覆盖缺口相对可控。",
            "top_gaps": top_gaps[:3],
        },
        "top_variables": top_variables,
        "top_risks": top_risks[:3],
        "top_gaps": top_gaps[:3],
        "curated_evidence": curated_evidence[:12],
        "recommendation_text": recommendation_text,
        "source_quality": {
            "official": official_count,
            "professional": professional_count,
            "weak": weak_count,
            "diversity": judgment.confidence_basis.source_diversity,
            "conflict": judgment.confidence_basis.conflict_level,
            "broken_refs": broken_refs,
        },
        "depth_summary": {
            "valuation": depth["valuation_depth"],
            "industry": depth["industry_depth"],
            "moat": depth["moat_depth"],
            "financial_quality": depth["financial_depth"],
        },
        "developer_payload": {
            "report_internal": report_internal,
            "financial_snapshot": financial_snapshot.model_dump() if financial_snapshot is not None else None,
            "raw_sources": [item.model_dump() for item in sources],
            "raw_evidence": [item.model_dump() for item in raw_evidence],
            "debug_stats": {**judgment.debug_observability, **registry.debug_stats},
            "pressure_tests": [item.model_dump() for item in judgment.pressure_tests],
            "auto_research_logs": [item.model_dump() if hasattr(item, "model_dump") else item for item in (auto_research_trace or [])],
            "unsupported_claims": depth["unsupported_claims"],
        },
    }
