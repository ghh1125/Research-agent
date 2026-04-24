from __future__ import annotations

from app.models.evidence import Evidence
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.evidence_registry import build_evidence_registry


def test_registry_filters_non_main_chain_evidence_and_missing_ids() -> None:
    registry = build_evidence_registry(
        [
            Evidence(
                id="e1",
                topic_id="topic_1",
                question_id="q1",
                source_id="s1",
                content="Revenue was RMB100 million in FY2025.",
                evidence_type="data",
                source_tier="official",
                metric_name="revenue",
                metric_value=100,
                period="FY2025",
            ),
            Evidence(
                id="e2",
                topic_id="topic_1",
                question_id="q1",
                source_id="s1",
                content="Truncated quote",
                evidence_type="data",
                source_tier="official",
                is_truncated=True,
            ),
            Evidence(
                id="e3",
                topic_id="topic_1",
                question_id="q1",
                source_id="s1",
                content="Noisy quote",
                evidence_type="claim",
                source_tier="professional",
                is_noise=True,
            ),
        ]
    )

    assert registry.total_count == 3
    assert registry.displayable_count == 1
    assert registry.has("e1")
    assert not registry.has("e2")
    assert registry.filter_existing(["e_missing", "e1", "e2", "e1"]) == ["e1"]


def test_registry_project_for_display_never_returns_registry_external_evidence() -> None:
    registry = build_evidence_registry(
        [
            Evidence(
                id="e1",
                topic_id="topic_1",
                question_id="q1",
                source_id="s1",
                content="Operating cash flow was RMB50 million in FY2025.",
                evidence_type="data",
                source_tier="official",
                evidence_score=0.9,
                metric_name="operating_cash_flow",
                metric_value=50,
                period="FY2025",
            )
        ]
    )

    projected = registry.project_for_display(["e_missing", "e1", "e_missing_2"])

    assert [item.id for item in projected] == ["e1"]


def test_registry_rejects_off_target_annual_report_for_target_company() -> None:
    topic = Topic(
        id="topic_alibaba",
        query="研究阿里巴巴是否值得继续研究",
        entity="阿里巴巴",
        topic="阿里巴巴研究",
        goal="判断是否值得继续研究",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="US",
    )
    adidas_source = Source(
        id="s1",
        question_id="q1",
        title="Adidas Annual Report 2025",
        url="https://www.adidas-group.com/en/investors/annual-report-2025.pdf",
        source_type="report",
        provider="fixture",
        source_origin_type="company_ir",
        credibility_tier="tier1",
        tier=SourceTier.TIER1,
        source_score=0.95,
        content="Adidas annual report with FY2025 revenue and margin details.",
    )
    registry = build_evidence_registry(
        [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="Adidas FY2025 revenue reached EUR 23.7 billion.",
                evidence_type="data",
                source_tier="official",
                metric_name="revenue",
                metric_value=23.7,
                unit="billion",
                period="FY2025",
                entity="Adidas",
            )
        ],
        topic=topic,
        sources=[adidas_source],
    )

    assert not registry.has("e1")
    assert registry.debug_stats["ENTITY_MISMATCH_DROPPED"] == 1
    assert registry.debug_stats["OFF_TARGET_SOURCE_DROPPED"] == 1
    assert registry.debug_stats["REGISTRY_REJECT_REASONS"]["OFF_TARGET_REPORT"] == 1
