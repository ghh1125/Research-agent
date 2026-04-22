from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config import get_settings
from app.agent.steps.reason import reason_and_generate
from app.agent.steps.reason import _build_logic_gap_pressure_test
from app.models.judgment import Judgment, ConfidenceBasis
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.topic import Topic


class ReasonStepTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DASHSCOPE_API_KEY"] = ""
        os.environ["OPENAI_API_KEY"] = ""
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        get_settings.cache_clear()

    def test_reason_and_generate_returns_judgment(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究贸易企业违约原因",
            topic="贸易企业违约",
            goal="识别违约成因",
            type="theme",
        )
        evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="资产负债率连续三年高于70%",
                evidence_type="data",
                stance="support",
            ),
            Evidence(
                id="e2",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="自由现金流连续为负",
                evidence_type="risk_signal",
                stance="support",
            ),
        ]
        questions = [
            Question(id="q1", topic_id=topic.id, content="违约企业的财务共性是什么", priority=1),
            Question(id="q2", topic_id=topic.id, content="是否存在反向改善证据", priority=2),
        ]

        judgment = reason_and_generate(topic, evidence, questions)
        valid_ids = {item.id for item in evidence}

        self.assertEqual(judgment.topic_id, topic.id)
        self.assertTrue(judgment.conclusion)
        self.assertTrue(judgment.conclusion_evidence_ids)
        self.assertTrue(set(judgment.conclusion_evidence_ids).issubset(valid_ids))
        self.assertTrue(judgment.clusters)
        self.assertTrue(judgment.risk)
        self.assertTrue(judgment.unknown)
        self.assertTrue(judgment.evidence_gaps)
        self.assertTrue(judgment.pressure_tests)
        self.assertTrue(judgment.research_actions)
        self.assertGreaterEqual(judgment.confidence_basis.source_count, 1)
        self.assertIn(judgment.confidence, {"low", "medium", "high"})
        self.assertIn("高杠杆", judgment.conclusion)
        for cluster in judgment.clusters:
            self.assertTrue(
                set(cluster.support_evidence_ids + cluster.counter_evidence_ids).issubset(valid_ids)
            )
        for risk_item in judgment.risk:
            self.assertTrue(risk_item.evidence_ids)
            self.assertTrue(set(risk_item.evidence_ids).issubset(valid_ids))

    def test_reason_empty_evidence_fallback(self) -> None:
        topic = Topic(
            id="topic_002",
            query="研究贸易企业违约原因",
            topic="贸易企业违约",
            goal="识别违约成因",
            type="theme",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="违约企业的财务共性是什么", priority=1)]

        judgment = reason_and_generate(topic, [], questions)

        self.assertIn("证据不足", judgment.conclusion)
        self.assertEqual(judgment.conclusion_evidence_ids, [])
        self.assertEqual(judgment.clusters, [])
        self.assertEqual(judgment.risk, [])
        self.assertTrue(judgment.unknown)
        self.assertTrue(judgment.evidence_gaps)
        self.assertTrue(judgment.research_actions)
        self.assertEqual(judgment.confidence_basis.evidence_gap_level, "high")
        self.assertEqual(judgment.confidence, "low")

    def test_company_research_without_official_evidence_caps_confidence_low(self) -> None:
        topic = Topic(
            id="topic_003",
            query="研究拼多多是否值得进一步研究",
            topic="拼多多研究价值",
            goal="判断是否进入深度研究",
            type="company",
            entity="拼多多",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="收入和利润质量如何", priority=1),
            Question(id="q2", topic_id=topic.id, content="行业竞争风险如何", priority=2),
        ]
        evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                source_tier="content",
                source_score=0.2,
                evidence_score=0.4,
                content="拼多多收入增长较快，但利润质量仍需观察。",
                evidence_type="claim",
                stance="support",
            ),
            Evidence(
                id="e2",
                topic_id=topic.id,
                question_id="q2",
                source_id="s2",
                source_tier="content",
                source_score=0.2,
                evidence_score=0.4,
                content="拼多多仍面临价格竞争和补贴强度压力。",
                evidence_type="risk_signal",
                stance="support",
            ),
            Evidence(
                id="e3",
                topic_id=topic.id,
                question_id="q1",
                source_id="s3",
                source_tier="content",
                source_score=0.2,
                evidence_score=0.4,
                content="社区观点认为拼多多增长模式存在争议。",
                evidence_type="claim",
                stance="neutral",
            ),
        ]

        judgment = reason_and_generate(topic, evidence, questions)

        self.assertEqual(judgment.confidence, "low")
        self.assertFalse(judgment.confidence_basis.has_official_source)
        self.assertTrue(judgment.confidence_basis.weak_source_only)
        self.assertTrue(any(item.attack_type == "weak_source" for item in judgment.pressure_tests))

    def test_evidence_gap_pressure_does_not_always_force_low(self) -> None:
        topic = Topic(
            id="topic_004",
            query="研究宁德时代是否值得进一步研究",
            topic="宁德时代研究价值",
            goal="判断是否值得继续深挖",
            type="company",
            entity="宁德时代",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1),
            Question(id="q2", topic_id=topic.id, content="行业竞争如何", priority=1),
            Question(id="q3", topic_id=topic.id, content="治理风险如何", priority=1),
            Question(id="q4", topic_id=topic.id, content="还缺少哪些估值数据", priority=1),
        ]
        evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                source_tier="official",
                source_score=0.9,
                evidence_score=0.8,
                content="宁德时代财报显示营业收入和经营现金流保持稳定。",
                evidence_type="data",
                stance="neutral",
            ),
            Evidence(
                id="e2",
                topic_id=topic.id,
                question_id="q2",
                source_id="s2",
                source_tier="professional",
                source_score=0.8,
                evidence_score=0.75,
                content="专业财经资料显示宁德时代动力电池市场份额保持领先。",
                evidence_type="data",
                stance="counter",
            ),
            Evidence(
                id="e3",
                topic_id=topic.id,
                question_id="q3",
                source_id="s3",
                source_tier="professional",
                source_score=0.78,
                evidence_score=0.72,
                content="公开资料暂未显示宁德时代存在重大监管处罚。",
                evidence_type="fact",
                stance="counter",
            ),
        ]

        judgment = reason_and_generate(topic, evidence, questions)

        self.assertTrue(any(item.attack_type == "evidence_gap" for item in judgment.pressure_tests))
        self.assertNotEqual(judgment.confidence, "low")

    def test_logic_gap_pressure_test_uses_llm_attack(self) -> None:
        evidence = Evidence(
            id="e1",
            topic_id="topic_005",
            question_id="q1",
            source_id="s1",
            source_tier="professional",
            evidence_score=0.8,
            content="宁德时代动力电池市场份额保持全球领先。",
            evidence_type="data",
            stance="counter",
        )
        judgment = Judgment(
            topic_id="topic_005",
            conclusion="宁德时代具备明确投资价值。",
            conclusion_evidence_ids=["e1"],
            clusters=[],
            risk=[],
            unknown=[],
            evidence_gaps=[],
            confidence="medium",
            confidence_basis=ConfidenceBasis(
                source_count=1,
                source_diversity="low",
                conflict_level="none",
                evidence_gap_level="low",
                effective_evidence_count=1,
                has_official_source=False,
                official_evidence_count=0,
                weak_source_only=False,
            ),
            research_actions=[],
        )

        with patch(
            "app.agent.steps.reason.call_llm",
            return_value='{"has_logic_gap": true, "weakness": "市占率领先不能直接推出投资价值，仍缺估值和现金流前提。", "counter_conclusion": "只能说明竞争地位较强，投资价值仍待验证。", "severity": "medium"}',
        ):
            test = _build_logic_gap_pressure_test(judgment, ["e1"], {"e1": evidence}, 1)

        self.assertIsNotNone(test)
        self.assertEqual(test.attack_type, "logic_gap")
        self.assertEqual(test.severity, "medium")
        self.assertIn("估值", test.weakness)


if __name__ == "__main__":
    unittest.main()
