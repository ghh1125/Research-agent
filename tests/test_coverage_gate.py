from __future__ import annotations

import unittest

from app.agent.pipeline import _mark_question_coverage
from app.models.evidence import Evidence
from app.models.financial import FinancialSnapshot
from app.models.question import Question
from app.models.topic import Topic


class CoverageGateTest(unittest.TestCase):
    def test_financial_requires_revenue_profit_margin_and_trend(self) -> None:
        topic = Topic(id="t1", query="研究公司财务", topic="公司财务", goal="初筛", type="company")
        question = Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial")
        partial = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="公司营业收入100亿元，同比增长10%。",
                evidence_type="data",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]
        covered = [
            Evidence(
                id="e2",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="公司营业收入100亿元，同比增长10%，净利润20亿元，同比增长12%，毛利率24.6%。",
                evidence_type="data",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]

        partial_questions = _mark_question_coverage([question], partial, topic)
        covered_questions = _mark_question_coverage([question], covered, topic)

        self.assertEqual(partial_questions[0].coverage_level, "partial")
        self.assertFalse(partial_questions[0].covered)
        self.assertEqual(covered_questions[0].coverage_level, "covered")
        self.assertTrue(covered_questions[0].covered)

    def test_valuation_without_multiple_and_peer_is_gap(self) -> None:
        topic = Topic(
            id="t2",
            query="研究公司估值",
            topic="公司估值",
            goal="初筛",
            type="company",
            research_object_type="listed_company",
        )
        question = Question(id="q1", topic_id=topic.id, content="估值是否合理", priority=1, framework_type="valuation")
        evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="公司估值仍需结合同行比较。",
                evidence_type="claim",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]

        questions = _mark_question_coverage(
            [question],
            evidence,
            topic,
            FinancialSnapshot(entity="公司", provider="test", status="SUCCESS"),
        )

        self.assertEqual(questions[0].coverage_level, "uncovered")
        self.assertFalse(questions[0].covered)


if __name__ == "__main__":
    unittest.main()
