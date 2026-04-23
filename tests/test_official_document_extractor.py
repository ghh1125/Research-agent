from __future__ import annotations

import unittest

from app.agent.pipeline import _mark_question_coverage
from app.agent.steps.extract import extract_evidence
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.evidence_engine import classify_source_origin_v2, rank_sources
from app.services.official_document_extractor import extract_official_financial_evidence


class OfficialDocumentExtractorTest(unittest.TestCase):
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
            content="Alibaba Group Holding Limited Investor Relations quarterly results revenue cloud revenue operating cash flow free cash flow.",
        )

        ranked = rank_sources([source], topic, 1)

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].source_origin_type, "company_ir")
        self.assertEqual(ranked[0].tier, SourceTier.TIER1)
        self.assertTrue(ranked[0].is_official_pdf)

    def test_official_financial_extractor_outputs_structured_metric_evidence(self) -> None:
        topic = self._alibaba_topic()
        question = Question(id="q1", topic_id=topic.id, content="阿里收入、CMR、EBITA、OCF 和 FCF 如何", priority=1, framework_type="financial")
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba March Quarter 2025 Results",
            url="https://www.alibabagroup.com/document-2025-quarterly-results.pdf",
            source_type="report",
            provider="fixture",
            source_origin_type="company_ir",
            tier=SourceTier.TIER1,
            is_pdf=True,
            is_official_pdf=True,
            page_type="financial_pages",
            content=(
                "Alibaba Group revenue was RMB236,454 million, an increase of 7% year-over-year. "
                "Customer management revenue increased 12% year-over-year. "
                "Adjusted EBITA was RMB45,000 million. "
                "Net cash provided by operating activities was RMB31,400 million. "
                "Free cash flow declined 56% year-over-year to RMB15,200 million. "
                "Cloud Intelligence Group revenue was RMB30,100 million. "
                "AIDC revenue was RMB34,700 million. "
                "Capital expenditures were RMB16,200 million. "
                "Share repurchases were US$4.8 billion."
            ),
        )

        evidence = extract_official_financial_evidence(source, topic, [question], start_index=1)
        by_metric = {item.metric_name: item for item in evidence}

        self.assertIn("revenue", by_metric)
        self.assertIn("cmr", by_metric)
        self.assertIn("adjusted_ebita", by_metric)
        self.assertIn("operating_cash_flow", by_metric)
        self.assertIn("free_cash_flow", by_metric)
        self.assertIn("cloud_revenue", by_metric)
        self.assertEqual(by_metric["cmr"].comparison_type, "yoy")
        self.assertEqual(by_metric["free_cash_flow"].quality_score, 0.7)
        self.assertIn("official_structured_financial", by_metric["revenue"].quality_notes)

    def test_official_html_and_filing_blocks_extract_short_field_evidence(self) -> None:
        topic = self._alibaba_topic()
        question = Question(id="q1", topic_id=topic.id, content="阿里云、现金流、利润和资本开支如何", priority=1, framework_type="financial")
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba Group Q3 FY2026 Quarterly Results Highlights",
            url="https://www.examplegroup.com/investor-relations/quarterly-results",
            source_type="company",
            provider="fixture",
            source_origin_type="company_ir",
            tier=SourceTier.TIER1,
            content=(
                "Earnings Release and Investor Relations Highlights. "
                "In Q3 FY2026, Cloud revenue grew 35% YoY. "
                "Revenue: RMB260,000 million, up 8% year-over-year. "
                "Adjusted EBITA: RMB52,000 million. "
                "Operating cash flow: RMB42,000 million. "
                "Free cash flow: RMB23,000 million. "
                "Capital expenditures: RMB19,000 million. "
                "Diluted EPS was RMB2.87."
            ),
        )

        evidence = extract_official_financial_evidence(source, topic, [question])
        by_metric = {item.metric_name: item for item in evidence}

        self.assertGreaterEqual(len(evidence), 6)
        self.assertIn("cloud_revenue", by_metric)
        self.assertIn("revenue", by_metric)
        self.assertIn("adjusted_ebita", by_metric)
        self.assertIn("operating_cash_flow", by_metric)
        self.assertIn("free_cash_flow", by_metric)
        self.assertIn("capex", by_metric)
        self.assertIn("diluted_eps", by_metric)
        self.assertLessEqual(max(len(item.content) for item in evidence), 120)
        self.assertEqual(by_metric["cloud_revenue"].period, "FY2026Q3")
        self.assertEqual(by_metric["cloud_revenue"].comparison_type, "yoy")
        self.assertEqual(by_metric["cloud_revenue"].yoy_qoq_flag, "yoy")
        self.assertEqual(by_metric["revenue"].currency, "RMB")
        self.assertEqual(by_metric["revenue"].source_type, "official")

    def test_extract_evidence_prefers_official_financial_channel_for_official_sources(self) -> None:
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

        evidence = extract_evidence(topic, questions, [source])

        self.assertGreaterEqual(len(evidence), 2)
        self.assertTrue(all("official_structured_financial" in item.quality_notes for item in evidence))
        self.assertEqual({item.source_tier for item in evidence}, {"official"})

    def test_cross_entity_official_evidence_is_marked_and_excluded_from_main_extract(self) -> None:
        topic = self._alibaba_topic()
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")]
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
            content=(
                "Alibaba Group revenue was RMB236,454 million. "
                "Baidu revenue was RMB33,900 million in the neighboring snippet."
            ),
        )

        raw_evidence = extract_official_financial_evidence(source, topic, questions)
        extracted = extract_evidence(topic, questions, [source])

        self.assertTrue(any(item.cross_entity_contamination for item in raw_evidence))
        self.assertFalse(extracted)

    def test_truncated_official_metric_is_not_allowed_into_main_extract(self) -> None:
        topic = self._alibaba_topic()
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量", priority=1, framework_type="financial")]
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
            content="Customer management revenue increased 1% year-over-year to RMB1",
        )

        raw_evidence = extract_official_financial_evidence(source, topic, questions)
        extracted = extract_evidence(topic, questions, [source])

        self.assertTrue(raw_evidence)
        self.assertTrue(all(item.is_truncated for item in raw_evidence))
        self.assertFalse(extracted)

    def test_prefix_fragment_official_metric_is_not_allowed_into_main_extract(self) -> None:
        topic = self._alibaba_topic()
        questions = [Question(id="q1", topic_id=topic.id, content="现金流", priority=1, framework_type="credit")]
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
            content="ent maintained a stable free cash flow profile and free cash flow declined 56% year-over-year.",
        )

        raw_evidence = extract_official_financial_evidence(source, topic, questions)
        extracted = extract_evidence(topic, questions, [source])

        self.assertTrue(raw_evidence)
        self.assertTrue(all(not item.can_enter_main_chain for item in raw_evidence))
        self.assertFalse(extracted)

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
                    "quality_notes": ["official_structured_financial"],
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
