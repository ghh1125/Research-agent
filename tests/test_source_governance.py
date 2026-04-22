from __future__ import annotations

import unittest

from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.evidence_engine import rank_sources


class SourceGovernanceTest(unittest.TestCase):
    def test_catl_company_pdf_is_ranked_as_official_company_ir(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="宁德时代年度报告 PDF",
            url="https://www.catl.com/uploads/2025/annual_report.pdf",
            source_type="report",
            provider="fixture",
            is_pdf=True,
            pdf_parse_status="parsed",
            content="宁德时代 A股股票代码 300750 董事会秘书 资产负债率 营业收入 100亿元。",
        )
        topic = Topic(
            id="topic_catl",
            query="研究宁德时代财务质量",
            entity="宁德时代",
            topic="宁德时代财务质量",
            goal="判断财务质量",
            type="company",
        )

        ranked = rank_sources([source], topic, 1)

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].source_origin_type, "company_ir")
        self.assertEqual(ranked[0].tier, SourceTier.TIER1)
        self.assertTrue(ranked[0].is_official_pdf)


if __name__ == "__main__":
    unittest.main()
