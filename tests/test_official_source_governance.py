from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.pipeline import _mark_question_coverage
from app.agent.steps.extract import extract_evidence
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.evidence_engine import classify_source_origin_v2, rank_sources


class OfficialSourceGovernanceTest(unittest.TestCase):
    def _alibaba_topic(self) -> Topic:
        return Topic(
            id="topic_alibaba",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务、估值和现金流质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="HK",
        )

    def test_alibabagroup_ir_url_is_classified_as_company_ir_without_whitelist(self) -> None:
        result = classify_source_origin_v2(
            entity="阿里巴巴",
            url="https://www.alibabagroup.com/ir-financial-reports-quarterly-results",
            title="Alibaba Group Quarterly Results and Financial Reports",
            content="Alibaba Group Holding Limited BABA 9988.HK Investor Relations quarterly results annual report download PDF webcast presentation transcript.",
        )

        self.assertTrue(result["is_official"])
        self.assertTrue(result["is_company_ir"])
        self.assertGreaterEqual(result["official_confidence"], 0.8)
        self.assertEqual(result["source_origin_type"], "company_ir")
        self.assertIn("domain_brand_match", result["signals"])

    def test_rank_sources_uses_entity_aware_official_detection(self) -> None:
        topic = self._alibaba_topic()
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba Group Quarterly Results",
            url="https://www.alibabagroup.com/document-2025-quarterly-results.pdf",
            source_type="report",
            provider="fixture",
            is_pdf=True,
            pdf_parse_status="parsed",
            content="Alibaba Group Holding Limited Investor Relations quarterly results annual report download PDF webcast presentation transcript.",
        )

        ranked = rank_sources([source], topic, 1)

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].source_origin_type, "company_ir")
        self.assertEqual(ranked[0].tier, SourceTier.TIER1)
        self.assertTrue(ranked[0].is_official_pdf)

    def test_official_sources_extract_through_llm_structured_channel(self) -> None:
        topic = self._alibaba_topic()
        questions = [
            Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial"),
            Question(id="q2", topic_id=topic.id, content="信用和现金流", priority=1, framework_type="credit"),
        ]
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba official results",
            url="https://www.alibabagroup.com/document-results.pdf",
            source_type="report",
            provider="fixture",
            source_origin_type="company_ir",
            tier=SourceTier.TIER1,
            is_official_pdf=True,
            content="Customer management revenue increased 12% year-over-year. Free cash flow declined 56% year-over-year.",
        )

        with patch(
            "app.services.llm_evidence_extractor.call_llm",
            return_value=(
                '{"evidences":['
                '{"metric_name":"customer_management_revenue","metric_value":12,"unit":"%",'
                '"period":null,"entity":"Alibaba","quote":"Customer management revenue increased 12% year-over-year.",'
                '"extraction_confidence":0.9},'
                '{"metric_name":"free_cash_flow","metric_value":56,"unit":"%",'
                '"period":null,"entity":"Alibaba","quote":"Free cash flow declined 56% year-over-year.",'
                '"extraction_confidence":0.9}]}'
            ),
        ):
            evidence = extract_evidence(topic, questions, [source])

        self.assertEqual(len(evidence), 2)
        self.assertTrue(all("llm_structured_candidate" in item.quality_notes for item in evidence))
        self.assertTrue(all("official_structured_financial" in item.quality_notes for item in evidence))
        self.assertEqual({item.source_tier for item in evidence}, {"official"})

    def test_financial_coverage_without_official_or_professional_structured_evidence_cannot_be_covered(self) -> None:
        topic = self._alibaba_topic()
        question = Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")
        weak_evidence = [
            Evidence(
                id="e1",
                topic_id=topic.id,
                question_id="q1",
                source_id="s1",
                content="公司营业收入100亿元，同比增长10%，净利润20亿元，同比增长12%，毛利率24.6%。",
                evidence_type="data",
                source_tier="content",
                evidence_score=0.8,
                quality_score=0.8,
            )
        ]
        official_structured = [
            weak_evidence[0].model_copy(
                update={
                    "source_tier": "official",
                    "metric_name": "revenue",
                    "quality_notes": ["llm_structured_candidate"],
                }
            )
        ]

        weak_marked = _mark_question_coverage([question], weak_evidence, topic)
        official_marked = _mark_question_coverage([question], official_structured, topic)

        self.assertEqual(weak_marked[0].coverage_level, "partial")
        self.assertFalse(weak_marked[0].covered)
        self.assertEqual(official_marked[0].coverage_level, "covered")
        self.assertTrue(official_marked[0].covered)


if __name__ == "__main__":
    unittest.main()
