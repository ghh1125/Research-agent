from __future__ import annotations

import unittest
from hashlib import md5
from unittest.mock import patch

from app.agent.pipeline import research_pipeline
from app.db.repository import InMemoryResearchRepository
from app.models.financial import FinancialSnapshot


class PipelineTest(unittest.TestCase):
    def _fake_search(self, query: str) -> list[dict]:
        digest = md5(query.encode("utf-8")).hexdigest()[:8]
        content = (
            "公开资料显示，研究对象营业收入100亿元，同比增长12%，净利润8亿元，同比增长5%，毛利率24.6%。"
            "公司披露经营现金流12亿元，资本开支6亿元，自由现金流6亿元，同时负债水平仍需要结合财报验证。"
            "行业资料显示公司市场份额18%，同行排名第二，价格竞争格局加剧需要关注。"
            "合规方面需要关注监管资质、许可边界、合同授权和潜在处罚记录。"
            "反证信号包括市场份额提升、经营改善和风险缓解。"
        )
        return [
            {
                "url": f"https://example.com/{digest}/1",
                "title": f"{query} 来源一",
                "source_type": "news",
                "provider": "test-realistic-fixture",
                "published_at": "2026-01-01",
                "content": content,
            },
            {
                "url": f"https://example.com/{digest}/2",
                "title": f"{query} 来源二",
                "source_type": "report",
                "provider": "test-realistic-fixture",
                "published_at": "2026-01-02",
                "content": content,
            },
        ]

    @patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.define.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.auto_research.search")
    @patch("app.agent.steps.retrieve.search")
    def test_research_pipeline_runs_end_to_end(
        self,
        search_mock,
        auto_search_mock,
        define_llm_mock,
        decompose_llm_mock,
        reason_llm_mock,
    ) -> None:
        search_mock.side_effect = self._fake_search
        auto_search_mock.side_effect = self._fake_search
        repository = InMemoryResearchRepository()

        result = research_pipeline("研究贸易企业违约原因", repository=repository)
        judgment = result["judgment"]
        evidence_ids = {item.id for item in result["evidence"]}

        self.assertTrue(judgment.conclusion)
        self.assertTrue(judgment.conclusion_evidence_ids)
        self.assertIsNotNone(repository.get_judgment_by_topic_id(judgment.topic_id))
        self.assertGreaterEqual(len(judgment.risk), 1)
        self.assertTrue(judgment.research_actions)
        self.assertIsNotNone(judgment.research_scope)
        self.assertIsNotNone(judgment.peer_context)
        self.assertIsNotNone(judgment.investment_decision)
        self.assertTrue(judgment.investment_decision.decision_basis)
        self.assertTrue(judgment.confidence_basis.source_count >= 1)
        self.assertTrue(judgment.pressure_tests)
        self.assertTrue(all(item.evidence_ids for item in judgment.risk))
        self.assertEqual(set(result.keys()), {"topic", "questions", "sources", "evidence", "variables", "roles", "judgment", "auto_research_trace", "executive_summary", "financial_snapshot", "early_stop_reason", "report"})
        self.assertIsNotNone(result["financial_snapshot"])
        self.assertTrue(result["variables"])
        self.assertEqual(len(result["roles"]), 5)
        self.assertTrue(all(role.role_prompt for role in result["roles"]))
        self.assertTrue(any(question.coverage_level in {"partial", "covered"} for question in result["questions"]))
        self.assertTrue(any(question.framework_type == "adversarial" for question in result["questions"]))
        self.assertTrue(result["report"].report_sections)
        self.assertTrue(any(section.section_type == "source" for section in result["report"].report_sections))
        self.assertTrue(any(section.section_type == "role" for section in result["report"].report_sections))
        self.assertTrue(any(section.section_type == "variable" for section in result["report"].report_sections))
        self.assertTrue(any(section.section_type == "investment" for section in result["report"].report_sections))
        self.assertTrue(result["report"].markdown.startswith("# 投研初步研究报告"))
        self.assertIn("auto_research_trace", result)
        self.assertIsNotNone(result["executive_summary"])
        self.assertIn("关键变量", result["report"].markdown)
        self.assertIn("多角色视角", result["report"].markdown)
        self.assertIn("投资层判断", result["report"].markdown)
        self.assertTrue(set(judgment.conclusion_evidence_ids).issubset(evidence_ids))
        for risk_item in judgment.risk:
            self.assertTrue(set(risk_item.evidence_ids).issubset(evidence_ids))

    @patch("app.agent.steps.reason.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.define.call_llm", side_effect=RuntimeError("skip llm in unit test"))
    @patch("app.agent.steps.auto_research.search")
    @patch("app.agent.steps.retrieve.search")
    def test_research_pipeline_handles_compliance_query(
        self,
        search_mock,
        auto_search_mock,
        define_llm_mock,
        decompose_llm_mock,
        reason_llm_mock,
    ) -> None:
        search_mock.side_effect = self._fake_search
        auto_search_mock.side_effect = self._fake_search
        repository = InMemoryResearchRepository()

        result = research_pipeline("这个经营权模式有没有合规风险", repository=repository)
        judgment = result["judgment"]

        self.assertIn("合规", judgment.conclusion)
        self.assertTrue(judgment.conclusion_evidence_ids)
        self.assertTrue(judgment.unknown)
        self.assertTrue(result["report"].report_sections)

    def test_pipeline_early_stops_when_sources_are_insufficient(self) -> None:
        repository = InMemoryResearchRepository()
        snapshot = FinancialSnapshot(
            entity="某公司",
            provider="not_applicable",
            status="not_applicable",
            note="unit test snapshot",
        )

        with patch("app.agent.pipeline.fetch_financial_snapshot", return_value=snapshot), patch(
            "app.agent.pipeline.retrieve_information",
            return_value=[],
        ), patch("app.agent.steps.define.call_llm", side_effect=RuntimeError("skip llm in unit test")), patch(
            "app.agent.steps.decompose.call_llm",
            side_effect=RuntimeError("skip llm in unit test"),
        ), patch(
            "app.agent.steps.reason.call_llm",
            side_effect=RuntimeError("skip llm in unit test"),
        ):
            result = research_pipeline("研究某公司是否值得进一步研究", repository=repository)

        self.assertEqual(result["early_stop_reason"], "未获得有效来源且金融快照不可用，当前检索结果不足以支撑本次研究。")
        self.assertEqual(result["executive_summary"].confidence, "low")
        self.assertLess(len(result["sources"]), 2)
        self.assertIn(
            result["financial_snapshot"].status,
            {
                "SUCCESS",
                "PARTIAL_SUCCESS",
                "FALLBACK_USED",
                "SYMBOL_NOT_FOUND",
                "UNSUPPORTED_MARKET",
                "ALL_PROVIDERS_FAILED",
                "not_applicable",
            },
        )


if __name__ == "__main__":
    unittest.main()
