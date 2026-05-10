from __future__ import annotations

import re

from research_flow.schema import EvidenceBundle, ScenarioAnalysis


def _metric(bundle: EvidenceBundle, names: set[str]) -> float | None:
    for item in bundle.evidence:
        key = (item.metric_name or "").lower()
        if key not in names:
            continue
        value = item.metric_value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
            if match:
                return float(match.group(0))
    return None


def _computed_prices(bundle: EvidenceBundle) -> dict[str, float]:
    eps = _metric(bundle, {"eps", "earnings_per_share", "diluted_eps"})
    pe = _metric(bundle, {"pe", "p_e", "forward_pe", "trailing_pe"})
    revenue_per_share = _metric(bundle, {"revenue_per_share", "sales_per_share"})
    ps = _metric(bundle, {"ps", "p_s", "price_to_sales"})

    anchor = None
    method = None
    if eps is not None and pe is not None and pe > 0:
        anchor = eps * pe
        method = "P/E"
    elif revenue_per_share is not None and ps is not None and ps > 0:
        anchor = revenue_per_share * ps
        method = "P/S"

    if anchor is None:
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
