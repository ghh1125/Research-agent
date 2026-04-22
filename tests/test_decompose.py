from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent.steps.decompose import decompose_problem
from app.models.topic import Topic


class DecomposeStepTest(unittest.TestCase):
    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit"))
    def test_decompose_problem_returns_questions(self, llm_mock) -> None:
        topic = Topic(
            id="topic_001",
            query="研究贸易企业违约原因",
            topic="贸易企业违约",
            goal="识别违约成因",
            type="theme",
        )

        questions = decompose_problem(topic)

        self.assertGreaterEqual(len(questions), 3)
        self.assertLessEqual(len(questions), 8)
        self.assertTrue(all(question.topic_id == topic.id for question in questions))
        self.assertTrue(all(1 <= question.priority <= 5 for question in questions))
        self.assertTrue(all(question.framework_type for question in questions))
        self.assertTrue(all(not question.content.startswith(topic.topic) for question in questions))
        self.assertTrue(any("财务" in question.content or "现金流" in question.content for question in questions))

    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit"))
    def test_decompose_growth_sustainability_uses_growth_framework(self, llm_mock) -> None:
        topic = Topic(
            id="topic_002",
            query="拼多多当前的高增长模式是否具有可持续性，是否值得进入深度研究阶段？",
            entity="拼多多",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
        )

        questions = decompose_problem(topic)
        contents = [question.content for question in questions]

        self.assertTrue(any("收入" in content and "利润" in content for content in contents))
        self.assertTrue(any("用户" in content or "商家" in content for content in contents))
        self.assertTrue(any("竞争" in content and "监管" in content for content in contents))
        self.assertFalse(any("违约" in content for content in contents))
        self.assertIn("financial", {question.framework_type for question in questions})
        self.assertIn("credit", {question.framework_type for question in questions})
        self.assertIn("adversarial", {question.framework_type for question in questions})
        self.assertIn("gap", {question.framework_type for question in questions})

    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit"))
    def test_decompose_manufacturing_company_uses_industry_template(self, llm_mock) -> None:
        topic = Topic(
            id="topic_003",
            query="研究宁德时代是否值得进一步研究",
            entity="宁德时代",
            topic="宁德时代研究价值",
            goal="判断是否值得继续深挖",
            type="company",
        )

        questions = decompose_problem(topic)
        contents = [question.content for question in questions]

        self.assertTrue(any("产能" in content or "毛利率" in content for content in contents))
        self.assertTrue(any("资本开支" in content or "负债结构" in content for content in contents))
        self.assertTrue(any("技术路线" in content or "客户结构" in content for content in contents))

    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("unit"))
    def test_decompose_private_company_switches_from_stock_to_private_workflow(self, llm_mock) -> None:
        topic = Topic(
            id="topic_004",
            query="华为股票研究价值",
            entity="华为",
            topic="华为研究价值",
            goal="识别华为未上市边界",
            type="company",
            listing_status="private",
        )

        questions = decompose_problem(topic)
        contents = [question.content for question in questions]

        self.assertTrue(any("无法直接交易股票" in content for content in contents))
        self.assertTrue(any("产业链" in content or "生态" in content for content in contents))
        self.assertTrue(any("IPO" in content or "资本市场动作" in content for content in contents))
        self.assertFalse(any("公开股票估值" in content for content in contents))

    @patch(
        "app.agent.steps.decompose.call_llm",
        return_value='{"questions":[{"content":"英伟达数据中心收入增速和毛利率是否能由真实需求支撑","search_query":"NVIDIA data center revenue gross margin quarterly results","priority":1,"framework_type":"financial"},{"content":"英伟达在AI算力和关键客户中的竞争位置是否稳固","search_query":"NVIDIA AI accelerator market share key customers","priority":1,"framework_type":"industry"},{"content":"英伟达经营现金流和资本开支是否支持高质量增长","search_query":"NVIDIA operating cash flow capex free cash flow","priority":1,"framework_type":"credit"},{"content":"英伟达当前估值与核心同行相比是否仍有研究空间","search_query":"NVIDIA PE EV EBITDA valuation peer comparison","priority":2,"framework_type":"valuation"},{"content":"英伟达出口管制和客户集中风险会如何影响增长持续性","search_query":"NVIDIA export control customer concentration risk","priority":2,"framework_type":"risk"}]}',
    )
    def test_decompose_uses_llm_first_when_output_is_valid(self, llm_mock) -> None:
        topic = Topic(
            id="topic_llm",
            query="研究英伟达是否值得进一步研究",
            entity="英伟达",
            topic="英伟达研究价值",
            goal="判断是否值得继续深挖",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )

        questions = decompose_problem(topic)

        llm_mock.assert_called_once()
        self.assertEqual(questions[0].content, "英伟达数据中心收入增速和毛利率是否能由真实需求支撑")
        self.assertEqual(questions[0].search_query, "NVIDIA data center revenue gross margin quarterly results")
        self.assertEqual(questions[0].framework_type, "financial")
        self.assertTrue(any(question.framework_type == "adversarial" for question in questions))

    @patch("app.agent.steps.decompose.call_llm", return_value='{"questions":[{"content":"研究英伟达是否值得研究","priority":1}]}')
    def test_decompose_falls_back_when_llm_output_is_too_weak(self, llm_mock) -> None:
        topic = Topic(
            id="topic_bad_llm",
            query="研究英伟达是否值得进一步研究",
            entity="英伟达",
            topic="英伟达研究价值",
            goal="判断是否值得继续深挖",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )

        questions = decompose_problem(topic)

        llm_mock.assert_called_once()
        self.assertGreaterEqual(len(questions), 5)
        self.assertTrue(any("AI算力" in question.content for question in questions))


if __name__ == "__main__":
    unittest.main()
