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

    def test_aggregator_and_mirror_sites_cannot_be_promoted_to_official(self) -> None:
        topic = Topic(
            id="topic_alibaba",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="Alibaba Group Annual Report and Earnings News",
                url="https://www.tradingview.com/news/reuters.com,2025:alibaba-results/",
                source_type="company",
                provider="fixture",
                content="阿里巴巴 Alibaba Group Holding Limited annual report earnings release revenue operating cash flow.",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="Alibaba Group Investor Relations Analysis",
                url="https://simplywall.st/stocks/us/retail/nyse-baba/alibaba-group-holding",
                source_type="report",
                provider="fixture",
                content="阿里巴巴 Alibaba Group Holding Limited financial report analysis revenue earnings valuation.",
            ),
            Source(
                id="s3",
                question_id="q1",
                title="Alibaba Group Annual Report PDF",
                url="https://www.annualreports.com/HostedData/AnnualReportArchive/b/NYSE_BABA_2025.pdf",
                source_type="report",
                provider="fixture",
                is_pdf=True,
                pdf_parse_status="parsed",
                content="阿里巴巴 Alibaba Group Holding Limited annual report form 20-f revenue operating cash flow.",
            ),
        ]

        ranked = rank_sources(sources, topic, 3)
        by_id = {source.id: source for source in ranked}

        self.assertEqual(by_id["s1"].source_origin_type, "professional_media")
        self.assertEqual(by_id["s2"].source_origin_type, "professional_media")
        self.assertEqual(by_id["s3"].source_origin_type, "research_media")
        self.assertTrue(all(source.tier != SourceTier.TIER1 for source in ranked))
        self.assertFalse(any(source.is_official_pdf for source in ranked))

    def test_morningstar_globe_and_statista_are_hard_capped_below_official(self) -> None:
        topic = Topic(
            id="topic_caps",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="Alibaba Earnings Call Transcript",
                url="https://www.morningstar.com/news/dow-jones/202604010001/alibaba-earnings-call-transcript",
                source_type="report",
                provider="fixture",
                content="Alibaba earnings call transcript revenue operating cash flow.",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="Alibaba still faces investor questions",
                url="https://www.theglobeandmail.com/investing/markets/stocks/BABA/article-alibaba-results/",
                source_type="news",
                provider="fixture",
                content="Alibaba results and investor discussion.",
            ),
            Source(
                id="s3",
                question_id="q1",
                title="Alibaba cloud market share stat",
                url="https://www.statista.com/statistics/123456/alibaba-cloud-market-share/",
                source_type="report",
                provider="fixture",
                content="Alibaba cloud market share dataset.",
            ),
        ]

        ranked = rank_sources(sources, topic, 3)

        assert all(source.tier != SourceTier.TIER1 for source in ranked)
        assert {item.source_origin_type for item in ranked}.issubset({"professional_media", "research_media", "aggregator"})

    def test_revenue_model_gurufocus_and_motley_fool_are_never_official(self) -> None:
        topic = Topic(
            id="topic_caps2",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="Alibaba Revenue Model 2026: How Alibaba Makes Money Explained",
                url="https://www.stockanalysisblog.com/alibaba-revenue-model-2026",
                source_type="report",
                provider="fixture",
                content="Revenue model and makes money explained.",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="Alibaba Statistics Facts 2026",
                url="https://www.gurufocus.com/news/123456/alibaba-statistics-facts-2026",
                source_type="report",
                provider="fixture",
                content="GuruFocus facts and statistics.",
            ),
            Source(
                id="s3",
                question_id="q1",
                title="Alibaba stock analysis blog",
                url="https://www.fool.com/investing/2026/04/01/alibaba-stock-analysis-blog/",
                source_type="news",
                provider="fixture",
                content="Motley Fool style analysis blog.",
            ),
        ]

        ranked = rank_sources(sources, topic, 3)

        assert all(source.tier != SourceTier.TIER1 for source in ranked)
        assert all(source.source_origin_type in {"professional_media", "research_media", "aggregator"} for source in ranked)

    def test_monexa_and_moomoo_are_hard_capped_below_official(self) -> None:
        topic = Topic(
            id="topic_caps3",
            query="研究阿里巴巴财务质量",
            entity="阿里巴巴",
            topic="阿里巴巴财务质量",
            goal="判断财务质量",
            type="company",
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="Alibaba valuation dashboard",
                url="https://monexa.ai/stocks/BABA/valuation",
                source_type="report",
                provider="fixture",
                content="Alibaba valuation dashboard and financial snapshot.",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="Alibaba financial analysis",
                url="https://www.moomoo.com/stock/BABA-US/financials",
                source_type="report",
                provider="fixture",
                content="Alibaba revenue, earnings and cash flow analysis.",
            ),
        ]

        ranked = rank_sources(sources, topic, 2)

        assert all(source.tier != SourceTier.TIER1 for source in ranked)
        assert all(source.source_origin_type in {"professional_media", "research_media", "aggregator"} for source in ranked)


if __name__ == "__main__":
    unittest.main()
