from __future__ import annotations

import unittest

from app.models.source import Source
from app.models.source import SourceTier
from app.models.topic import Topic
from app.services.evidence_engine import (
    classify_source_tier,
    is_recent_source,
    is_usable_source,
    looks_like_noise,
    rank_sources,
    recency_score_for_source,
    resolve_source_date,
    score_evidence_text,
)


class EvidenceEngineTest(unittest.TestCase):
    def test_source_tier_classification(self) -> None:
        self.assertEqual(classify_source_tier("https://www.sec.gov/Archives/report"), SourceTier.TIER1)
        self.assertEqual(classify_source_tier("https://finance.sina.com.cn/news"), SourceTier.TIER2)
        self.assertEqual(classify_source_tier("https://www.zhihu.com/question/1"), SourceTier.TIER3)

    def test_reprint_content_downgrades_professional_domain(self) -> None:
        topic = Topic(
            id="topic_001",
            query="拼多多增长是否可持续",
            entity="拼多多",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
        )
        source = Source(
            id="s1",
            question_id="q1",
            title="东方财富转载观点",
            url="https://eastmoney.com/a/123",
            source_type="website",
            provider="fixture",
            content="来源：某自媒体。责任编辑：编辑。相关推荐。拼多多增长受到关注。",
        )

        ranked = rank_sources([source], topic, limit=1)

        self.assertEqual(ranked[0].tier, SourceTier.TIER3)
        self.assertIn("reprint_or_aggregation", ranked[0].source_rank_reason)

    def test_rank_sources_rejects_unrelated_webpage_and_gibberish_pdf(self) -> None:
        topic = Topic(
            id="topic_001",
            query="拼多多当前的高增长模式是否具有可持续性",
            entity="拼多多",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
        )
        sources = [
            Source(
                id="s1",
                question_id="q1",
                title="一文了解高质量数据集",
                url="https://example.com/dataset",
                source_type="website",
                provider="fixture",
                content="高质量数据集需要考虑完整性、合规性和规模化增长，与机器学习训练有关。",
            ),
            Source(
                id="s2",
                question_id="q1",
                title="[PDF] PDD Holdings 深度研究报告",
                url="https://example.com/pdd.pdf",
                source_type="report",
                provider="fixture",
                content="GY:0e isD\\ Jƀ:+K @ @]¯ n05x$و Q@ A4PEPEPEPEUm4S",
            ),
            Source(
                id="s3",
                question_id="q1",
                title="PDD Holdings announces quarterly results",
                url="https://investor.pddholdings.com/news",
                source_type="company",
                provider="fixture",
                content="PDD Holdings reported revenue growth, net income growth and strong operating cash flow. Temu continued to expand, while competition and regulatory risks remain important.",
            ),
        ]

        ranked = rank_sources(sources, topic, limit=5)

        self.assertEqual([source.id for source in ranked], ["s3"])
        self.assertEqual(ranked[0].tier, SourceTier.TIER1)
        self.assertGreater(ranked[0].source_score or 0, 0)
        self.assertFalse(is_usable_source(sources[0], topic))
        self.assertFalse(is_usable_source(sources[1], topic))

    def test_rank_sources_keeps_official_source_with_resolved_english_alias(self) -> None:
        topic = Topic(
            id="topic_baba",
            query="研究阿里巴巴财务质量、现金流、估值和行业竞争",
            entity="阿里巴巴",
            topic="阿里巴巴基本面",
            goal="判断财务质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        source = Source(
            id="s1",
            question_id="q1",
            title="Alibaba Group Holding Limited SEC EDGAR submissions",
            url="https://data.sec.gov/submissions/CIK0001577552.json",
            source_type="regulatory",
            provider="sec_edgar",
            content=(
                "Alibaba Group Holding Limited SEC EDGAR submissions official disclosure. "
                "Revenue: CNY996347 million in FY2025. "
                "Operating cash flow: CNY163509 million in FY2025. "
                "Net income: CNY130109 million in FY2025."
            ),
            source_origin_type="official_disclosure",
        )

        ranked = rank_sources([source], topic, limit=1)

        self.assertEqual([item.id for item in ranked], ["s1"])
        self.assertTrue(ranked[0].contains_entity)
        self.assertEqual(ranked[0].tier, SourceTier.TIER1)
        self.assertGreaterEqual(ranked[0].source_score or 0, 0.22)

    def test_noise_filter_detects_html_navigation(self) -> None:
        self.assertTrue(looks_like_noise("<nav>首页 登录 注册</nav>"))

    def test_evidence_score_rejects_gibberish(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="PDD",
            url="https://example.com/pdd.pdf",
            source_type="report",
            provider="fixture",
            content="拼多多财报显示收入增长。",
        )

        score, notes = score_evidence_text("GY:0e isD\\ Jƀ:+K", source)

        self.assertEqual(score, 0.0)
        self.assertIn("gibberish_rejected", notes)

    def test_higher_quality_source_gets_higher_evidence_score(self) -> None:
        official = Source(
            id="s1",
            question_id="q1",
            title="PDD Holdings quarterly results",
            url="https://investor.pddholdings.com/news",
            source_type="company",
            provider="fixture",
            tier=SourceTier.TIER1,
            source_score=0.9,
            contains_entity=True,
            is_recent=True,
            content="PDD Holdings reported revenue growth and operating cash flow improvement in 2025.",
        )
        weak = Source(
            id="s2",
            question_id="q1",
            title="社区讨论",
            url="https://www.zhihu.com/question/1",
            source_type="website",
            provider="fixture",
            tier=SourceTier.TIER3,
            source_score=0.2,
            content="有人讨论拼多多增长。",
        )
        topic = Topic(
            id="topic_001",
            query="拼多多增长是否可持续",
            entity="拼多多",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
        )

        official_score, _ = score_evidence_text("PDD Holdings reported revenue growth and operating cash flow improvement in 2025.", official, topic)
        weak_score, _ = score_evidence_text("有人讨论拼多多增长。", weak, topic)

        self.assertGreater(official_score, weak_score)

    def test_placeholder_date_is_unknown_not_stale(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="Company investor relations results",
            url="https://investor.example.com/results",
            source_type="company",
            provider="fixture",
            published_at="1970-01-01",
            content="Company reported revenue growth and operating cash flow improvement.",
        )

        resolved_date, date_source = resolve_source_date(source)

        self.assertIsNone(resolved_date)
        self.assertEqual(date_source, "unknown")
        self.assertIsNone(is_recent_source(source))
        self.assertEqual(recency_score_for_source(source), 0.85)

    def test_source_date_can_be_extracted_from_url_or_content(self) -> None:
        source_from_url = Source(
            id="s1",
            question_id="q1",
            title="PDD Holdings results",
            url="https://example.com/2026/03/31/pdd-results",
            source_type="website",
            provider="fixture",
            published_at="1970-01-01",
            content="PDD Holdings reported revenue growth.",
        )
        source_from_content = Source(
            id="s2",
            question_id="q1",
            title="拼多多业绩",
            url="https://example.com/pdd",
            source_type="website",
            provider="fixture",
            content="拼多多在2026年3月披露营业收入增长。",
        )

        url_date, url_date_source = resolve_source_date(source_from_url)
        content_date, content_date_source = resolve_source_date(source_from_content)

        self.assertEqual(url_date_source, "url_extracted")
        self.assertEqual(url_date.year, 2026)
        self.assertEqual(content_date_source, "content_extracted")
        self.assertEqual(content_date.year, 2026)


if __name__ == "__main__":
    unittest.main()
