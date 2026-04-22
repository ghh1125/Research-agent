from __future__ import annotations

import unittest

from app.agent.utils.query_builder import (
    build_layered_search_queries,
    build_counter_queries,
    build_english_queries,
    build_fact_queries,
    build_risk_queries,
    is_us_stock,
    split_directed_queries,
)
from app.models.question import Question
from app.models.topic import Topic


class QueryBuilderTest(unittest.TestCase):
    def test_build_fact_queries_uses_entity_plus_framework_keywords(self) -> None:
        topic = Topic(
            id="topic_001",
            query="宁德时代是否值得进一步研究",
            topic="宁德时代研究价值",
            goal="评估研究价值",
            type="company",
            entity="宁德时代",
        )
        question = Question(
            id="q1",
            topic_id=topic.id,
            content="收入、利润和现金流质量如何",
            priority=1,
            framework_type="financial",
        )

        queries = build_fact_queries(question, topic)

        self.assertTrue(queries)
        self.assertGreaterEqual(len(queries), 5)
        self.assertTrue(all(query.startswith("宁德时代 ") for query in queries))
        self.assertFalse(any(topic.query == query for query in queries))
        main_queries, directed_queries = split_directed_queries(queries)
        self.assertTrue(any("site:cninfo.com.cn" in query for query in directed_queries))
        self.assertFalse(any("site:" in query for query in main_queries))
        self.assertTrue(any("annual report" in query or "quarterly results" in query for query in queries))
        self.assertTrue(any("收入" in query or "利润" in query or "现金流" in query for query in queries))

    def test_layered_queries_prioritize_market_specific_official_sources(self) -> None:
        us_queries = build_layered_search_queries("Apple", "US", "financial")
        hk_queries = build_layered_search_queries("腾讯", "HK", "financial")
        a_share_queries = build_layered_search_queries("宁德时代", "A_share", "financial")

        self.assertNotIn("site:", us_queries[0])
        self.assertTrue(any("site:hkexnews.hk" in query for query in hk_queries))
        self.assertTrue(any("site:cninfo.com.cn" in query for query in a_share_queries))
        self.assertTrue(any("operating cash flow capex free cash flow" in query for query in us_queries))

    def test_question_search_query_is_used_before_analyst_question(self) -> None:
        topic = Topic(
            id="topic_llm",
            query="研究苹果",
            topic="苹果研究价值",
            goal="判断研究价值",
            type="company",
            entity="苹果",
            research_object_type="listed_company",
            market_type="US",
        )
        question = Question(
            id="q1",
            topic_id=topic.id,
            content="量化过去8个季度Services业务营收占比提升对自由现金流转换率的影响",
            search_query="Apple Services revenue gross margin operating cash flow",
            priority=1,
            framework_type="financial",
        )

        queries = build_fact_queries(question, topic)

        self.assertEqual(queries[0], "Apple Services revenue gross margin operating cash flow")
        self.assertFalse(any("过去8个季度" in query for query in queries))

    def test_risk_counter_and_english_queries_are_separate_views(self) -> None:
        topic = Topic(
            id="topic_002",
            query="拼多多当前的高增长模式是否可持续",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
            entity="拼多多",
        )

        self.assertTrue(build_risk_queries(topic))
        self.assertTrue(build_counter_queries(topic))
        self.assertTrue(is_us_stock(topic))
        self.assertTrue(any("PDD Holdings" in query for query in build_english_queries(topic)))


if __name__ == "__main__":
    unittest.main()
