from __future__ import annotations

import unittest
from hashlib import md5
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _fake_search(self, query: str) -> list[dict]:
        digest = md5(query.encode("utf-8")).hexdigest()[:8]
        content = (
            "公开资料显示，研究对象营收增长但现金流承压，毛利率下降和行业竞争加剧需要关注。"
            "公司披露经营现金流改善，同时负债水平和资本开支仍需要结合财报验证。"
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
    def test_research_endpoint_returns_structured_response(
        self,
        search_mock,
        auto_search_mock,
        define_llm_mock,
        decompose_llm_mock,
        reason_llm_mock,
    ) -> None:
        search_mock.side_effect = self._fake_search
        auto_search_mock.side_effect = self._fake_search
        response = self.client.post("/research", json={"query": "研究贸易企业违约原因"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {"topic", "questions", "sources", "evidence", "variables", "roles", "judgment", "auto_research_trace", "executive_summary", "financial_snapshot", "early_stop_reason", "report"},
        )
        self.assertTrue(body["sources"])
        self.assertTrue(all(item["content"] for item in body["sources"]))
        self.assertTrue(all("tier" in item and "source_score" in item for item in body["sources"]))
        self.assertTrue(all(item["flow_type"] in {"fact", "risk", "counter"} for item in body["sources"]))
        self.assertTrue(all(item["flow_type"] in {"fact", "risk", "counter"} for item in body["evidence"]))
        self.assertTrue(all("evidence_score" in item for item in body["evidence"]))
        self.assertTrue(all(item["stance"] in {"support", "counter", "neutral"} for item in body["evidence"]))
        self.assertIn("variables", body)
        self.assertEqual(len(body["roles"]), 5)
        self.assertEqual(
            {item["role_id"] for item in body["roles"]},
            {"fact_researcher", "risk_officer", "counter_analyst", "synthesis_analyst", "investment_manager"},
        )
        self.assertTrue(all(item["role_description"] for item in body["roles"]))
        self.assertTrue(all(item["role_prompt"] for item in body["roles"]))
        self.assertTrue(all(item["operating_rules"] for item in body["roles"]))
        self.assertTrue(all(item["forbidden_actions"] for item in body["roles"]))
        self.assertTrue(body["judgment"]["conclusion_evidence_ids"])
        self.assertIn("clusters", body["judgment"])
        self.assertIn("pressure_tests", body["judgment"])
        self.assertIn("evidence_gaps", body["judgment"])
        self.assertIn("confidence_basis", body["judgment"])
        self.assertIn("research_actions", body["judgment"])
        self.assertTrue(all("objective" in item and "query_templates" in item for item in body["judgment"]["research_actions"]))
        self.assertIn("research_scope", body["judgment"])
        self.assertIn("trend_signals", body["judgment"])
        self.assertIn("peer_context", body["judgment"])
        self.assertIn("investment_decision", body["judgment"])
        self.assertIn("confidence", body["judgment"])
        self.assertIn("reviewer_status", body["judgment"])
        self.assertIn("executive_summary", body)
        self.assertIn("financial_snapshot", body)
        self.assertIn("status", body["financial_snapshot"])
        self.assertIn("one_line_conclusion", body["executive_summary"])
        self.assertIn("decision_basis", body["judgment"]["investment_decision"])
        self.assertIn("decision_target", body["judgment"]["investment_decision"])
        self.assertTrue(all("theme" in item for item in body["judgment"]["clusters"]))
        self.assertTrue(all("attack_type" in item and "severity" in item for item in body["judgment"]["pressure_tests"]))
        self.assertTrue(all("text" in item and "evidence_ids" in item for item in body["judgment"]["risk"]))
        self.assertTrue(all(isinstance(item, str) for item in body["judgment"]["unknown"]))
        self.assertTrue(body["report"]["report_sections"])
        self.assertTrue(any(item["section_type"] == "role" for item in body["report"]["report_sections"]))
        self.assertTrue(any(item["section_type"] == "variable" for item in body["report"]["report_sections"]))
        self.assertTrue(any(item["section_type"] == "investment" for item in body["report"]["report_sections"]))
        self.assertTrue(body["report"]["markdown"].startswith("# 投研初步研究报告"))

    def test_research_endpoint_rejects_empty_query(self) -> None:
        response = self.client.post("/research", json={"query": ""})

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
