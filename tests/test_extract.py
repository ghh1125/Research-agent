from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.steps.extract import extract_evidence
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic


class ExtractStepTest(unittest.TestCase):
    def _topic(self) -> Topic:
        return Topic(
            id="topic_001",
            query="研究阿里巴巴财务质量",
            topic="阿里巴巴财务质量",
            entity="阿里巴巴",
            goal="判断财务质量",
            type="company",
            research_object_type="listed_company",
        )

    def test_extract_evidence_uses_llm_structured_extractor_only(self) -> None:
        topic = self._topic()
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")]
        source = Source(
            id="s1",
            question_id="q1",
            url="https://www.alibabagroup.com/results",
            title="Alibaba official results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            tier=SourceTier.TIER1,
            content="Alibaba revenue was RMB996347 million in FY2025. Navigation Login Footer.",
        )

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":[{"metric_name":"revenue","metric_value":996347,"unit":"million",'
                '"period":"FY2025","entity":"Alibaba","quote":"Alibaba revenue was RMB996347 million in FY2025.",'
                '"extraction_confidence":0.92}]}'
            ),
        ) as llm_mock:
            evidence = extract_evidence(topic, questions, [source])

        llm_mock.assert_called_once()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].id, "e1")
        self.assertEqual(evidence[0].metric_name, "revenue")
        self.assertEqual(evidence[0].metric_value, 996347)
        self.assertTrue(evidence[0].can_enter_main_chain)
        self.assertIn("llm_structured_candidate", evidence[0].quality_notes)

    def test_extract_evidence_drops_candidates_blocked_by_llm_safety_gate(self) -> None:
        topic = self._topic()
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")]
        source = Source(
            id="s1",
            question_id="q1",
            url="https://www.alibabagroup.com/results",
            title="Alibaba official results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            tier=SourceTier.TIER1,
            content="Alibaba revenue was RMB996347 million. Baidu revenue was RMB134598 million.",
        )

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":[{"metric_name":"revenue","metric_value":134598,"unit":"million",'
                '"period":"FY2025","entity":"Baidu","quote":"Baidu revenue was RMB134598 million.",'
                '"requires_cross_check":true,"extraction_confidence":0.9}]}'
            ),
        ):
            evidence = extract_evidence(topic, questions, [source])

        self.assertEqual(evidence, [])

    def test_extract_evidence_returns_empty_when_llm_returns_no_metrics(self) -> None:
        topic = self._topic()
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")]
        source = Source(
            id="s1",
            question_id="q1",
            url="https://example.com/noise",
            title="Noise",
            source_type="website",
            provider="fixture",
            content="首页 登录 注册 联系我们 目录",
        )

        with patch("app.services.llm_evidence_extractor.call_llm", return_value='{"evidences":[]}'):
            evidence = extract_evidence(topic, questions, [source])

        self.assertEqual(evidence, [])


if __name__ == "__main__":
    unittest.main()
