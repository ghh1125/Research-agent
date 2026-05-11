from __future__ import annotations

import json
import re

from research_flow.schema import EvidenceBundle, ScenarioAnalysis

# Expanded name sets covering Evidence metric_name variants and yfinance camelCase keys
_PE_NAMES = {
    "pe", "p_e", "forward_pe", "trailing_pe", "forwardpe", "trailingpe",
    "pe_ratio", "price_to_earnings", "price_earnings",
    "trailingPE", "forwardPE",
}
_EPS_NAMES = {
    "eps", "earnings_per_share", "diluted_eps", "basic_eps",
    "trailing_eps", "trailingeps", "diluted_earnings_per_share",
    "trailingEps", "forwardEps",
}
_PS_NAMES = {
    "ps", "p_s", "price_to_sales", "priceToSalesTrailingI2Months",
}
_REVENUE_PER_SHARE_NAMES = {
    "revenue_per_share", "sales_per_share", "revenuePerShare",
}


def _metric(bundle: EvidenceBundle, names: set[str]) -> float | None:
    """Find a numeric metric from structured Evidence items."""
    lower_names = {n.lower() for n in names}
    for item in bundle.evidence:
        key = (item.metric_name or "").lower().replace("-", "_")
        if key not in lower_names:
            continue
        value = item.metric_value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
            if match:
                return float(match.group(0))
    return None


def _metric_from_valuation_artifact(bundle: EvidenceBundle, names: set[str]) -> float | None:
    """Directly parse ## valuation_metrics JSON section from YFinanceValuationTool artifacts."""
    lower_names = {n.lower() for n in names}
    for artifact in bundle.artifacts:
        if artifact.category not in {"valuation", "market_data"}:
            continue
        idx = artifact.content.find("## valuation_metrics\n")
        if idx < 0:
            continue
        section_start = idx + len("## valuation_metrics\n")
        section_end = artifact.content.find("\n##", section_start)
        raw = artifact.content[section_start:section_end if section_end > 0 else None].strip()
        try:
            data: dict = json.loads(raw)
        except Exception:
            continue
        for key, val in data.items():
            if key.lower() in lower_names and isinstance(val, (int, float)) and val > 0:
                return float(val)
    return None


def _metric_from_income_statement(bundle: EvidenceBundle) -> float | None:
    """Extract EPS from income statement CSV produced by YFinanceFinancialStatementsTool."""
    eps_labels = {"diluted eps", "basic eps", "earnings per share"}
    for artifact in bundle.artifacts:
        if artifact.category != "financial_statements":
            continue
        in_income = False
        for line in artifact.content.splitlines():
            lower = line.lower()
            if "income_statement" in lower or "## income" in lower:
                in_income = True
                continue
            if line.startswith("##"):
                in_income = False
                continue
            if not in_income:
                continue
            if any(label in lower for label in eps_labels):
                parts = line.split(",")
                for part in parts[1:4]:
                    stripped = part.strip()
                    if not stripped:
                        continue
                    try:
                        val = float(stripped)
                        # EPS is typically 0.01–1000; filter out total revenue rows
                        if 0 < abs(val) < 10000:
                            return val
                    except ValueError:
                        continue
    return None


def _computed_prices(bundle: EvidenceBundle) -> dict[str, float]:
    # 1. Try structured Evidence items first
    eps = _metric(bundle, _EPS_NAMES)
    pe = _metric(bundle, _PE_NAMES)

    # 2. Try valuation artifact JSON section
    if pe is None:
        pe = _metric_from_valuation_artifact(bundle, _PE_NAMES)
    if eps is None:
        eps = _metric_from_valuation_artifact(bundle, _EPS_NAMES)

    # 3. Try income statement CSV for EPS
    if eps is None:
        eps = _metric_from_income_statement(bundle)

    # 4. Revenue-per-share / P/S as fallback when P/E data is unavailable
    revenue_per_share = _metric(bundle, _REVENUE_PER_SHARE_NAMES) or _metric_from_valuation_artifact(bundle, _REVENUE_PER_SHARE_NAMES)
    ps = _metric(bundle, _PS_NAMES) or _metric_from_valuation_artifact(bundle, _PS_NAMES)

    anchor: float | None = None
    method: str | None = None

    if eps is not None and pe is not None and pe > 0:
        anchor = eps * pe
        method = "P/E"
    elif revenue_per_share is not None and ps is not None and ps > 0:
        anchor = revenue_per_share * ps
        method = "P/S"

    if anchor is None or method is None:
        return {}

    return {
        "bear": round(anchor * 0.8, 2),
        "base": round(anchor, 2),
        "bull": round(anchor * 1.2, 2),
        "_method": method,  # type: ignore[dict-item]
    }


def enrich_scenario_analysis(scenario: ScenarioAnalysis, bundle: EvidenceBundle) -> ScenarioAnalysis:
    computed = _computed_prices(bundle)
    if not computed:
        methodologies = sorted(set(scenario.valuation_methodologies + ["DCF", "可比公司", "历史估值"]))
        return scenario.model_copy(update={"valuation_methodologies": methodologies})

    method = str(computed.pop("_method"))
    table = [
        {"scenario": "bear", "target_price": computed["bear"], "assumption": f"{method} anchor -20%"},
        {"scenario": "base", "target_price": computed["base"], "assumption": f"{method} anchor"},
        {"scenario": "bull", "target_price": computed["bull"], "assumption": f"{method} anchor +20%"},
    ]
    return scenario.model_copy(
        update={
            "target_price_range": f"{computed['bear']}-{computed['bull']}",
            "margin_of_safety": scenario.margin_of_safety or f"低于 base 情景 {computed['base']} 时才有安全边际。",
            "valuation_methodologies": sorted(set(scenario.valuation_methodologies + [method, "DCF", "可比公司", "历史估值"])),
            "scenario_table": table,
            "computed_target_prices": computed,
        }
    )
