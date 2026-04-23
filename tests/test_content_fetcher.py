from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.source import Source
from app.services.content_fetcher import enrich_source_content, enrich_sources_content, should_fetch


class ContentFetcherTest(unittest.TestCase):
    def test_should_fetch_only_high_score_non_pdf_non_paywall_sources(self) -> None:
        self.assertTrue(should_fetch("https://finance.test/article", 0.7))
        self.assertFalse(should_fetch("https://finance.test/report.pdf", 0.9))
        self.assertFalse(should_fetch("https://data.sec.gov/submissions/CIK0001577552.json", 0.9))
        self.assertFalse(should_fetch("https://data.sec.gov/api/xbrl/companyfacts/CIK0001577552.json", 0.9))
        self.assertFalse(should_fetch("https://finance.test/article", 0.49))
        self.assertFalse(should_fetch("https://www.reuters.com/markets/article", 0.9))

    @patch("app.services.content_fetcher.fetch_full_content")
    def test_enrich_source_content_keeps_snippet_when_fetch_fails(self, fetch_mock) -> None:
        fetch_mock.return_value = None
        original = "宁德时代营收增长但现金流仍需验证。"

        self.assertEqual(
            enrich_source_content("https://finance.test/article", original, 0.8),
            None,
        )

    @patch("app.services.content_fetcher.fetch_full_content")
    def test_enrich_sources_content_replaces_with_longer_clean_content(self, fetch_mock) -> None:
        fetch_mock.return_value = "宁德时代2025年营收增长，经营活动现金流改善，毛利率仍受价格竞争影响。" * 5
        source = Source(
            id="s1",
            question_id="q1",
            search_query="宁德时代 财报",
            title="宁德时代财报",
            url="https://finance.test/article",
            source_type="website",
            provider="fixture",
            source_score=0.8,
            content="宁德时代营收增长。",
        )

        enriched = enrich_sources_content([source], max_workers=1)

        self.assertEqual(enriched[0].content, source.content)
        self.assertIsNotNone(enriched[0].enriched_content)
        self.assertGreater(len(enriched[0].enriched_content or ""), len(source.content))


if __name__ == "__main__":
    unittest.main()
