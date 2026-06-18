from __future__ import annotations

from src.files import ParsedFile
from src.nodes.due_diligence.financial import compute_financial_ratios


def test_compute_ratios_from_sheets() -> None:
    parsed = [
        ParsedFile(
            path="financials.xlsx",
            kind="xlsx",
            text="",
            sheets={
                "利润表": [
                    ["项目", "2024", "2025"],
                    ["营业收入", "1000", "1500"],
                    ["营业成本", "600", "800"],
                    ["净利润", "100", "300"],
                ]
            },
        )
    ]
    ratios = compute_financial_ratios(parsed)
    assert ratios.revenue == {"period_1": 1000.0, "period_2": 1500.0}
    assert ratios.cost == {"period_1": 600.0, "period_2": 800.0}
    assert ratios.gross_margin_pct == round((1500 - 800) / 1500 * 100, 2)
    assert ratios.net_margin_pct == round(300 / 1500 * 100, 2)
    assert ratios.revenue_yoy_growth_pct == round((1500 - 1000) / 1000 * 100, 2)


def test_compute_ratios_no_data_returns_none_fields() -> None:
    parsed = [ParsedFile(path="bp.pdf", kind="pdf", text="这是一份没有财务数字的商业计划书")]
    ratios = compute_financial_ratios(parsed)
    assert ratios.revenue == {}
    assert ratios.gross_margin_pct is None
    assert ratios.computed_from == "未提取到结构化财务数据"


def test_compute_ratios_from_text_fallback() -> None:
    parsed = [ParsedFile(path="bp.pdf", kind="pdf", text="2025年营业收入 2000 万元，营业成本 1200 万元。")]
    ratios = compute_financial_ratios(parsed)
    assert ratios.revenue == {"period_1": 2000.0}
    assert ratios.cost == {"period_1": 1200.0}
    assert ratios.gross_margin_pct == round((2000 - 1200) / 2000 * 100, 2)
