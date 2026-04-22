from __future__ import annotations

import unittest

from app.agent.steps.extract import _calc_clarity_score, extract_evidence, is_noise_evidence, is_truncated_fragment
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic


class ExtractStepTest(unittest.TestCase):
    def test_extract_evidence_from_fixture_source(self) -> None:
        topic = Topic(
            id="topic_001",
            query="研究贸易企业违约原因",
            topic="贸易企业违约",
            goal="识别违约成因",
            type="theme",
        )
        questions = [
            Question(id="q1", topic_id=topic.id, content="违约企业的财务共性是什么", priority=1),
        ]
        sources = [
            Source(
                id="s1",
                question_id="q1",
                url="https://example.com/report-1",
                title="Fixture Research Report",
                source_type="report",
                provider="fixture",
                published_at=None,
                content="该企业资产负债率连续三年高于70%，且自由现金流连续为负。公开资料提到大客户集中度偏高。",
            )
        ]

        evidence = extract_evidence(topic, questions, sources)

        self.assertGreaterEqual(len(evidence), 2)
        self.assertTrue(all(item.source_id == "s1" for item in evidence))
        self.assertTrue(all(item.evidence_type in {"fact", "data", "claim", "risk_signal"} for item in evidence))
        self.assertTrue(all(item.stance in {"support", "counter", "neutral"} for item in evidence))
        self.assertTrue(all(item.quality_score is not None for item in evidence))
        self.assertTrue(all("<" not in item.content and ">" not in item.content for item in evidence))

    def test_extract_preserves_contrast_sentence_for_stance(self) -> None:
        topic = Topic(
            id="topic_002",
            query="研究贸易企业风险",
            topic="贸易企业",
            goal="识别风险信号",
            type="theme",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="现金流是否改善", priority=1)]
        sources = [
            Source(
                id="s1",
                question_id="q1",
                url="https://example.com/report-2",
                title="Contrast Evidence",
                source_type="report",
                provider="fixture",
                published_at=None,
                content="资产负债率偏高，但是经营活动现金流已转正。",
            )
        ]

        evidence = extract_evidence(topic, questions, sources)

        self.assertEqual(len(evidence), 1)
        self.assertIn("但是", evidence[0].content)
        self.assertEqual(evidence[0].stance, "counter")

    def test_extract_rejects_html_and_navigation_noise(self) -> None:
        topic = Topic(
            id="topic_003",
            query="研究宁德时代",
            topic="宁德时代研究价值",
            goal="识别研究价值",
            type="company",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1)]
        sources = [
            Source(
                id="s1",
                question_id="q1",
                url="https://example.com/noise",
                title="Noise",
                source_type="website",
                provider="fixture",
                published_at=None,
                content="<nav>首页 登录 注册</nav><script>alert(1)</script>宁德时代近年研发投入持续增长，动力电池市场份额保持领先。",
            )
        ]

        evidence = extract_evidence(topic, questions, sources)

        self.assertTrue(evidence)
        self.assertTrue(all("登录" not in item.content and "script" not in item.content for item in evidence))
        self.assertTrue(any("研发投入" in item.content or "市场份额" in item.content for item in evidence))

    def test_extract_rejects_pdf_gibberish(self) -> None:
        topic = Topic(
            id="topic_004",
            query="拼多多当前的高增长模式是否具有可持续性",
            topic="拼多多高增长模式可持续性",
            goal="评估增长质量",
            type="company",
            entity="拼多多",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="收入和利润增长来自哪些核心驱动", priority=1)]
        sources = [
            Source(
                id="s1",
                question_id="q1",
                flow_type="risk",
                url="https://example.com/pdd.pdf",
                title="[PDF] PDD Holdings 深度研究报告",
                source_type="report",
                provider="fixture",
                published_at=None,
                content="GY:0e isD\\ Jƀ:+K。@ @]¯ n05x$و Q@ A4PEPEPEPEUm4S。ƹ2JHzs4e/6tg+f。",
            )
        ]

        evidence = extract_evidence(topic, questions, sources)

        self.assertEqual(evidence, [])

    def test_extract_rejects_truncated_numeric_fragments(self) -> None:
        self.assertTrue(is_noise_evidence("货币资金 7"))
        self.assertTrue(is_noise_evidence("流动资产合计 16"))
        self.assertTrue(is_noise_evidence("12345"))
        self.assertTrue(is_truncated_fragment("营业收入 84 净利润 67 毛利率 2"))
        self.assertEqual(_calc_clarity_score("货币资金 7"), 0.0)
        self.assertGreater(
            _calc_clarity_score("宁德时代2025年经营活动现金流同比改善至120亿元，现金回款质量提升"),
            0.35,
        )

    def test_extract_filters_pdf_header_footer_and_promotional_noise(self) -> None:
        self.assertTrue(is_noise_evidence("第12页 2025年年度报告全文"))
        self.assertTrue(is_noise_evidence("联系电话：010-12345678 公司网址：www.example.com"))
        self.assertTrue(is_noise_evidence("公司坚持创新驱动发展，坚定推进高质量发展"))

    def test_extract_penalizes_stale_fiscal_year_evidence(self) -> None:
        topic = Topic(
            id="topic_stale",
            query="研究宁德时代财务质量",
            topic="宁德时代财务质量",
            goal="识别财务质量",
            type="company",
            entity="宁德时代",
        )
        questions = [Question(id="q1", topic_id=topic.id, content="财务质量如何", priority=1, framework_type="financial")]
        stale_source = Source(
            id="s1",
            question_id="q1",
            url="https://example.com/old",
            title="宁德时代2021年财务数据",
            source_type="report",
            provider="fixture",
            published_at="2021-12-31",
            content="宁德时代2021年营业收入100亿元，同比增长10%，净利润20亿元，毛利率24.6%。",
        )

        evidence = extract_evidence(topic, questions, [stale_source])

        self.assertTrue(evidence)
        self.assertTrue(any("stale_source" in item.quality_notes for item in evidence))
        self.assertTrue(all((item.evidence_score or 0) < 0.6 for item in evidence))


if __name__ == "__main__":
    unittest.main()
