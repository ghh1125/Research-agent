from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.source import Source
from app.services.pdf_service import _extract_table_like_rows, _score_pdf_page, _select_high_value_pages, extract_financial_rows, parse_pdf_source


class PdfServiceTest(unittest.TestCase):
    def test_non_pdf_source_is_preserved(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="普通网页",
            url="https://example.com/article",
            source_type="news",
            provider="test",
            content="这是一条普通网页内容。",
        )

        parsed = parse_pdf_source(source)

        self.assertEqual(parsed.pdf_parse_status, "not_pdf")
        self.assertEqual(parsed.content, source.content)

    def test_invalid_pdf_fails_safely(self) -> None:
        source = Source(
            id="s1",
            question_id="q1",
            title="公司年报 PDF",
            url="https://example.com/report.pdf",
            source_type="report",
            provider="test",
            content="摘要内容",
            is_pdf=True,
            pdf_parse_status="not_attempted",
        )

        with patch("app.services.pdf_service._download_pdf", return_value=b"not a pdf"):
            parsed = parse_pdf_source(source)

        self.assertEqual(parsed.pdf_parse_status, "failed")
        self.assertEqual(parsed.content, source.content)

    def test_table_like_rows_extract_financial_rows(self) -> None:
        text = """
        营业收入 2024 123.4 2023 100.1
        普通文字 没有足够数字
        operating cash flow 2024 -12.3 2023 8.1
        """

        rows = _extract_table_like_rows(text)

        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all("numbers" in row for row in rows))

    def test_extract_financial_rows_from_pdfplumber_tables(self) -> None:
        tables = [
            [
                ["项目", "2024", "2023"],
                ["营业收入", "123.4", "100.1"],
                ["普通行", "1", "2"],
                ["Operating cash flow", "-12.3", "8.1"],
            ]
        ]

        rows = extract_financial_rows(tables)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["row"][0], "营业收入")

    def test_pdf_page_scoring_prefers_financial_pages_over_toc(self) -> None:
        toc = _score_pdf_page("目录 第一节 释义 第二节 公司简介 联系电话 传真", 1)
        financial = _score_pdf_page(
            "主要会计数据 营业收入 1,234.5亿元 同比增长 22.1% 归属于上市公司股东的净利润 321.0亿元 毛利率 24.5%",
            18,
        )

        self.assertGreater(financial["page_score"], toc["page_score"])
        self.assertEqual(financial["page_type"], "financial")

    def test_select_high_value_pages_can_skip_front_matter(self) -> None:
        records = [
            {"index": 0, "text": "封面", "meta": _score_pdf_page("封面", 1)},
            {"index": 1, "text": "目录 第一节", "meta": _score_pdf_page("目录 第一节", 2)},
            {
                "index": 2,
                "text": "主要会计数据 营业收入 100亿元 同比增长 10%",
                "meta": _score_pdf_page("主要会计数据 营业收入 100亿元 同比增长 10%", 3),
            },
        ]

        selected = _select_high_value_pages(records, max_pages=2)

        self.assertIn(2, selected)


if __name__ == "__main__":
    unittest.main()
