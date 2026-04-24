from __future__ import annotations

from app.services.llm_research_depth_qa import assess_research_depth


def test_valuation_gap_removes_undervalued_claim() -> None:
    result = assess_research_depth(
        research_questions=[{"framework_type": "valuation", "content": "估值锚点如何"}],
        coverage=[{"framework_type": "valuation", "coverage_level": "uncovered"}],
        curated_evidence=[{"metric_name": "revenue", "quote": "Revenue was RMB996347 million in FY2025."}],
        variables=[{"name": "收入增长", "direction_label": "局部改善"}],
        draft_conclusion="阿里巴巴明显低估，安全边际明确。",
    )

    assert result["valuation_depth"] == "uncovered"
    assert result["unsupported_claims"]
    assert "明显低估" not in result["safe_conclusion"]
    assert "观察清单" in result["safe_conclusion"] or "继续研究" in result["safe_conclusion"]


def test_moat_gap_removes_moat_claim() -> None:
    result = assess_research_depth(
        research_questions=[{"framework_type": "moat", "content": "护城河如何"}],
        coverage=[{"framework_type": "moat", "coverage_level": "uncovered"}],
        curated_evidence=[{"metric_name": "revenue", "quote": "Revenue was RMB996347 million in FY2025."}],
        variables=[{"name": "收入增长", "direction_label": "局部改善"}],
        draft_conclusion="公司护城河成立，竞争优势明确。",
    )

    assert result["moat_depth"] == "uncovered"
    assert "护城河成立" in result["unsupported_claims"]
    assert "护城河成立" not in result["safe_conclusion"]
