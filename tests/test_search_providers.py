from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config import Settings, get_settings
from app.models.topic import Topic
from app.services.search_providers.supplemental import (
    CompanyIRSupplementalProvider,
    ProviderSearchResult,
    SecEdgarSupplementalProvider,
    search_supplemental_sources,
)
from app.services.search_providers.tavily import TavilySearchProvider
from app.services.search_providers.multi import MultiSearchProvider
from app.services.search_providers.web import ExaSearchProvider, GoogleCustomSearchProvider, SerperSearchProvider
from app.services.search_service import get_search_provider, get_search_provider_status, search


class SearchProviderTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("SEARCH_PROVIDER", None)
        os.environ.pop("TAVILY_API_KEY", None)
        os.environ.pop("SERPER_API_KEY", None)
        os.environ.pop("GOOGLE_SEARCH_API_KEY", None)
        os.environ.pop("GOOGLE_SEARCH_CX", None)
        os.environ.pop("EXA_API_KEY", None)
        get_settings.cache_clear()

    def test_auto_uses_multi_search_when_api_key_exists(self) -> None:
        get_settings.cache_clear()

        provider = get_search_provider()

        self.assertIsInstance(provider, MultiSearchProvider)
        self.assertTrue(any(isinstance(item, TavilySearchProvider) for item in provider.providers))

    def test_can_switch_to_tavily_provider(self) -> None:
        os.environ["SEARCH_PROVIDER"] = "tavily"
        get_settings.cache_clear()

        provider = get_search_provider()

        self.assertIsInstance(provider, TavilySearchProvider)

    def test_search_uses_real_provider(self) -> None:
        try:
            results = search("研究贸易企业违约原因")
        except RuntimeError as exc:
            self.skipTest(f"Real Tavily provider unavailable in this environment: {exc}")

        self.assertTrue(results)
        self.assertEqual(results[0]["provider"], "tavily")
        self.assertTrue(results[0]["content"])

    @patch("httpx.post")
    def test_tavily_uses_advanced_raw_content_request(self, post_mock) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "url": "https://example.com/report",
                            "title": "宁德时代财报",
                            "published_date": "2026-03-31",
                            "raw_content": "宁德时代2025年营收增长，经营现金流改善。",
                        }
                    ]
                }

        post_mock.return_value = _Response()
        provider = TavilySearchProvider(Settings(tavily_api_key="test-key", tavily_max_results=1))

        results = provider.search("宁德时代 财报")

        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["search_depth"], "advanced")
        self.assertEqual(payload["max_results"], 1)
        self.assertTrue(payload["include_raw_content"])
        self.assertFalse(payload["include_images"])
        self.assertEqual(payload["days"], 180)
        self.assertEqual(results[0]["content"], "宁德时代2025年营收增长，经营现金流改善。")
        self.assertEqual(results[0]["published_at"], "2026-03-31")

    def test_auto_multi_search_includes_configured_external_search_providers(self) -> None:
        settings = Settings(
            tavily_api_key="tvly-test",
            serper_api_key="serper-test",
            google_search_api_key="google-test",
            google_search_cx="cx-test",
            exa_api_key="exa-test",
        )

        provider = get_search_provider(settings)

        self.assertIsInstance(provider, MultiSearchProvider)
        provider_types = {type(item) for item in provider.providers}
        self.assertIn(TavilySearchProvider, provider_types)
        self.assertIn(SerperSearchProvider, provider_types)
        self.assertIn(GoogleCustomSearchProvider, provider_types)
        self.assertIn(ExaSearchProvider, provider_types)

    def test_search_provider_status_is_ui_safe_and_marks_enabled_keys(self) -> None:
        settings = Settings(
            tavily_api_key="tavily-secret",
            serper_api_key="serper-secret",
            google_search_api_key="google-secret",
            google_search_cx="cx-id",
            exa_api_key="exa-secret",
        )

        rows = get_search_provider_status(settings)

        self.assertEqual({row["provider"] for row in rows}, {"Tavily", "Serper", "Google Custom Search", "Exa"})
        self.assertTrue(all(row["enabled"] for row in rows))
        self.assertFalse(any("secret" in str(row) for row in rows))

    def test_google_search_status_requires_api_key_and_cx(self) -> None:
        settings = Settings(google_search_api_key="google-secret", google_search_cx="")

        google_row = next(row for row in get_search_provider_status(settings) if row["provider"] == "Google Custom Search")

        self.assertFalse(google_row["enabled"])
        self.assertIn("同时配置", google_row["note"])

    @patch("httpx.post")
    def test_serper_provider_normalizes_google_results(self, post_mock) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "organic": [
                        {
                            "link": "https://ir.example.com/report",
                            "title": "Example Annual Report",
                            "snippet": "Example revenue and operating cash flow improved.",
                            "date": "2026-02-01",
                        }
                    ]
                }

        post_mock.return_value = _Response()
        provider = SerperSearchProvider(Settings(serper_api_key="serper-test", serper_max_results=3))

        results = provider.search("Example annual report")

        self.assertEqual(results[0]["provider"], "serper")
        self.assertEqual(results[0]["url"], "https://ir.example.com/report")
        self.assertEqual(results[0]["published_at"], "2026-02-01")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["q"], "Example annual report")
        self.assertEqual(payload["num"], 3)

    @patch("httpx.get")
    def test_google_custom_search_provider_normalizes_results(self, get_mock) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "items": [
                        {
                            "link": "https://www.sec.gov/example",
                            "title": "Example 10-K",
                            "snippet": "Example 10-K includes revenue and net income.",
                            "pagemap": {"metatags": [{"article:published_time": "2026-01-31"}]},
                        }
                    ]
                }

        get_mock.return_value = _Response()
        provider = GoogleCustomSearchProvider(
            Settings(google_search_api_key="google-test", google_search_cx="cx-test", google_search_max_results=2)
        )

        results = provider.search("Example 10-K")

        self.assertEqual(results[0]["provider"], "google_custom_search")
        self.assertEqual(results[0]["source_type"], "report")
        params = get_mock.call_args.kwargs["params"]
        self.assertEqual(params["key"], "google-test")
        self.assertEqual(params["cx"], "cx-test")
        self.assertEqual(params["num"], 2)

    @patch("httpx.post")
    def test_exa_provider_normalizes_research_results(self, post_mock) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "results": [
                        {
                            "url": "https://research.example.com/report.pdf",
                            "title": "Industry Research PDF",
                            "text": "Market share and gross margin analysis.",
                            "publishedDate": "2026-03-10",
                        }
                    ]
                }

        post_mock.return_value = _Response()
        provider = ExaSearchProvider(Settings(exa_api_key="exa-test", exa_max_results=4))

        results = provider.search("industry market share report")

        self.assertEqual(results[0]["provider"], "exa")
        self.assertEqual(results[0]["source_type"], "report")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["query"], "industry market share report")
        self.assertEqual(payload["numResults"], 4)

    def test_company_ir_supplemental_provider_returns_direct_ir_source(self) -> None:
        topic = Topic(
            id="topic_nvda",
            query="研究英伟达财务质量",
            entity="英伟达",
            topic="英伟达投资研究",
            goal="判断财务与估值质量",
            type="company",
            research_object_type="listed_company",
            market_type="US",
        )
        provider = CompanyIRSupplementalProvider()

        attempt = provider.search("英伟达 annual report investor relations", topic)

        self.assertEqual(attempt.status, "success")
        self.assertEqual(attempt.items[0]["provider"], "company_ir_direct")
        self.assertEqual(attempt.items[0]["source_origin_type"], "company_ir")
        self.assertIn("investor", attempt.items[0]["url"])

    @patch("httpx.get")
    def test_sec_edgar_provider_returns_official_disclosure_source(self, get_mock) -> None:
        class _Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "name": "APPLE INC",
                    "filings": {
                        "recent": {
                            "form": ["10-K", "10-Q"],
                            "filingDate": ["2025-10-31", "2025-08-01"],
                        }
                    },
                }

        get_mock.return_value = _Response()
        topic = Topic(
            id="topic_us",
            query="研究苹果财务质量",
            entity="苹果",
            topic="苹果投资研究",
            goal="判断财务与估值质量",
            type="company",
            research_object_type="listed_company",
            market_type="US",
        )
        provider = SecEdgarSupplementalProvider(Settings(sec_user_agent_email="analyst@example.com"))

        attempt = provider.search("苹果 annual report", topic)

        self.assertEqual(attempt.status, "success")
        self.assertEqual(attempt.items[0]["provider"], "sec_edgar")
        self.assertEqual(attempt.items[0]["source_type"], "regulatory")
        self.assertEqual(attempt.items[0]["source_origin_type"], "official_disclosure")
        self.assertIn("10-K@2025-10-31", attempt.items[0]["content"])
        self.assertIn("analyst@example.com", get_mock.call_args.kwargs["headers"]["User-Agent"])

    def test_supplemental_search_skips_failed_provider_without_blocking_results(self) -> None:
        class _GoodProvider:
            name = "good"

            def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
                return ProviderSearchResult(
                    provider=self.name,
                    status="success",
                    items=[
                        {
                            "url": "https://example.com/official",
                            "title": "官方披露入口",
                            "source_type": "regulatory",
                            "provider": self.name,
                            "published_at": None,
                            "content": "官方披露入口包含收入、净利润与现金流指标。",
                            "source_origin_type": "official_disclosure",
                        }
                    ],
                )

        class _FailingProvider:
            name = "failing"

            def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
                raise RuntimeError("provider timeout")

        results, attempts = search_supplemental_sources(
            "苹果 annual report",
            providers=[_FailingProvider(), _GoodProvider()],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "good")
        self.assertEqual({attempt.provider for attempt in attempts}, {"failing", "good"})
        self.assertEqual(
            next(attempt.status for attempt in attempts if attempt.provider == "failing"),
            "error",
        )


if __name__ == "__main__":
    unittest.main()
