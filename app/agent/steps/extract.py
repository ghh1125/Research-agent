from __future__ import annotations

from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.llm_evidence_extractor import extract_structured_evidence_candidates


def extract_evidence(
    topic: Topic,
    questions: list[Question],
    sources: list[Source],
) -> list[Evidence]:
    """Extract main-chain evidence through the LLM structured extractor.

    Source governance and content enrichment happen before this step. This step no longer
    performs keyword-based sentence extraction or official-document rule parsing; it only
    accepts structured, grounded candidates that pass the LLM extractor safety gate.
    """

    evidence: list[Evidence] = []
    seen: set[tuple[str, str | float | int | None, str | None, str | None, str]] = set()
    for source in sources:
        candidates = extract_structured_evidence_candidates(
            source=source,
            topic=topic,
            questions=questions,
            start_index=len(evidence) + 1,
        )
        for candidate in candidates:
            if not candidate.can_enter_main_chain:
                continue
            if candidate.is_truncated or candidate.cross_entity_contamination:
                continue
            key = (
                candidate.metric_name or "",
                candidate.metric_value,
                candidate.period,
                candidate.segment,
                candidate.source_id,
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(candidate.model_copy(update={"id": f"e{len(evidence) + 1}"}))
    return evidence
