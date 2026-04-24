from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.llm_evidence_extractor import extract_structured_evidence_candidates
from app.services.llm_evidence_extractor import CandidateEvidence, validate_candidate_evidence, verify_value_grounded_in_quote


class LlmEvidenceExtractorTest(unittest.TestCase):
    def test_llm_json_candidates_become_structured_evidence(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        question = Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba official results",
            url="https://data.sec.gov/submissions/CIK0001577552.json",
            source_type="regulatory",
            provider="sec_edgar",
            source_origin_type="official_disclosure",
            tier=SourceTier.TIER1,
            source_score=0.95,
            content="Alibaba revenue was RMB996347 million in FY2025. Operating cash flow was RMB163509 million in FY2025.",
        )

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":[{"metric_name":"revenue","metric_value":996347,"unit":"million",'
                '"period":"FY2025","currency":"RMB","entity":"Alibaba","evidence_type":"data",'
                '"stance":"neutral","quote":"Alibaba revenue was RMB996347 million in FY2025.",'
                '"summary":"Revenue was RMB996347 million in FY2025.","extraction_confidence":0.92}]}'
            ),
        ):
            evidence = extract_structured_evidence_candidates(source, topic, [question])

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].metric_name, "revenue")
        self.assertEqual(evidence[0].metric_value, 996347)
        self.assertEqual(evidence[0].period, "FY2025")
        self.assertEqual(evidence[0].source_tier, "official")
        self.assertTrue(evidence[0].can_enter_main_chain)

    def test_cross_entity_llm_candidate_is_blocked(self) -> None:
        topic = Topic(
            id="topic_002",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
            research_object_type="listed_company",
        )
        question = Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba official results",
            url="https://www.alibabagroup.com/results",
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
                '"period":"FY2025","currency":"RMB","entity":"Baidu","evidence_type":"data",'
                '"stance":"neutral","quote":"Baidu revenue was RMB134598 million.",'
                '"summary":"Baidu revenue was RMB134598 million.","extraction_confidence":0.9}]}'
            ),
        ):
            evidence = extract_structured_evidence_candidates(source, topic, [question])

        self.assertTrue(evidence)
        self.assertTrue(evidence[0].cross_entity_contamination)
        self.assertFalse(evidence[0].can_enter_main_chain)

    def test_invalid_json_or_llm_failure_returns_empty(self) -> None:
        with patch("app.services.llm_evidence_extractor.call_llm", side_effect=RuntimeError("llm down")):
            self.assertEqual(
                extract_structured_evidence_candidates(
                    Source(
                        id="s1",
                        question_id="q1",
                        title="source",
                        source_type="website",
                        provider="fixture",
                        content="Revenue was RMB100 million.",
                    ),
                    Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司"),
                    [],
                ),
                [],
            )

    def test_period_null_is_allowed_but_not_guessed(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="official result",
            source_type="company",
            provider="fixture",
            tier=SourceTier.TIER1,
            content="Revenue was RMB100 million.",
        )
        ev = CandidateEvidence(
            metric_name="revenue",
            metric_value=100,
            unit="million",
            period=None,
            entity="公司",
            quote="Revenue was RMB100 million.",
            extraction_confidence=0.9,
        )

        self.assertTrue(validate_candidate_evidence(ev, source, Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司")))

    def test_value_must_be_grounded_in_quote(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="official result",
            source_type="company",
            provider="fixture",
            tier=SourceTier.TIER1,
            content="Revenue was RMB100 million.",
        )
        ev = CandidateEvidence(
            metric_name="revenue",
            metric_value=120,
            unit="million",
            period="FY2025",
            entity="公司",
            quote="Revenue was RMB100 million.",
            extraction_confidence=0.9,
        )

        self.assertFalse(verify_value_grounded_in_quote(ev))
        self.assertFalse(validate_candidate_evidence(ev, source, Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司")))

    def test_requires_cross_check_candidate_is_rejected(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="official result",
            source_type="company",
            provider="fixture",
            tier=SourceTier.TIER1,
            content="Revenue was RMB100 million while a peer disclosed RMB80 million.",
        )
        ev = CandidateEvidence(
            metric_name="revenue",
            metric_value=100,
            unit="million",
            period="FY2025",
            entity="公司",
            quote="Revenue was RMB100 million while a peer disclosed RMB80 million.",
            requires_cross_check=True,
            extraction_confidence=0.9,
        )

        self.assertFalse(validate_candidate_evidence(ev, source, Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司")))

    def test_latest_period_is_rejected_because_period_should_not_be_guessed(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="official result",
            source_type="company",
            provider="fixture",
            tier=SourceTier.TIER1,
            content="Revenue was RMB100 million.",
        )
        ev = CandidateEvidence(
            metric_name="revenue",
            metric_value=100,
            unit="million",
            period="latest",
            entity="公司",
            quote="Revenue was RMB100 million.",
            extraction_confidence=0.9,
        )

        self.assertFalse(validate_candidate_evidence(ev, source, Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司")))

    def test_weak_source_low_confidence_candidate_is_rejected(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="blog",
            source_type="website",
            provider="fixture",
            tier=SourceTier.TIER3,
            content="Revenue was RMB100 million.",
        )
        ev = CandidateEvidence(
            metric_name="revenue",
            metric_value=100,
            unit="million",
            period="FY2025",
            entity="公司",
            quote="Revenue was RMB100 million.",
            extraction_confidence=0.6,
        )

        self.assertFalse(validate_candidate_evidence(ev, source, Topic(id="t1", query="研究公司", topic="公司", goal="研究", type="company", entity="公司")))


if __name__ == "__main__":
    unittest.main()
