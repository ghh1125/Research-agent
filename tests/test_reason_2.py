from __future__ import annotations

import os
import unittest

from app.config import get_settings
from app.agent.steps.reason import reason_and_generate
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.topic import Topic


class Reason2Test(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DASHSCOPE_API_KEY"] = ""
        os.environ["OPENAI_API_KEY"] = ""
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        get_settings.cache_clear()

    def test_clusters_and_evidence_ids_are_valid(self) -> None:
        topic = Topic(
            id="topic_003",
            query="这个经营权模式有没有合规风险",
            topic="经营权模式",
            goal="评估合规边界",
            type="compliance",
        )
        evidence = [
            Evidence(id="e1", topic_id=topic.id, question_id="q1", source_id="s1", content="监管文件提到若实际经营主体与许可主体不一致，可能触发无证经营风险", evidence_type="risk_signal", stance="support"),
            Evidence(id="e2", topic_id=topic.id, question_id="q1", source_id="s1", content="关键资质是否可以转授权仍存在争议", evidence_type="claim", stance="neutral"),
            Evidence(id="e3", topic_id=topic.id, question_id="q2", source_id="s2", content="历史案例显示授权链条不完整时曾被要求整改", evidence_type="fact", stance="support"),
        ]
        questions = [
            Question(id="q1", topic_id=topic.id, content="该模式涉及哪些监管红线", priority=1),
            Question(id="q2", topic_id=topic.id, content="是否存在历史处罚案例", priority=2),
        ]

        judgment = reason_and_generate(topic, evidence, questions)
        all_ids = {item.id for item in evidence}

        self.assertGreater(len(judgment.clusters), 0)
        self.assertTrue(judgment.research_actions)
        self.assertIn(judgment.confidence_basis.source_diversity, {"low", "medium", "high"})
        for cluster in judgment.clusters:
            for evidence_id in cluster.support_evidence_ids + cluster.counter_evidence_ids:
                self.assertIn(evidence_id, all_ids)
        self.assertTrue(judgment.conclusion_evidence_ids)

    def test_confidence_is_low_when_evidence_is_too_sparse(self) -> None:
        topic = Topic(
            id="topic_004",
            query="研究贸易企业违约原因",
            topic="贸易企业违约",
            goal="识别违约成因",
            type="theme",
        )
        evidence = [
            Evidence(id="e1", topic_id=topic.id, question_id="q1", source_id="s1", content="资产负债率连续三年高于70%", evidence_type="data", stance="support"),
        ]
        questions = [
            Question(id="q1", topic_id=topic.id, content="违约或风险暴露前有哪些财务共性", priority=1),
            Question(id="q2", topic_id=topic.id, content="外部环境如何放大风险", priority=2),
        ]

        judgment = reason_and_generate(topic, evidence, questions)

        self.assertEqual(judgment.confidence, "low")
        self.assertIn(judgment.confidence_basis.evidence_gap_level, {"medium", "high"})
        self.assertTrue(judgment.conclusion_evidence_ids)


if __name__ == "__main__":
    unittest.main()
