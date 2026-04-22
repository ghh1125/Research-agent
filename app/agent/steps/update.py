from __future__ import annotations

from app.models.judgment import ConfidenceBasis, Judgment


def update_judgment(topic_id: str) -> Judgment:
    """Placeholder update step reserved for future iterations."""

    return Judgment(
        topic_id=topic_id,
        conclusion="Update step is not implemented in the MVP yet.",
        conclusion_evidence_ids=[],
        clusters=[],
        risk=[],
        unknown=["No incremental refresh logic yet"],
        evidence_gaps=[],
        confidence="low",
        confidence_basis=ConfidenceBasis(
            source_count=0,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=0,
            has_official_source=False,
            official_evidence_count=0,
            weak_source_only=True,
        ),
        research_actions=[],
    )
