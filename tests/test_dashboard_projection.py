from __future__ import annotations

from app.agent.steps.report import generate_report
from app.models.evidence import Evidence
from app.models.judgment import ConfidenceBasis, EvidenceGap, Judgment, ResearchAction, ResearchScope
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.models.variable import ResearchVariable


def _topic() -> Topic:
    return Topic(
        id="topic_dashboard",
        query="我想投资阿里巴巴，是否值得进一步研究",
        entity="阿里巴巴",
        topic="阿里巴巴研究价值",
        goal="判断是否值得继续研究",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="HK",
    )


def test_dashboard_view_generation_is_backend_complete() -> None:
    topic = _topic()
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    sources = [
        Source(
            id="s1",
            question_id="q1",
            title="Alibaba IR Results",
            url="https://www.alibabagroup.com/ir-results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            credibility_tier="tier1",
            tier=SourceTier.TIER1,
            source_score=0.95,
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
            evidence_score=0.95,
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
            content="Operating cash flow was RMB163509 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.94,
            metric_name="operating_cash_flow",
            metric_value=163509,
            unit="million",
            period="FY2025",
        ),
    ]
    variables = [
        ResearchVariable(
            name="收入增长",
            category="financial",
            value_summary="Revenue was RMB996347 million in FY2025.",
            direction="improving",
            direction_label="局部改善",
            evidence_ids=["e1"],
        )
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="当前证据尚不足以支持明确投资判断，建议先列入观察清单并继续补充核心数据验证。",
        conclusion_evidence_ids=["e1", "e2"],
        verified_facts=["Revenue FY2025: Revenue was RMB996347 million in FY2025."],
        probable_inferences=["经营现金流具备一定支撑，但估值安全边际仍待验证。"],
        pending_assumptions=["估值与行业竞争仍待补证。"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[EvidenceGap(question_id="q2", text="缺少估值锚点和同行对比", importance="high")],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=2,
            has_official_source=True,
            official_evidence_count=2,
        ),
        research_actions=[
            ResearchAction(
                id="a1",
                priority="high",
                question="补估值",
                objective="补齐估值锚点和同行对比",
                reason="估值缺口直接影响结论强度",
                required_data=["PE", "PB", "同行估值"],
                query_templates=["{entity} valuation peer comparison"],
                source_targets=["recognized data providers"],
            )
        ],
        positioning="观察清单",
        research_scope=ResearchScope(
            estimated_hours="2-4h",
            urgency="high",
            depth_recommendation="standard_research",
            reason="估值缺口仍未关闭。",
        ),
    )

    report = generate_report(topic, questions, sources, evidence, variables, [], judgment)
    dashboard = report.report_display

    assert set(dashboard.keys()) >= {
        "summary_cards",
        "headline",
        "next_action",
        "research_memo",
        "financial_quality",
        "risk_pressure",
        "evidence_quality",
        "gap_map",
        "top_variables",
        "top_risks",
        "top_gaps",
        "curated_evidence",
        "recommendation_text",
        "source_quality",
        "depth_summary",
        "developer_payload",
    }
    assert dashboard["summary_cards"]["evidence_count"] <= 12
    assert "official_count" in dashboard["summary_cards"]
    assert set(dashboard["research_memo"].keys()) >= {
        "verdict",
        "confidence",
        "headline",
        "snapshot_dashboard",
        "financial_quality",
        "cash_flow_bridge",
        "valuation",
        "competition",
        "bull_case",
        "bear_case",
        "what_changes_my_mind",
        "evidence_gaps",
        "next_research_actions",
    }
    assert set(dashboard["recommendation_text"].keys()) == {
        "what_we_know",
        "what_we_do_not_know",
        "why_this_verdict",
        "next_research_plan",
    }
    assert dashboard["developer_payload"]["report_internal"]["registry_displayable"] >= 1


def test_dashboard_view_curated_evidence_stays_capped() -> None:
    topic = _topic()
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    sources = []
    evidence = []
    for idx in range(14):
        source_id = f"s{idx}"
        sources.append(
            Source(
                id=source_id,
                question_id="q1",
                title=f"Source {idx}",
                url=f"https://example.com/{idx}",
                source_type="report",
                provider="fixture",
                source_origin_type="professional_media",
                credibility_tier="tier2",
                tier=SourceTier.TIER2,
                source_score=0.8,
                content="professional content",
            )
        )
        evidence.append(
            Evidence(
                id=f"e{idx}",
                topic_id=topic.id,
                question_id="q1",
                source_id=source_id,
                content=f"Metric {idx} was {idx}.",
                evidence_type="data",
                source_tier="professional",
                evidence_score=0.8,
                metric_name=f"metric_{idx}",
                metric_value=idx,
                period="FY2025",
            )
        )
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="继续观察。",
        conclusion_evidence_ids=["e0"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="low",
        confidence_basis=ConfidenceBasis(
            source_count=14,
            source_diversity="high",
            conflict_level="none",
            evidence_gap_level="medium",
            effective_evidence_count=14,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, sources, evidence, [], [], judgment)

    assert len(report.report_display["curated_evidence"]) <= 12


def test_dashboard_view_hides_raw_payload_outside_developer_section() -> None:
    topic = _topic()
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    source = Source(
        id="s1",
        question_id="q1",
        title="Alibaba IR Results",
        url="https://www.alibabagroup.com/ir-results",
        source_type="company",
        provider="fixture",
        source_origin_type="company_ir",
        credibility_tier="tier1",
        tier=SourceTier.TIER1,
        source_score=0.95,
        content="official content",
    )
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Revenue was RMB996347 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.95,
            metric_name="revenue",
            metric_value=996347,
            unit="million",
            period="FY2025",
        )
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="继续观察。",
        conclusion_evidence_ids=["e1"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="low",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="medium",
            effective_evidence_count=1,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, [source], evidence, [], [], judgment)
    dashboard = report.report_display

    assert "raw_sources" not in dashboard
    assert "raw_evidence" not in dashboard
    assert "developer_payload" in dashboard
    assert "raw_sources" in dashboard["developer_payload"]
    assert "raw_evidence" in dashboard["developer_payload"]


def test_dashboard_view_filters_off_target_evidence_from_curated_display() -> None:
    topic = _topic()
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    sources = [
        Source(
            id="s1",
            question_id="q1",
            title="Alibaba IR Results",
            url="https://www.alibabagroup.com/ir-results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            credibility_tier="tier1",
            tier=SourceTier.TIER1,
            source_score=0.95,
            content="Alibaba official content",
        ),
        Source(
            id="s2",
            question_id="q1",
            title="Adidas Annual Report 2025",
            url="https://www.adidas-group.com/en/investors/annual-report-2025.pdf",
            source_type="report",
            provider="fixture",
            source_origin_type="company_ir",
            credibility_tier="tier1",
            tier=SourceTier.TIER1,
            source_score=0.95,
            content="Adidas official annual report",
        ),
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
            evidence_score=0.95,
            metric_name="revenue",
            metric_value=996347,
            unit="million",
            period="FY2025",
            entity="Alibaba",
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s2",
            content="Adidas FY2025 revenue reached EUR23.7 billion.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.95,
            metric_name="revenue",
            metric_value=23.7,
            unit="billion",
            period="FY2025",
            entity="Adidas",
        ),
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="继续观察。",
        conclusion_evidence_ids=["e1", "e2"],
        verified_facts=["Revenue FY2025: Revenue was RMB996347 million in FY2025."],
        probable_inferences=["经营现金流具备一定支撑，但估值安全边际仍待验证。"],
        pending_assumptions=["估值与行业竞争仍待补证。"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=2,
            source_diversity="medium",
            conflict_level="none",
            evidence_gap_level="medium",
            effective_evidence_count=1,
            has_official_source=True,
            official_evidence_count=1,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, sources, evidence, [], [], judgment)
    dashboard = report.report_display

    assert all("Adidas" not in (item.get("quote") or "") for item in dashboard["curated_evidence"])
    assert all("adidas" not in (item.get("url") or "").lower() for item in dashboard["curated_evidence"])


def test_research_memo_flags_capex_period_misalignment_and_missing_valuation_context() -> None:
    topic = _topic()
    questions = [
        Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered"),
        Question(id="q2", topic_id=topic.id, content="估值是否合理", priority=1, framework_type="valuation", coverage_level="uncovered"),
        Question(id="q3", topic_id=topic.id, content="竞争位置如何", priority=1, framework_type="industry", coverage_level="partial"),
    ]
    source = Source(
        id="s1",
        question_id="q1",
        title="Alibaba IR Results",
        url="https://www.alibabagroup.com/ir-results",
        source_type="company",
        provider="fixture",
        source_origin_type="company_ir",
        credibility_tier="tier1",
        tier=SourceTier.TIER1,
        source_score=0.95,
        content="official content",
    )
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Operating cash flow was RMB163509 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.95,
            metric_name="operating_cash_flow",
            metric_value=163509,
            unit="million",
            period="FY2025",
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Capital expenditure was RMB32000 million in Q4 FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.94,
            metric_name="capex",
            metric_value=32000,
            unit="million",
            period="FY2025Q4",
        ),
        Evidence(
            id="e3",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Free cash flow was RMB15200 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.93,
            metric_name="free_cash_flow",
            metric_value=15200,
            unit="million",
            period="FY2025",
        ),
        Evidence(
            id="e4",
            topic_id=topic.id,
            question_id="q3",
            source_id="s1",
            content="Market share remained 18% in FY2025.",
            evidence_type="data",
            source_tier="professional",
            evidence_score=0.8,
            metric_name="market_share",
            metric_value=18,
            unit="%",
            period="FY2025",
        ),
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="当前仍需继续研究。",
        conclusion_evidence_ids=["e1", "e2", "e3", "e4"],
        verified_facts=["FY2025经营现金流仍为正。"],
        probable_inferences=["自由现金流覆盖能力需要结合资本回报继续确认。"],
        pending_assumptions=["估值锚点与同行对比仍待补证。"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[EvidenceGap(question_id="q2", text="缺少 forward PE、EV/EBITDA 和同行估值中位数", importance="high")],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=4,
            has_official_source=True,
            official_evidence_count=3,
        ),
        research_actions=[
            ResearchAction(
                id="a1",
                priority="high",
                question="补估值",
                objective="补齐估值锚点和同行对比",
                reason="估值缺口会直接影响判断",
                required_data=["forward PE", "EV/EBITDA", "peer median"],
                query_templates=["{entity} valuation peer comparison"],
                source_targets=["recognized data providers"],
            )
        ],
    )

    report = generate_report(topic, questions, [source], evidence, [], [], judgment)
    memo = report.report_display["research_memo"]

    assert "资本开支相关证据周期不一致" in memo["cash_flow_bridge"]["commentary"]
    assert memo["valuation"]["absolute"]["assessment"] == "参照系缺失"
    assert any("valuation missing" in gap.lower() or "估值" in gap for gap in memo["evidence_gaps"])


def test_dashboard_humanizes_cash_flow_and_blocks_cheap_or_moat_claims_without_reference() -> None:
    topic = _topic()
    questions = [
        Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered"),
        Question(id="q2", topic_id=topic.id, content="估值是否合理", priority=1, framework_type="valuation", coverage_level="partial"),
        Question(id="q3", topic_id=topic.id, content="竞争位置如何", priority=1, framework_type="industry", coverage_level="partial"),
    ]
    source = Source(
        id="s1",
        question_id="q1",
        title="Alibaba IR Results",
        url="https://www.alibabagroup.com/ir-results",
        source_type="company",
        provider="fixture",
        source_origin_type="company_ir",
        credibility_tier="tier1",
        tier=SourceTier.TIER1,
        source_score=0.95,
        content="official content",
    )
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Revenue was RMB996347 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.95,
            metric_name="revenue",
            metric_value=996347,
            unit="CNY million",
            period="FY2025",
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Operating cash flow was RMB163509 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.94,
            metric_name="operating_cash_flow",
            metric_value=163509,
            unit="CNY million",
            period="FY2025",
        ),
        Evidence(
            id="e3",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Free cash flow decreased to RMB77540 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.93,
            metric_name="free_cash_flow",
            metric_value=77540,
            unit="CNY million",
            period="FY2025",
        ),
        Evidence(
            id="e4",
            topic_id=topic.id,
            question_id="q2",
            source_id="s1",
            content="Forward P/E was 10.5x in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.92,
            metric_name="forward_pe",
            metric_value=10.5,
            unit="x",
            period="FY2025",
        ),
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="当前仍需继续研究。",
        conclusion_evidence_ids=["e1", "e2", "e3", "e4"],
        verified_facts=["FY2025收入约 9,963 亿元人民币，经营现金流仍为正。"],
        probable_inferences=["自由现金流同比承压。"],
        pending_assumptions=["估值参照系和竞争位置仍待补证。"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[EvidenceGap(question_id="q2", text="缺少历史估值区间与同行估值中位数", importance="high")],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high",
            effective_evidence_count=4,
            has_official_source=True,
            official_evidence_count=4,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, [source], evidence, [], [], judgment)
    dashboard = report.report_display
    memo = dashboard["research_memo"]
    visible_dashboard = {key: value for key, value in dashboard.items() if key != "developer_payload"}
    text_blob = str(visible_dashboard) + str(memo)

    assert memo["cash_flow_bridge"]["status"] != "Improving"
    assert "承压但未失控" in memo["cash_flow_bridge"]["commentary"]
    assert memo["valuation"]["absolute"]["assessment"] == "参照系缺失"
    assert "暂不能判断是否便宜" in memo["valuation"]["absolute"]["summary"]
    assert memo["competition"]["summary"] == "竞争位置证据不足，暂无法判断护城河强度。"
    assert "Revenue=" not in text_blob
    assert "CNY million" not in text_blob
    assert "Under Review" not in text_blob
    assert "Improving" not in text_blob
    assert "Healthy" not in text_blob
    assert "Weak moat" not in text_blob
    assert "cheap valuation" not in text_blob
    assert "logic_gap" not in text_blob
    assert "broken refs" not in text_blob


def test_dashboard_marks_capital_return_coverage_as_pending_without_distribution_data() -> None:
    topic = _topic()
    questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial", coverage_level="covered")]
    source = Source(
        id="s1",
        question_id="q1",
        title="Alibaba IR Results",
        url="https://www.alibabagroup.com/ir-results",
        source_type="company",
        provider="fixture",
        source_origin_type="company_ir",
        credibility_tier="tier1",
        tier=SourceTier.TIER1,
        source_score=0.95,
        content="official content",
    )
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Operating cash flow was RMB163509 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.94,
            metric_name="operating_cash_flow",
            metric_value=163509,
            unit="CNY million",
            period="FY2025",
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Capital expenditure was RMB85970 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.94,
            metric_name="capex",
            metric_value=85970,
            unit="CNY million",
            period="FY2025",
        ),
        Evidence(
            id="e3",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="Free cash flow was RMB77540 million in FY2025.",
            evidence_type="data",
            source_tier="official",
            evidence_score=0.93,
            metric_name="free_cash_flow",
            metric_value=77540,
            unit="CNY million",
            period="FY2025",
        ),
    ]
    judgment = Judgment(
        topic_id=topic.id,
        conclusion="继续观察。",
        conclusion_evidence_ids=["e1", "e2", "e3"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="medium",
        confidence_basis=ConfidenceBasis(
            source_count=1,
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="medium",
            effective_evidence_count=3,
        ),
        research_actions=[],
    )

    report = generate_report(topic, questions, [source], evidence, [], [], judgment)
    bridge = report.report_display["research_memo"]["cash_flow_bridge"]
    coverage_row = next(item for item in bridge["rows"] if item["metric"] == "资本回报覆盖")

    assert coverage_row["status"] == "覆盖能力待验证"
    assert "Improving" not in str(bridge)
