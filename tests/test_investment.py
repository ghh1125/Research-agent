from __future__ import annotations

import os
import unittest

from app.config import get_settings
from app.agent.steps.investment import apply_investment_layer
from app.agent.steps.reason import reason_and_generate
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.topic import Topic


class InvestmentLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DASHSCOPE_API_KEY"] = ""
        os.environ["OPENAI_API_KEY"] = ""
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        get_settings.cache_clear()

    def test_investment_layer_adds_decision_with_valid_evidence_ids(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究宁德时代是否值得进一步研究",
            topic="宁德时代研究价值",
            goal="判断是否具备继续深挖价值",
            type="company",
            entity="宁德时代",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="财务质量、现金流和资产负债结构是否健康", priority=1, covered=True),
            Question(id="q2", topic_id=topic.id, content="行业竞争格局和公司相对位置如何", priority=2, covered=True),
        ]
        evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="宁德时代实现营业收入4237.02亿元，同比增长17.04%",
                evidence_type="data",
                stance="support",
            ),
            Evidence(
                id="e2",
                topic_id=topic.id,
                question_id="q2",
                source_id="s2",
                content="动力电池行业价格竞争加剧，行业产能快速扩张",
                evidence_type="risk_signal",
                stance="support",
            ),
        ]
        judgment = reason_and_generate(topic, evidence, questions)

        judgment = apply_investment_layer(topic, questions, evidence, judgment)
        valid_ids = {item.id for item in evidence}

        self.assertIsNotNone(judgment.research_scope)
        self.assertIsNotNone(judgment.peer_context)
        self.assertIsNotNone(judgment.investment_decision)
        self.assertTrue(judgment.trend_signals)
        self.assertIn(judgment.investment_decision.decision, {"deep_dive_candidate", "watchlist", "deprioritize"})
        self.assertIn(
            judgment.investment_decision.decision_target,
            {"research_priority", "deep_research_entry", "watchlist_entry", "research_action"},
        )
        self.assertTrue(judgment.investment_decision.decision_basis)
        self.assertTrue(set(judgment.investment_decision.evidence_ids).issubset(valid_ids))
        for signal in judgment.trend_signals:
            self.assertTrue(signal.evidence_ids)
            self.assertTrue(set(signal.evidence_ids).issubset(valid_ids))

    def test_empty_evidence_defaults_to_watch(self) -> None:
        topic = Topic(
            id="topic_002",
            query="研究某公司",
            topic="某公司研究价值",
            goal="判断是否值得研究",
            type="company",
            entity="某公司",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1)]
        judgment = reason_and_generate(topic, [], questions)

        judgment = apply_investment_layer(topic, questions, [], judgment)

        self.assertEqual(judgment.investment_decision.decision, "watchlist")
        self.assertEqual(judgment.investment_decision.decision_target, "research_priority")
        self.assertTrue(judgment.investment_decision.decision_basis)
        self.assertEqual(judgment.investment_decision.evidence_ids, [])
        self.assertEqual(judgment.research_scope.depth_recommendation, "quick_screen")
        self.assertEqual(judgment.peer_context.status, "needs_research")

    def test_known_company_gets_auto_peer_group_even_before_metrics(self) -> None:
        topic = Topic(
            id="topic_003",
            query="研究宁德时代",
            topic="宁德时代研究价值",
            goal="判断是否值得研究",
            type="company",
            entity="宁德时代",
            research_object_type="listed_company",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="行业竞争格局如何", priority=1)]
        judgment = reason_and_generate(topic, [], questions)

        judgment = apply_investment_layer(topic, questions, [], judgment)

        self.assertEqual(judgment.peer_context.status, "needs_research")
        self.assertIn("比亚迪", judgment.peer_context.peer_entities)
        self.assertTrue(judgment.peer_context.comparison_rows)
        self.assertTrue(any(item.startswith("peer_group=") for item in judgment.investment_decision.decision_basis))


if __name__ == "__main__":
    unittest.main()
