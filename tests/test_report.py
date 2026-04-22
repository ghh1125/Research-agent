from __future__ import annotations

from app.agent.steps.report import generate_report
from app.models.evidence import Evidence
from app.models.judgment import (
    ConfidenceBasis,
    EvidenceGap,
    InvestmentDecision,
    Judgment,
    PeerContext,
    PressureTest,
    ResearchAction,
    ResearchScope,
)
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic


def test_report_renders_user_facing_labels_without_engineering_keys() -> None:
    topic = Topic(
        id="topic_1",
        query="研究英伟达研究价值",
        entity="英伟达",
        topic="英伟达研究价值",
        goal="判断是否进入深度研究",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="US",
    )
    questions = [
        Question(
            id="q1",
            topic_id=topic.id,
            content="英伟达收入增长和利润率是否可持续？",
            priority=1,
            framework_type="financial",
            coverage_level="partial",
        )
    ]
    source = Source(
        id="s1",
        question_id="q1",
        title="英伟达结构化金融数据快照",
        url="https://finance.example/NVDA",
        source_type="other",
        provider="finnhub",
        source_origin_type="professional_media",
        credibility_tier="tier2",
        tier=SourceTier.TIER2,
        source_score=0.72,
        content="英伟达金融快照。",
    )
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="英伟达实时金融快照显示，营收同比增速为120.1%，期间为TTM。",
            evidence_type="data",
            source_tier="professional",
            evidence_score=0.9,
        )
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="需要继续补证后判断。",
        conclusion_evidence_ids=["e1"],
        clusters=[],
        risk=[],
        pressure_tests=[
            PressureTest(
                test_id="pt1",
                attack_type="fragile_evidence",
                target="收入增速持续性",
                fragile_evidence_ids=["e1"],
                counter_evidence_ids=[],
                weakness="实时快照不能替代财报口径。",
                counter_conclusion="若后续季度增速回落，结论需要下修。",
                severity="high",
            )
        ],
        unknown=[],
        evidence_gaps=[EvidenceGap(question_id="q1", text="缺少分业务收入和毛利率趋势。", importance="high")],
        confidence="low",
        research_confidence="low",
        signal_confidence="medium",
        source_confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="partial",
            evidence_gap_level="high",
            effective_evidence_count=1,
            official_evidence_count=0,
            weak_source_only=True,
        ),
        research_actions=[
            ResearchAction(
                id="a1",
                priority="high",
                question="补全年报口径的收入、毛利率和现金流。",
                objective="补全财务变量",
                reason="当前只有实时快照。",
                required_data=["营业收入", "毛利率", "经营现金流"],
                search_query="NVDA annual report revenue gross margin operating cash flow",
                query_templates=["NVDA annual report revenue gross margin operating cash flow"],
                target_sources=["公司年报", "SEC 10-K"],
                source_targets=["official_disclosure"],
                status="pending",
            )
        ],
        research_scope=ResearchScope(
            estimated_hours="2-4h",
            urgency="high",
            depth_recommendation="deep_dive",
            reason="需要补齐官方财报证据。",
        ),
        peer_context=PeerContext(
            required=True,
            status="needs_research",
            peer_entities=["AMD"],
            evidence_ids=["e1"],
            comparison_rows=[],
            note="peer_context=needs_research",
        ),
        investment_decision=InvestmentDecision(
            decision_target="watchlist_entry",
            decision="deep_dive_candidate",
            rationale="趋势强但证据仍不完整。",
            evidence_ids=["e1"],
            decision_basis=["watchlist_entry", "deep_dive_candidate", "confidence=low"],
            trigger_to_revisit="获得官方年报与同行对比后复盘。",
            caveat="当前结论不能直接作为投资建议。",
        ),
    )

    report = generate_report(topic, questions, [source], evidence, [], [], judgment)

    raw_tokens = [
        "source score=",
        "weak_source_only",
        "watchlist_entry",
        "deep_dive_candidate",
        "coverage_level",
        "listed_company",
        "pending_review",
        "fragile_evidence",
        "peer_context=needs_research",
    ]
    for token in raw_tokens:
        assert token not in report.markdown
    assert "上市公司" in report.markdown
    assert "美股" in report.markdown
    assert "来源分=0.72" in report.markdown
    assert "观察清单" in report.markdown
    assert "建议进入深度研究" in report.markdown
    assert "是否仅依赖弱来源=是" in report.markdown
