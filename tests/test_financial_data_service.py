from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.pipeline import _append_financial_source, _snapshot_to_evidence, research_pipeline
from app.config import Settings
from app.models.financial import FinancialMetric, FinancialSnapshot
from app.models.judgment import ConfidenceBasis, Judgment, PeerContext
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.financial_data_service import build_peer_comparison, build_peer_universe, derive_peer_positioning, fetch_financial_snapshot, resolve_symbol


class FinancialDataServiceTest(unittest.TestCase):
    def test_resolve_symbol_for_known_company(self) -> None:
        topic = Topic(
            id="topic_test",
            query="研究拼多多是否值得进一步研究",
            entity="拼多多",
            topic="拼多多研究价值",
            goal="判断是否值得继续研究",
            type="company",
        )

        self.assertEqual(resolve_symbol(topic), "PDD")

    def test_fetch_snapshot_uses_real_provider_payload_shape(self) -> None:
        topic = Topic(
            id="topic_test",
            query="研究拼多多是否值得进一步研究",
            entity="拼多多",
            topic="拼多多研究价值",
            goal="判断是否值得继续研究",
            type="company",
        )
        metrics = [
            FinancialMetric(name="revenue", value=1000, unit=None, period="2025-12-31", source="yfinance.income_stmt"),
            FinancialMetric(name="net_income", value=200, unit=None, period="2025-12-31", source="yfinance.income_stmt"),
            FinancialMetric(name="operating_cash_flow", value=300, unit=None, period="2025-12-31", source="yfinance.cashflow"),
        ]
        peer_rows = [{"symbol": "PDD", "marketCap": 100, "trailingPE": 12}]

        with patch("app.services.financial_data_service._fetch_yfinance_snapshot", return_value=(metrics, peer_rows)):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "SUCCESS")
        self.assertEqual(snapshot.symbol, "PDD")
        self.assertTrue(snapshot.metrics)
        self.assertTrue(snapshot.peer_comparison)
        self.assertEqual(snapshot.provider, "yfinance")
        self.assertEqual(snapshot.provider_status.status, "SUCCESS")

    def test_unknown_symbol_falls_back_to_search(self) -> None:
        topic = Topic(
            id="topic_test",
            query="研究某某科技是否值得进一步研究",
            entity="某某科技",
            topic="某某科技研究价值",
            goal="判断是否值得继续研究",
            type="company",
        )
        results = [
            {
                "title": "某某科技股价与市值信息",
                "url": "https://example.com/market",
                "source_type": "news",
                "provider": "tavily",
                "content": "某某科技近期股价波动，市场关注其市值和财报表现。",
            }
        ]

        with patch("app.services.financial_data_service.search", return_value=results):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "FALLBACK_USED")
        self.assertEqual(snapshot.provider, "tavily_search_fallback")
        self.assertTrue(snapshot.metrics)

    def test_unlisted_company_does_not_use_stock_fallback(self) -> None:
        topic = Topic(
            id="topic_test",
            query="华为股票研究价值",
            entity="华为",
            topic="华为研究价值",
            goal="识别华为未上市边界",
            type="company",
            listing_status="private",
        )

        with patch("app.services.financial_data_service.search") as search_mock:
            snapshot = fetch_financial_snapshot(topic)

        search_mock.assert_not_called()
        self.assertEqual(snapshot.status, "UNSUPPORTED_MARKET")
        self.assertEqual(snapshot.provider, "listing_status_engine")
        self.assertIsNone(snapshot.symbol)
        self.assertIn("未公开上市", snapshot.note or "")

    def test_pipeline_appends_structured_financial_source_when_available(self) -> None:
        snapshot = FinancialSnapshot(
            entity="拼多多",
            symbol="PDD",
            provider="yfinance",
            status="SUCCESS",
            metrics=[
                FinancialMetric(
                    name="revenue",
                    value=123.45,
                    unit="USD",
                    period="latest",
                    source="yfinance.income_stmt",
                )
            ],
            peer_symbols=["BABA", "JD"],
            peer_comparison=[{"symbol": "PDD", "marketCap": 100}, {"symbol": "BABA", "marketCap": 80}],
            note="test snapshot",
        )
        source = Source(
            id="s1",
            question_id="q1",
            title="拼多多财报",
            url="https://example.com/pdd",
            source_type="news",
            provider="test",
            content="拼多多营收增长，现金流改善。",
        )
        judgment = Judgment(
            topic_id="topic_test",
            conclusion="结构化金融快照已进入证据链。",
            conclusion_evidence_ids=[],
            clusters=[],
            risk=[],
            unknown=[],
            evidence_gaps=[],
            confidence="low",
            confidence_basis=ConfidenceBasis(
                source_count=1,
                source_diversity="low",
                conflict_level="none",
                evidence_gap_level="high",
                effective_evidence_count=1,
            ),
            research_actions=[],
            peer_context=PeerContext(
                required=True,
                status="needs_research",
                peer_entities=[],
                comparison_rows=[],
                note="unit test peer context",
            ),
        )

        with patch("app.agent.pipeline.fetch_financial_snapshot", return_value=snapshot), patch(
            "app.agent.pipeline.retrieve_information",
            return_value=[source],
        ), patch("app.agent.pipeline.inject_official_sources", return_value=[]), patch(
            "app.agent.pipeline._enrich_and_rank_sources",
            side_effect=lambda sources, topic: sources,
        ), patch(
            "app.agent.pipeline.auto_research_loop",
            side_effect=lambda topic, questions, sources, evidence, variables, judgment, actions: SimpleNamespace(
                sources=sources,
                evidence=evidence,
                variables=variables,
                judgment=judgment,
                actions=actions,
                trace=[],
            ),
        ), patch("app.agent.pipeline.reason_and_generate", return_value=judgment), patch(
            "app.agent.pipeline.apply_investment_layer",
            side_effect=lambda topic, questions, evidence, judgment, variables: judgment,
        ), patch(
            "app.agent.pipeline.synthesize_role_outputs",
            return_value=[],
        ), patch("app.agent.steps.decompose.call_llm", side_effect=RuntimeError("skip llm in unit test")), patch(
            "app.agent.steps.define.call_llm",
            side_effect=RuntimeError("skip llm in unit test"),
        ), patch("app.agent.pipeline.extract_evidence", return_value=[]):
            result = research_pipeline("研究拼多多是否值得进一步研究")

        self.assertEqual(result["financial_snapshot"].status, "SUCCESS")
        self.assertTrue(any(item.provider == "yfinance" for item in result["sources"]))
        self.assertTrue(result["judgment"].peer_context.comparison_rows)

    def test_structured_financial_snapshot_becomes_evidence(self) -> None:
        topic = Topic(
            id="topic_nvda",
            query="研究英伟达研究价值",
            entity="英伟达",
            topic="英伟达研究价值",
            goal="判断是否值得继续研究",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        questions = [
            Question(
                id="q1",
                topic_id=topic.id,
                content="英伟达收入、利润率和现金流质量如何？",
                priority=1,
                framework_type="financial",
            ),
            Question(
                id="q2",
                topic_id=topic.id,
                content="英伟达估值是否合理？",
                priority=2,
                framework_type="valuation",
            ),
        ]
        snapshot = FinancialSnapshot(
            entity="英伟达",
            symbol="NVDA",
            provider="finnhub",
            status="FALLBACK_USED",
            metrics=[
                FinancialMetric(name="revenue_growth", value=120.1, unit="%", period="TTM", source="finnhub.metric"),
                FinancialMetric(name="pe_ttm", value=40.5, unit=None, period="TTM", source="finnhub.metric"),
            ],
        )
        sources = _append_financial_source([], snapshot, topic, questions)

        evidence = _snapshot_to_evidence(snapshot, topic, questions, sources, [])

        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(item.evidence_type == "data" for item in evidence))
        self.assertTrue(all("structured_financial_snapshot" in item.quality_notes for item in evidence))
        self.assertEqual({item.source_tier for item in evidence}, {"professional"})
        self.assertIn("营收同比增速", evidence[0].content)
        self.assertEqual(evidence[0].question_id, "q1")
        self.assertEqual(evidence[1].question_id, "q2")

    def test_a_share_routes_to_fallback_provider_with_structured_attempts(self) -> None:
        topic = Topic(
            id="topic_catl",
            query="研究宁德时代财务质量",
            entity="宁德时代",
            topic="宁德时代财务质量",
            goal="判断财务和信用质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="A_share",
        )
        metrics = [
            FinancialMetric(name="营业收入", value="2025 营业收入 1000亿元", unit=None, period="latest", source="akshare.stock_financial_abstract")
        ]

        with patch("app.services.financial_data_service._fetch_akshare_snapshot", return_value=(metrics, [])):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "FALLBACK_USED")
        self.assertEqual(snapshot.provider, "akshare")
        self.assertEqual(snapshot.provider_attempts[0].provider, "yfinance")
        self.assertEqual(snapshot.provider_attempts[0].status, "UNSUPPORTED_MARKET")
        self.assertEqual(snapshot.provider_attempts[1].status, "SUCCESS")
        self.assertTrue(snapshot.fallback_used)

    def test_hk_snapshot_tries_provider_specific_symbol_variants(self) -> None:
        topic = Topic(
            id="topic_tencent",
            query="研究腾讯财务质量",
            entity="腾讯",
            topic="腾讯财务质量",
            goal="判断财务和估值质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="HK",
        )
        metrics = [
            FinancialMetric(name="market_cap", value=1000, unit="HKD", period="latest", source="yfinance.info")
        ]

        def _fake_yfinance(symbol: str, peer_key: str | None = None):
            if symbol == "0700.HK":
                raise RuntimeError("No data found for 0700.HK")
            if symbol == "700.HK":
                return metrics, []
            raise RuntimeError(f"unexpected symbol {symbol}")

        with patch("app.services.financial_data_service._fetch_yfinance_snapshot", side_effect=_fake_yfinance):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "SUCCESS")
        self.assertEqual(snapshot.provider, "yfinance")
        self.assertEqual(snapshot.symbol, "0700.HK")
        self.assertEqual(snapshot.provider_status.symbol, "700.HK")
        self.assertIn("0700.HK, 700.HK", snapshot.provider_status.message)

    def test_hk_all_providers_failed_uses_router_status_not_last_provider(self) -> None:
        topic = Topic(
            id="topic_tencent",
            query="研究腾讯财务质量",
            entity="腾讯",
            topic="腾讯财务质量",
            goal="判断财务和估值质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="HK",
        )

        with patch(
            "app.services.financial_data_service._fetch_yfinance_snapshot",
            side_effect=RuntimeError("Failed to perform, curl: (6) Could not resolve host: guce.yahoo.com"),
        ), patch(
            "app.services.financial_data_service._fetch_akshare_snapshot",
            side_effect=RuntimeError("akshare hk endpoint unavailable"),
        ), patch(
            "app.services.financial_data_service.search",
            side_effect=RuntimeError("Could not resolve host: api.tavily.com"),
        ):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "ALL_PROVIDERS_FAILED")
        self.assertEqual(snapshot.provider, "provider_router")
        self.assertEqual(snapshot.provider_status.status, "ALL_PROVIDERS_FAILED")
        self.assertEqual(snapshot.symbol, "0700.HK")
        self.assertEqual(snapshot.provider_attempts[0].provider, "yfinance")
        self.assertEqual(snapshot.provider_attempts[0].status, "NETWORK_ERROR")
        self.assertEqual(snapshot.provider_attempts[-1].provider, "tavily_search_fallback")
        self.assertEqual(snapshot.provider_attempts[-1].status, "NETWORK_ERROR")
        self.assertIn("investing: NETWORK_ERROR", snapshot.note or "")

    @patch("httpx.get")
    def test_us_snapshot_uses_finnhub_when_yfinance_fails(self, get_mock) -> None:
        class _Response:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self._payload

        def _fake_get(url: str, **kwargs):
            self.assertEqual(kwargs["params"]["token"], "test-finnhub-key")
            self.assertEqual(kwargs["params"]["symbol"], "NVDA")
            if url.endswith("/stock/profile2"):
                return _Response({"ticker": "NVDA", "name": "NVIDIA Corp", "marketCapitalization": 3000000, "currency": "USD"})
            if url.endswith("/quote"):
                return _Response({"c": 900.0, "pc": 880.0, "h": 905.0, "l": 870.0})
            if url.endswith("/stock/metric"):
                return _Response({"metric": {"peTTM": 40.5, "grossMarginTTM": 73.2, "revenueGrowthTTMYoy": 120.1}})
            return _Response({})

        topic = Topic(
            id="topic_nvda",
            query="研究英伟达财务质量",
            entity="英伟达",
            topic="英伟达财务质量",
            goal="判断财务和估值质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        get_mock.side_effect = _fake_get

        with patch(
            "app.services.financial_data_service._fetch_yfinance_snapshot",
            side_effect=RuntimeError("Could not resolve host: guce.yahoo.com"),
        ), patch(
            "app.services.financial_data_service.get_settings",
            return_value=Settings(finnhub_api_key="test-finnhub-key", finnhub_base_url="https://finnhub.example/api/v1"),
        ), patch("app.services.financial_data_service.build_peer_comparison", return_value=[]):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "FALLBACK_USED")
        self.assertEqual(snapshot.provider, "finnhub")
        self.assertEqual(snapshot.provider_status.status, "SUCCESS")
        self.assertEqual(snapshot.provider_status.symbol, "NVDA")
        self.assertTrue(any(metric.source.startswith("finnhub.") for metric in snapshot.metrics))
        self.assertEqual(snapshot.provider_attempts[0].provider, "yfinance")
        self.assertEqual(snapshot.provider_attempts[1].provider, "polygon")
        self.assertEqual(snapshot.provider_attempts[2].provider, "finnhub")

    @patch("httpx.get")
    def test_us_snapshot_uses_massive_polygon_provider_when_yfinance_fails(self, get_mock) -> None:
        class _Response:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self._payload

        def _fake_get(url: str, **kwargs):
            self.assertEqual(kwargs["params"]["apiKey"], "test-massive-key")
            if url.endswith("/v3/reference/tickers/NVDA"):
                return _Response(
                    {
                        "status": "OK",
                        "results": {
                            "ticker": "NVDA",
                            "name": "NVIDIA Corp",
                            "market_cap": 3000000,
                            "currency_name": "USD",
                            "weighted_shares_outstanding": 24000000000,
                        },
                    }
                )
            if url.endswith("/v2/aggs/ticker/NVDA/prev"):
                return _Response({"status": "OK", "results": [{"c": 900.0, "h": 905.0, "l": 870.0, "v": 1000000}]})
            return _Response({})

        topic = Topic(
            id="topic_nvda",
            query="研究英伟达财务质量",
            entity="英伟达",
            topic="英伟达财务质量",
            goal="判断财务和估值质量",
            type="company",
            research_object_type="listed_company",
            listing_status="listed",
            market_type="US",
        )
        get_mock.side_effect = _fake_get

        with patch(
            "app.services.financial_data_service._fetch_yfinance_snapshot",
            side_effect=RuntimeError("Could not resolve host: guce.yahoo.com"),
        ), patch(
            "app.services.financial_data_service.get_settings",
            return_value=Settings(massive_api_key="test-massive-key", massive_base_url="https://massive.example"),
        ), patch("app.services.financial_data_service.build_peer_comparison", return_value=[]):
            snapshot = fetch_financial_snapshot(topic)

        self.assertEqual(snapshot.status, "FALLBACK_USED")
        self.assertEqual(snapshot.provider, "polygon")
        self.assertEqual(snapshot.provider_status.status, "SUCCESS")
        self.assertEqual(snapshot.provider_status.symbol, "NVDA")
        self.assertTrue(any(metric.source.startswith("massive.") for metric in snapshot.metrics))
        self.assertEqual(snapshot.provider_attempts[0].provider, "yfinance")
        self.assertEqual(snapshot.provider_attempts[1].provider, "polygon")

    def test_peer_universe_contains_business_groups_for_known_listed_companies(self) -> None:
        nvda = build_peer_universe("NVDA")
        tencent = build_peer_universe("0700.HK")
        catl = build_peer_universe("300750.SZ")

        self.assertTrue(any(item["ticker"] == "AMD" and item["peer_group"] == "direct_competitor" for item in nvda))
        self.assertTrue(any(item["ticker"] == "TSM" and item["peer_group"] == "value_chain_peer" for item in nvda))
        self.assertTrue(any(item["peer_name"] == "字节跳动" and item["peer_group"] == "business_substitute" for item in tencent))
        self.assertTrue(any(item["ticker"] == "373220.KS" for item in catl))
        self.assertTrue(all("benchmark_dimensions" in item for item in nvda + tencent + catl))

    def test_peer_comparison_uses_unified_benchmark_schema(self) -> None:
        fake_info = {
            "NVDA": {
                "shortName": "NVIDIA",
                "marketCap": 3000,
                "trailingPE": 45.0,
                "enterpriseToEbitda": 35.0,
                "profitMargins": 0.55,
                "grossMargins": 0.73,
                "revenueGrowth": 1.2,
                "debtToEquity": 20.0,
                "returnOnEquity": 0.9,
            },
            "AMD": {
                "shortName": "AMD",
                "marketCap": 300,
                "trailingPE": 30.0,
                "enterpriseToEbitda": 24.0,
                "profitMargins": 0.10,
                "grossMargins": 0.50,
                "revenueGrowth": 0.2,
            },
        }

        class _Ticker:
            def __init__(self, symbol: str) -> None:
                self.info = fake_info.get(symbol, {})

        with patch("yfinance.Ticker", side_effect=_Ticker):
            rows = build_peer_comparison("NVDA", ["AMD"])

        target = rows[0]
        self.assertEqual(target["ticker"], "NVDA")
        self.assertEqual(target["peer_name"], "NVIDIA")
        self.assertEqual(target["revenue_growth"], 1.2)
        self.assertEqual(target["gross_margin"], 0.73)
        self.assertEqual(target["valuation_pe"], 45.0)
        self.assertEqual(target["valuation_ev_ebitda"], 35.0)
        self.assertIn("capex_intensity", target["benchmark_dimensions"])
        self.assertIn("overseas_exposure", target)

    def test_derive_peer_positioning_flags_target_relative_strength(self) -> None:
        rows = [
            {"ticker": "NVDA", "revenue_growth": 1.2, "gross_margin": 0.73, "valuation_pe": 45.0},
            {"ticker": "AMD", "revenue_growth": 0.2, "gross_margin": 0.50, "valuation_pe": 30.0},
            {"ticker": "INTC", "revenue_growth": -0.1, "gross_margin": 0.42, "valuation_pe": 18.0},
        ]

        positioning = derive_peer_positioning(rows, target_symbol="NVDA")

        self.assertEqual(positioning["target_symbol"], "NVDA")
        self.assertIn("growth_above_peer_median", positioning["signals"])
        self.assertIn("margin_above_peer_median", positioning["signals"])
        self.assertIn("valuation_above_peer_median", positioning["signals"])


if __name__ == "__main__":
    unittest.main()
