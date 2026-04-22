from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.question import Question
from app.models.source import SourceTier
from app.models.topic import Topic
from app.services.official_source_injector import get_stock_code, inject_official_sources


class OfficialSourceInjectorTest(unittest.TestCase):
    @patch("app.services.official_source_injector.discover_cninfo_announcements")
    def test_injects_cninfo_sources_for_known_a_share_company(self, discover_mock) -> None:
        discover_mock.return_value = [
            {
                "title": "宁德时代官方披露：2025年年度报告",
                "url": "http://static.cninfo.com.cn/finalpage/2026-03-30/test.PDF",
                "published_at": "2026-03-30",
            }
        ]
        topic = Topic(
            id="topic_001",
            query="宁德时代是否值得进一步研究",
            topic="宁德时代研究价值",
            goal="评估研究价值",
            type="company",
            entity="宁德时代",
        )
        questions = [
            Question(
                id="q1",
                topic_id=topic.id,
                content="财务质量如何",
                priority=1,
                framework_type="financial",
            )
        ]

        sources = inject_official_sources(topic, questions)

        self.assertEqual(get_stock_code(topic), "300750")
        self.assertTrue(sources)
        self.assertTrue(all(source.tier == SourceTier.TIER1 for source in sources))
        self.assertTrue(any("static.cninfo.com.cn" in (source.url or "") for source in sources))
        self.assertTrue(all(source.is_pdf for source in sources))
        self.assertTrue(all(source.question_id == "q1" for source in sources))

    def test_unknown_company_does_not_inject_fake_official_source(self) -> None:
        topic = Topic(
            id="topic_002",
            query="测试公司是否值得进一步研究",
            topic="测试公司研究价值",
            goal="评估研究价值",
            type="company",
            entity="测试公司",
        )

        self.assertEqual(inject_official_sources(topic, []), [])


if __name__ == "__main__":
    unittest.main()
