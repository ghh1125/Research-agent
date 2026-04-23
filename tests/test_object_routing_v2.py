from __future__ import annotations

from unittest.mock import patch

from app.agent.steps.define import define_problem
from app.agent.steps.decompose import decompose_problem
from app.agent.steps.investment import apply_investment_layer
from app.agent.steps.reason import reason_and_generate
from app.agent.pipeline import _mark_question_coverage
from app.agent.utils.query_builder import build_fact_queries
from app.models.evidence import Evidence
from app.models.financial import FinancialSnapshot
from app.models.judgment import ConfidenceBasis, Judgment
from app.models.question import Question
from app.models.topic import Topic
from app.services.evidence_engine import classify_source_origin, classify_tier_from_origin


def test_define_classifies_common_research_objects() -> None:
    with patch("app.agent.steps.define.call_llm", side_effect=RuntimeError("unit")):
        huawei = define_problem("华为股票研究价值")
        ai_agent = define_problem("AI Agent 行业是否值得研究")
        credit = define_problem("某城投债主体是否值得继续研究")
        gold = define_problem("黄金价格是否值得建立跟踪")

    assert huawei.entity == "华为"
    assert huawei.research_object_type == "private_company"
    assert huawei.listing_status == "private"
    assert ai_agent.research_object_type == "industry_theme"
    assert credit.research_object_type == "credit_issuer"
    assert gold.research_object_type == "commodity"


def test_decompose_templates_are_object_specific_and_not_meta_questions() -> None:
    listed = Topic(
        id="t1",
        query="英伟达是否值得进一步研究",
        entity="英伟达",
        topic="英伟达研究价值",
        goal="判断研究价值",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="US",
    )
    private = listed.model_copy(
        update={
            "id": "t2",
            "query": "华为股票研究价值",
            "entity": "华为",
            "topic": "华为研究价值",
            "research_object_type": "private_company",
            "listing_status": "private",
            "market_type": "private",
        }
    )
    industry = listed.model_copy(
        update={
            "id": "t3",
            "query": "AI Agent 行业是否值得研究",
            "entity": None,
            "topic": "AI Agent 行业",
            "type": "theme",
            "research_object_type": "industry_theme",
            "listing_status": "not_applicable",
            "market_type": "thematic",
        }
    )

    with patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit")):
        listed_questions = decompose_problem(listed)
        private_questions = decompose_problem(private)
        industry_questions = decompose_problem(industry)

    all_text = "\n".join(question.content for question in listed_questions + private_questions + industry_questions)
    assert "有哪些证据支持该假设" not in all_text
    assert "有哪些证据可以反驳" not in all_text
    assert any("估值" in question.content for question in listed_questions)
    assert any("无法直接交易股票" in question.content for question in private_questions)
    assert any("市场空间" in question.content for question in industry_questions)


def test_decompose_has_real_industry_specific_branches() -> None:
    saas = Topic(
        id="t_saas",
        query="某 SaaS 软件公司是否值得研究",
        entity="某软件",
        topic="某软件研究价值",
        goal="判断研究价值",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="US",
    )
    credit_trade = saas.model_copy(
        update={
            "id": "t_trade",
            "query": "贸易企业信用风险是否值得研究",
            "entity": "某贸易企业",
            "topic": "贸易企业信用风险",
            "research_object_type": "listed_company",
        }
    )

    with patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit")):
        saas_text = "\n".join(question.content for question in decompose_problem(saas))
        trade_text = "\n".join(question.content for question in decompose_problem(credit_trade))

    assert "ARR" in saas_text
    assert "NRR" in saas_text
    assert "CAC" in saas_text
    assert "担保链条" in trade_text
    assert "再融资" in trade_text


def test_query_builder_routes_by_object_type() -> None:
    credit_topic = Topic(
        id="t_credit",
        query="某城投债主体是否值得继续研究",
        entity="某城投",
        topic="某城投信用风险",
        goal="判断信用风险",
        type="theme",
        research_object_type="credit_issuer",
        listing_status="not_applicable",
        market_type="bond",
    )
    question = Question(id="q1", topic_id=credit_topic.id, content="偿债能力如何", priority=1, framework_type="credit")

    queries = build_fact_queries(question, credit_topic)

    assert len(queries) == 2
    assert any("bond prospectus" in query or "募集说明书" in query for query in queries)
    assert all(" PE " not in f" {query} " for query in queries)


def test_source_origin_treats_ir_and_earnings_as_high_quality() -> None:
    origin = classify_source_origin(
        url="https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results",
        title="NVIDIA Announces Financial Results",
        source_type="company",
        content="NVIDIA today announced quarterly results and revenue growth.",
    )

    assert origin in {"company_ir", "official_disclosure"}
    assert classify_tier_from_origin(origin).value == "official"


def test_reason_outputs_bear_thesis_confidence_layers_and_catalysts() -> None:
    topic = Topic(
        id="t_reason",
        query="腾讯是否值得进一步研究",
        entity="腾讯",
        topic="腾讯研究价值",
        goal="判断研究价值",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="HK",
    )
    questions = [
        Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial"),
        Question(id="q2", topic_id=topic.id, content="风险因素如何", priority=1, framework_type="risk"),
    ]
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="腾讯财报披露收入增长且经营现金流改善，利润率保持稳定。",
            evidence_type="data",
            stance="counter",
            source_tier="official",
            evidence_score=0.82,
            quality_score=0.82,
        ),
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q2",
            source_id="s2",
            content="腾讯仍面临监管、竞争和广告需求波动风险。",
            evidence_type="risk_signal",
            stance="support",
            source_tier="professional",
            evidence_score=0.66,
            quality_score=0.66,
        ),
        Evidence(
            id="e3",
            topic_id=topic.id,
            question_id="q1",
            source_id="s3",
            content="最新季度业绩显示云业务和广告业务存在修复信号。",
            evidence_type="claim",
            stance="counter",
            source_tier="professional",
            evidence_score=0.61,
            quality_score=0.61,
        ),
    ]

    with patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("unit")):
        judgment = reason_and_generate(topic, evidence, questions)

    assert judgment.bear_theses
    assert judgment.catalysts
    assert judgment.research_confidence in {"low", "medium", "high"}
    assert judgment.signal_confidence in {"low", "medium", "high"}
    assert judgment.source_confidence in {"low", "medium", "high"}
    assert judgment.positioning


def test_investment_decision_routes_industry_theme_to_tracking() -> None:
    topic = Topic(
        id="t_industry",
        query="AI Agent 行业是否值得研究",
        topic="AI Agent 行业",
        goal="判断是否值得建立跟踪",
        type="theme",
        research_object_type="industry_theme",
        listing_status="not_applicable",
        market_type="thematic",
    )
    with patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit")):
        questions = decompose_problem(topic)
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id=questions[0].id,
            source_id="s1",
            content="AI Agent 行业市场空间增长，政策和技术进展带来催化剂。",
            evidence_type="claim",
            stance="neutral",
            source_tier="professional",
            evidence_score=0.62,
            quality_score=0.62,
        )
    ]
    with patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("unit")):
        judgment = reason_and_generate(topic, evidence, questions)
    judgment = apply_investment_layer(topic, questions, evidence, judgment)

    assert judgment.investment_decision is not None
    assert judgment.investment_decision.decision_target == "theme_tracking"
    assert judgment.investment_decision.decision in {"establish_tracking", "monitor_for_trigger", "deprioritize"}


def test_relative_context_affects_coverage_and_confidence_cap() -> None:
    topic = Topic(
        id="t_peer",
        query="英伟达是否值得进一步研究",
        entity="英伟达",
        topic="英伟达研究价值",
        goal="判断研究价值",
        type="company",
        research_object_type="listed_company",
        listing_status="listed",
        market_type="US",
    )
    questions = [
        Question(id="q1", topic_id=topic.id, content="行业竞争和相对位置如何", priority=1, framework_type="industry"),
        Question(id="q2", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial"),
    ]
    evidence = [
        Evidence(
            id="e1",
            topic_id=topic.id,
            question_id="q1",
            source_id="s1",
            content="英伟达收入增长和利润率改善。",
            evidence_type="data",
            stance="counter",
            source_tier="official",
            evidence_score=0.8,
            quality_score=0.8,
        )
    ]

    no_peer_questions = _mark_question_coverage(
        questions,
        evidence,
        topic,
        FinancialSnapshot(entity="英伟达", provider="yfinance", status="ok"),
    )
    with_peer_questions = _mark_question_coverage(
        questions,
        evidence,
        topic,
        FinancialSnapshot(
            entity="英伟达",
            provider="yfinance",
            status="ok",
            peer_comparison=[{"symbol": "NVDA"}, {"symbol": "AMD"}],
        ),
    )

    assert no_peer_questions[0].covered is False
    assert with_peer_questions[0].covered is False
    assert with_peer_questions[0].coverage_level == "partial"

    strict_industry_evidence = [
        Evidence(
            id="e2",
            topic_id=topic.id,
            question_id="q1",
            source_id="s2",
            content="英伟达市场份额80%，同行排名第一，AI芯片竞争格局保持领先。",
            evidence_type="data",
            stance="counter",
            source_tier="official",
            evidence_score=0.8,
            quality_score=0.8,
        )
    ]
    strict_questions = _mark_question_coverage(
        questions,
        strict_industry_evidence,
        topic,
        FinancialSnapshot(
            entity="英伟达",
            provider="yfinance",
            status="SUCCESS",
            peer_comparison=[{"symbol": "NVDA"}, {"symbol": "AMD"}],
        ),
    )
    assert strict_questions[0].covered is False
    assert strict_questions[0].coverage_level == "partial"

    rich_peer_questions = _mark_question_coverage(
        questions,
        strict_industry_evidence,
        topic,
        FinancialSnapshot(
            entity="英伟达",
            provider="yfinance",
            status="SUCCESS",
            peer_comparison=[
                {
                    "symbol": "NVDA",
                    "revenue_growth": 1.2,
                    "gross_margin": 0.73,
                    "valuation_pe": 45.0,
                    "market_share": "AI accelerator leader",
                },
                {
                    "symbol": "AMD",
                    "revenue_growth": 0.2,
                    "gross_margin": 0.5,
                    "valuation_pe": 30.0,
                    "market_share": "GPU challenger",
                },
            ],
        ),
    )
    strict_questions = rich_peer_questions
    assert strict_questions[0].covered is True

    judgment = Judgment(
        topic_id=topic.id,
        conclusion="已有证据显示英伟达具备进一步研究价值。",
        conclusion_evidence_ids=["e1"],
        clusters=[],
        risk=[],
        unknown=[],
        evidence_gaps=[],
        confidence="high",
        research_confidence="high",
        signal_confidence="high",
        source_confidence="high",
        confidence_basis=ConfidenceBasis(
            source_count=3,
            source_diversity="high",
            conflict_level="none",
            evidence_gap_level="low",
            effective_evidence_count=5,
            has_official_source=True,
            official_evidence_count=2,
            weak_source_only=False,
        ),
        research_actions=[],
    )
    adjusted = apply_investment_layer(topic, questions, evidence, judgment)

    assert adjusted.peer_context is not None
    assert adjusted.peer_context.status == "needs_research"
    assert adjusted.confidence == "medium"
    assert adjusted.research_confidence == "medium"
    assert adjusted.investment_decision is not None
    assert "peer_context=needs_research" in adjusted.investment_decision.decision_basis
