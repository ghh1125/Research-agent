from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.steps.define import define_problem


class DefineStepTest(unittest.TestCase):
    def test_define_problem_returns_topic(self) -> None:
        topic = define_problem("研究贸易企业违约原因")

        self.assertEqual(topic.query, "研究贸易企业违约原因")
        self.assertTrue(topic.topic)
        self.assertTrue(topic.goal)
        self.assertIn(topic.type, {"company", "theme", "compliance", "general"})

    def test_define_extracts_company_entity_and_concise_topic(self) -> None:
        topic = define_problem("研究宁德时代是否值得进一步研究")

        self.assertEqual(topic.entity, "宁德时代")
        self.assertEqual(topic.type, "company")
        self.assertEqual(topic.topic, "宁德时代研究价值")
        self.assertNotEqual(topic.topic, topic.query)

    def test_define_growth_sustainability_query_extracts_company(self) -> None:
        topic = define_problem("拼多多当前的高增长模式是否具有可持续性，是否值得进入深度研究阶段？")

        self.assertEqual(topic.entity, "拼多多")
        self.assertEqual(topic.type, "company")
        self.assertEqual(topic.topic, "拼多多高增长模式可持续性")
        self.assertIn("增长", topic.goal)

    @patch("app.agent.steps.define.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    def test_define_huawei_stock_as_private_company_not_stock_entity(self, llm_mock) -> None:
        topic = define_problem("华为股票研究价值")

        self.assertEqual(topic.entity, "华为")
        self.assertEqual(topic.type, "company")
        self.assertEqual(topic.topic, "华为研究价值")
        self.assertEqual(topic.listing_status, "private")
        self.assertNotIn("华为股票", topic.entity or "")
        self.assertIn("未上市", topic.goal)


if __name__ == "__main__":
    unittest.main()
