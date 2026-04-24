from __future__ import annotations

from collections import defaultdict

_VALUATION_CLAIMS = ["估值低位", "明显低估", "安全边际明确", "undervalued"]
_COMPETITION_CLAIMS = ["竞争优势明确", "行业龙头稳固"]
_MOAT_CLAIMS = ["护城河成立", "护城河已成立"]
_GOVERNANCE_CLAIMS = ["治理风险可控"]


def _critical_gap(label: str) -> dict[str, object]:
    mapping = {
        "valuation": {
            "title": "估值仍需补证",
            "why_it_matters": "没有 forward PE、EV/EBITDA、历史估值区间或同行中位数时，无法判断安全边际。",
            "required_data": ["forward PE", "EV/EBITDA", "历史估值区间", "同行估值中位数"],
            "next_query": "target valuation peer comparison forward PE EV/EBITDA historical band",
            "decision_impact": "这些数据会直接影响是否能从观察清单升级为标准研究或深度跟踪。",
        },
        "industry": {
            "title": "竞争位置仍需补证",
            "why_it_matters": "缺少市场份额、GMV、同行增速或 take rate，无法判断竞争力是否稳定。",
            "required_data": ["market share", "GMV", "peer growth", "take rate"],
            "next_query": "target market share GMV take rate peer growth",
            "decision_impact": "会影响对行业地位、增长持续性和风险压力的判断。",
        },
        "moat": {
            "title": "护城河仍需补证",
            "why_it_matters": "没有留存、商家、用户、流量或转换成本数据时，无法确认优势是否可持续。",
            "required_data": ["retention", "merchant count", "MAU/DAU", "traffic", "switching cost"],
            "next_query": "target retention merchant count MAU DAU switching cost",
            "decision_impact": "会决定能否把短期经营改善解释为长期竞争优势。",
        },
        "governance": {
            "title": "治理与合规仍需补证",
            "why_it_matters": "缺少监管披露、诉讼和合规记录时，无法确认治理风险是否可控。",
            "required_data": ["regulatory filing", "litigation", "compliance action"],
            "next_query": "target regulatory filing litigation compliance risk",
            "decision_impact": "会直接影响风险压力评估和研究优先级。",
        },
    }
    return mapping[label]


def assess_research_depth(
    research_questions: list[dict],
    coverage: list[dict],
    curated_evidence: list[dict],
    variables: list[dict],
    draft_conclusion: str,
) -> dict[str, object]:
    del research_questions, variables
    coverage_map: dict[str, str] = defaultdict(lambda: "uncovered")
    for item in coverage:
        framework = str(item.get("framework_type") or "").lower()
        if framework:
            coverage_map[framework] = str(item.get("coverage_level") or "uncovered")

    metric_names = {str(item.get("metric_name") or "").lower() for item in curated_evidence if item.get("metric_name")}
    valuation_depth = coverage_map["valuation"]
    industry_depth = coverage_map["industry"]
    moat_depth = coverage_map["moat"]
    financial_depth = coverage_map["financial"]
    governance_depth = coverage_map["governance"]

    unsupported_claims: list[str] = []
    if not ({"forward_pe", "pe", "pb", "ev_ebitda"} & metric_names):
        unsupported_claims.extend([claim for claim in _VALUATION_CLAIMS if claim in draft_conclusion])
    if not ({"market_share", "retention", "take_rate"} & metric_names):
        unsupported_claims.extend([claim for claim in _COMPETITION_CLAIMS if claim in draft_conclusion])
    if not ({"retention", "take_rate", "merchant_count", "mau", "dau"} & metric_names):
        unsupported_claims.extend([claim for claim in _MOAT_CLAIMS if claim in draft_conclusion])
    if not {"regulatory_filing", "litigation", "compliance"} & metric_names:
        unsupported_claims.extend([claim for claim in _GOVERNANCE_CLAIMS if claim in draft_conclusion])

    dashboard_gaps: list[str] = []
    critical_gaps: list[dict[str, object]] = []
    for label, depth in [
        ("valuation", valuation_depth),
        ("industry", industry_depth),
        ("moat", moat_depth),
        ("financial_quality", financial_depth),
    ]:
        if depth != "covered":
            dashboard_gaps.append(f"{label}={depth}")
    for label, depth in [
        ("valuation", valuation_depth),
        ("industry", industry_depth),
        ("moat", moat_depth),
        ("governance", governance_depth),
    ]:
        if depth != "covered":
            critical_gaps.append(_critical_gap(label))

    if unsupported_claims:
        safe_conclusion = "当前证据尚不足以支持明确投资判断，建议先列入观察清单并继续补充核心数据验证。"
    elif any(depth == "uncovered" for depth in [valuation_depth, industry_depth, moat_depth]):
        safe_conclusion = "当前已有部分经营与财务线索，但估值、竞争位置或护城河验证仍不充分，更适合作为观察标的继续跟踪。"
    else:
        safe_conclusion = draft_conclusion

    return {
        "valuation_depth": valuation_depth,
        "industry_depth": industry_depth,
        "moat_depth": moat_depth,
        "financial_depth": financial_depth,
        "unsupported_claims": list(dict.fromkeys(unsupported_claims)),
        "dashboard_gaps": dashboard_gaps[:4],
        "critical_gaps": critical_gaps[:3],
        "safe_conclusion": safe_conclusion,
    }
