from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config import Settings, get_settings
from app.models.topic import Topic
from app.services.search_providers.supplemental import (
    ProviderSearchResult,
    SecEdgarSupplementalProvider,
    search_supplemental_sources,
)
from app.services.search_providers.tavily import TavilySearchProvider
from app.services.search_service import get_search_provider, search


class SearchProviderTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("SEARCH_PROVIDER", None)
        os.environ.pop("TAVILY_API_KEY", None)
        get_settings.cache_clear()

    def test_auto_uses_tavily_when_api_key_exists(self) -> None:
        get_settings.cache_clear()

        provider = get_search_provider()

        self.assertIsInstance(provider, TavilySearchProvider)

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
