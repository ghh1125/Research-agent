from __future__ import annotations

from app.agent.steps.report import curate_evidence_for_display, generate_report
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


def test_report_curates_evidence_to_top_12_and_deduplicates_metrics() -> None:
    topic = Topic(
        id="topic_2",
        query="我想投资阿里巴巴，是否值得进一步研究",
        entity="阿里巴巴",
        topic="阿里巴巴研究价值",
        goal="判断是否继续研究",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="HK",
    )
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    sources = []
    evidence = []
    for idx in range(1, 15):
        source_id = f"s{idx}"
        sources.append(
            Source(
                id=source_id,
                question_id="q1",
                title=f"Official source {idx}",
                url=f"https://ir.example.com/{idx}",
                source_type="company",
                provider="fixture",
                source_origin_type="company_ir",
                credibility_tier="tier1",
                tier=SourceTier.TIER1,
                source_score=0.9,
                content="official content",
            )
        )
        evidence.append(
            Evidence(
                id=f"e{idx}",
                topic_id=topic.id,
                question_id="q1",
                source_id=source_id,
                content=f"Revenue was RMB{100+idx} million in FY2025.",
                evidence_type="data",
                source_tier="official",
                evidence_score=0.9 - idx * 0.01,
                metric_name="revenue",
                metric_value=100 + idx,
                unit="million",
                period="FY2025",
            )
        )
    evidence.extend(
        [
            Evidence(
                id="e20",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="Revenue was RMB999 million in FY2025.",
                evidence_type="data",
                source_tier="official",
                evidence_score=0.95,
                metric_name="revenue",
                metric_value=999,
                unit="million",
                period="FY2025",
            ),
            Evidence(
                id="e21",
                topic_id=topic.id,
                question_id="q1",
                source_id="s2",
                content="Operating cash flow was RMB120 million in FY2025.",
                evidence_type="data",
                source_tier="official",
                evidence_score=0.93,
                metric_name="operating_cash_flow",
                metric_value=120,
                unit="million",
                period="FY2025",
            ),
        ]
    )
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="值得继续标准研究。",
        conclusion_evidence_ids=["e20", "e21"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="medium",
        confidence_basis=ConfidenceBasis(source_count=3, source_diversity="high", conflict_level="none", evidence_gap_level="low", effective_evidence_count=8, has_official_source=True, official_evidence_count=8),
        research_actions=[],
    )

    curated = curate_evidence_for_display(evidence, sources)
    report = generate_report(topic, questions, sources, evidence, [], [], judgment)

    assert len(curated) <= 12
    assert len(report.evidence) <= 12
    revenue_ids = [item.id for item in curated if item.metric_name == "revenue" and item.period == "FY2025"]
    assert revenue_ids
    assert "e20" in revenue_ids


def test_report_never_renders_evidence_not_found_or_registry_external_evidence() -> None:
    topic = Topic(
        id="topic_registry_report",
        query="研究阿里巴巴",
        entity="阿里巴巴",
        topic="阿里巴巴研究价值",
        goal="判断是否继续研究",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="HK",
    )
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    sources = [
        Source(
            id="s1",
            question_id="q1",
            title="Alibaba IR",
            url="https://www.alibabagroup.com/ir-results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            credibility_tier="tier1",
            tier=SourceTier.TIER1,
            source_score=0.94,
            content="official content",
        )
    ]
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Revenue was RMB996347 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.9,
            metric_name="revenue",
            metric_value=996347,
            unit="million",
            period="FY2025",
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Invalid broken evidence should never be displayed.",
            evidence_type="claim",
            source_tier="official",
            can_enter_main_chain=False,
        ),
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="继续研究，但只基于有效主链证据。",
        conclusion_evidence_ids=["e_missing", "e2", "e1"],
        verified_facts=["revenue FY2025: Revenue was RMB996347 million in FY2025."],
        probable_inferences=["当前结论只应绑定 e1。"],
        pending_assumptions=["估值与行业竞争仍待补证。"],
        clusters=[],
        risk=[],
        pressure_tests=[],
        unknown=[],
        evidence_gaps=[],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="low",
            effective_evidence_count=1,
            has_official_source=True,
            official_evidence_count=1,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, sources, evidence, [], [], judgment)

    assert "证据不存在" not in report.markdown
    assert [item.id for item in report.evidence] == ["e1"]
    curated_ids = [item["id"] for item in report.report_display["curated_evidence"]]
    assert curated_ids == ["e1"]
