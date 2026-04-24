from __future__ import annotations

from app.services.llm_evidence_extractor import CandidateEvidence
from app.services.llm_evidence_qa import qa_candidate_evidence


def test_grounding_rejects_fake_metric_value_not_present_in_quote() -> None:
    candidate = CandidateEvidence(
        metric_name="revenue",
        metric_value=999,
        unit="million",
        period="FY2025",
        quote="Revenue was RMB996347 million in FY2025.",
        extraction_confidence=0.9,
    )

    result = qa_candidate_evidence(
        source_metadata={"title": "Alibaba IR", "url": "https://example.com"},
        raw_chunk="Revenue was RMB996347 million in FY2025.",
        candidate_evidence=candidate,
    )

    assert not result.keep
    assert result.grounding_score < 0.5


def test_consensus_or_target_is_marked_estimate() -> None:
    candidate = CandidateEvidence(
        metric_name="revenue",
        metric_value=120,
        unit="billion",
        period="FY2026",
        quote="Consensus expects revenue to reach RMB120 billion in FY2026.",
        extraction_confidence=0.92,
    )

    result = qa_candidate_evidence(
        source_metadata={"title": "Street consensus", "url": "https://example.com"},
        raw_chunk="Consensus expects revenue to reach RMB120 billion in FY2026.",
        candidate_evidence=candidate,
    )

    assert result.keep
    assert result.is_estimate


def test_off_target_company_evidence_is_rejected() -> None:
    candidate = CandidateEvidence(
        metric_name="revenue",
        metric_value=23.7,
        unit="billion",
        period="FY2025",
        entity="Adidas",
        quote="Adidas FY2025 revenue reached EUR23.7 billion.",
        extraction_confidence=0.95,
    )

    result = qa_candidate_evidence(
        source_metadata={
            "title": "Adidas Annual Report 2025",
            "url": "https://www.adidas-group.com/en/investors/annual-report-2025.pdf",
            "tier": "official",
        },
        raw_chunk="Adidas FY2025 revenue reached EUR23.7 billion.",
        candidate_evidence=candidate,
        target_profile={"entity": "阿里巴巴", "aliases": ["阿里巴巴", "Alibaba", "BABA"]},
    )

    assert not result.keep
    assert result.reason == "entity_mismatch"
