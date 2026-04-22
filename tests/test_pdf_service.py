from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.source import Source
from app.services.pdf_service import (
    _extract_table_like_rows,
    _score_pdf_page,
    _select_high_value_pages,
    classify_pdf_page,
    detect_repeated_headers_footers,
    extract_financial_rows,
    extract_structured_pdf_metrics,
    needs_ocr_fallback,
    parse_pdf_source,
    remove_pdf_noise_lines,
)


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

    def test_classify_pdf_page_locates_financial_statements(self) -> None:
        self.assertEqual(classify_pdf_page("合并资产负债表 总资产 总负债 货币资金"), "balance_sheet")
        self.assertEqual(classify_pdf_page("合并利润表 营业收入 营业成本 净利润"), "income_statement")
        self.assertEqual(classify_pdf_page("合并现金流量表 经营活动产生的现金流量净额 投资活动现金流"), "cashflow_statement")
        self.assertEqual(classify_pdf_page("主要会计数据 营业收入 净利润 毛利率"), "financial_summary")
        self.assertEqual(classify_pdf_page("目录 第一节 释义 第二节 公司简介"), "toc")

    def test_extract_structured_pdf_metrics_normalizes_financial_fields(self) -> None:
        text = (
            "主要会计数据 营业收入 3,620.1亿元，同比增长18.2%；"
            "归属于上市公司股东的净利润 441.0亿元，同比增长12.0%；"
            "毛利率 24.6%，同比增加1.2个百分点；"
            "经营活动产生的现金流量净额 928.0亿元；"
            "购建固定资产、无形资产和其他长期资产支付的现金 510.5亿元。"
        )

        metrics = extract_structured_pdf_metrics(text)
        metric_by_name = {item["metric_name"]: item for item in metrics}

        self.assertIn("revenue", metric_by_name)
        self.assertIn("net_income_attributable", metric_by_name)
        self.assertIn("gross_margin", metric_by_name)
        self.assertIn("operating_cash_flow", metric_by_name)
        self.assertIn("capex", metric_by_name)
        self.assertEqual(metric_by_name["revenue"]["value"], 3620.1)
        self.assertEqual(metric_by_name["revenue"]["unit"], "亿元")
        self.assertEqual(metric_by_name["gross_margin"]["value"], 24.6)
        self.assertEqual(metric_by_name["gross_margin"]["unit"], "%")
        self.assertFalse(metric_by_name["revenue"]["is_truncated"])

    def test_pdf_noise_filter_removes_repeated_headers_and_footers(self) -> None:
        pages = [
            "2025年度报告全文\n第1页\n营业收入 100亿元 同比增长10%",
            "2025年度报告全文\n第2页\n净利润 20亿元 同比增长5%",
            "2025年度报告全文\n第3页\n经营活动产生的现金流量净额 30亿元",
        ]

        noise = detect_repeated_headers_footers(pages)
        cleaned = remove_pdf_noise_lines(pages[0], noise)

        self.assertIn("2025年度报告全文", noise)
        self.assertNotIn("2025年度报告全文", cleaned)
        self.assertNotIn("第1页", cleaned)
        self.assertIn("营业收入 100亿元", cleaned)

    def test_truncated_metric_fragments_are_downgraded(self) -> None:
        metrics = extract_structured_pdf_metrics("营业收入 84 净利润 67 毛利率 2")

        self.assertTrue(metrics)
        self.assertTrue(all(item["is_truncated"] for item in metrics))
        self.assertTrue(all(item["can_enter_summary"] is False for item in metrics))
        self.assertTrue(all(item["weight"] <= 0.3 for item in metrics))

    def test_ocr_fallback_detects_scanned_financial_page(self) -> None:
        self.assertTrue(needs_ocr_fallback("", image_count=2, page_score=0.7))
        self.assertFalse(needs_ocr_fallback("营业收入 100亿元 净利润 20亿元", image_count=0, page_score=0.7))


if __name__ == "__main__":
    unittest.main()
