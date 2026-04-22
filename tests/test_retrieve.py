from __future__ import annotations

import unittest
from hashlib import md5
from unittest.mock import patch

from app.agent.steps.retrieve import retrieve_information
from app.models.question import Question
from app.models.topic import Topic


class RetrieveStepTest(unittest.TestCase):
    def _fake_search(self, query: str) -> list[dict]:
        digest = md5(query.encode("utf-8")).hexdigest()[:8]
        return [
            {
                "url": f"https://example.com/{digest}/1",
                "title": f"{query} 来源一",
                "source_type": "news",
                "provider": "test-realistic-fixture",
                "published_at": "2026-01-01",
                "content": "宁德时代营收增长但价格竞争加剧，市场份额和现金流表现需要结合财报继续验证。公司披露现金流改善，同时行业竞争仍然带来毛利率下降风险。",
            },
            {
                "url": f"https://example.com/{digest}/2",
                "title": f"{query} 来源二",
                "source_type": "report",
                "provider": "test-realistic-fixture",
                "published_at": "2026-01-02",
                "content": "公开资料显示，宁德时代负债和资本开支需要持续关注，海外业务增长和客户结构变化可能影响未来盈利质量。",
            },
        ]

    @patch("app.agent.steps.retrieve.search")
    def test_retrieve_returns_sources_with_content(self, search_mock) -> None:
        search_mock.side_effect = self._fake_search
        questions = [
            Question(id="q1", topic_id="topic_001", content="有哪些风险信号", priority=1),
            Question(id="q2", topic_id="topic_001", content="财务共性是什么", priority=1),
        ]
        topic = Topic(
            id="topic_001",
            query="研究宁德时代是否值得进一步研究",
            entity="宁德时代",
            topic="宁德时代研究价值",
            goal="判断研究价值",
            type="company",
        )

        sources = retrieve_information(questions, topic)

        self.assertTrue(sources)
        self.assertLessEqual(len(sources), 15)
        self.assertTrue(all(source.content for source in sources))
        self.assertTrue(all(source.flow_type in {"fact", "risk", "counter"} for source in sources))
        self.assertTrue(all(source.search_query for source in sources))
        self.assertEqual(len({source.url for source in sources}), len(sources))

    @patch("app.agent.steps.retrieve.search_supplemental_sources")
    @patch("app.agent.steps.retrieve.search")
    def test_retrieve_merges_supplemental_sources_for_listed_company(self, search_mock, supplemental_mock) -> None:
        search_mock.side_effect = self._fake_search
        supplemental_mock.return_value = (
            [
                {
                    "url": "",
                    "title": "宁德时代 A股行情快照",
                    "source_type": "other",
                    "provider": "akshare",
                    "published_at": None,
                    "content": "宁德时代 A股结构化行情快照：代码=300750；总市值=10000亿元；市盈率-动态=20。",
                    "source_origin_type": "professional_media",
                }
            ],
            [],
        )
        questions = [
            Question(id="q1", topic_id="topic_001", content="财务关键数据是什么", priority=1),
        ]
        topic = Topic(
            id="topic_001",
            query="研究宁德时代是否值得进一步研究",
            entity="宁德时代",
            topic="宁德时代研究价值",
            goal="判断研究价值",
            type="company",
            research_object_type="listed_company",
            market_type="A_share",
        )

        sources = retrieve_information(questions, topic)

        akshare_sources = [source for source in sources if source.provider == "akshare"]
        self.assertEqual(len(akshare_sources), 1)
        self.assertEqual(akshare_sources[0].source_origin_type, "professional_media")
        self.assertEqual(akshare_sources[0].flow_type, "fact")
        self.assertTrue(any(source.provider == "test-realistic-fixture" for source in sources))
        supplemental_mock.assert_called_once()

    @patch("app.agent.steps.retrieve.search")
    def test_site_directed_queries_do_not_starve_main_retrieval(self, search_mock) -> None:
        def _search(query: str) -> list[dict]:
            if "site:" in query:
                raise RuntimeError("site search unavailable")
            digest = md5(query.encode("utf-8")).hexdigest()[:8]
            return [
                {
                    "url": f"https://example.com/apple/{digest}",
                    "title": f"{query} 来源",
                    "source_type": "report",
                    "provider": "fixture",
                    "published_at": "2026-01-01",
                    "content": "苹果 Apple Services revenue gross margin operating cash flow improved, annual report data supports analysis.",
                }
            ]

        search_mock.side_effect = _search
        questions = [
            Question(
                id="q1",
                topic_id="topic_001",
                content="量化过去8个季度Services业务营收占比提升对自由现金流转换率的影响",
                search_query="Apple Services revenue gross margin operating cash flow",
                priority=1,
                framework_type="financial",
            ),
        ]
        topic = Topic(
            id="topic_001",
            query="研究苹果是否值得进一步研究",
            entity="苹果",
            topic="苹果研究价值",
            goal="判断研究价值",
            type="company",
            research_object_type="listed_company",
            market_type="US",
        )

        sources = retrieve_information(questions, topic)
        called_queries = [call.args[0] for call in search_mock.call_args_list]

        self.assertTrue(sources)
        self.assertEqual(called_queries[0], "Apple Services revenue gross margin operating cash flow")
        self.assertTrue(any("site:" in query for query in called_queries))
        self.assertTrue(all("过去8个季度" not in source.search_query for source in sources))


if __name__ == "__main__":
    unittest.main()
