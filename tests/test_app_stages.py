from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.schema import CompetitorAnalysis, CompetitorCandidate, CompetitorDiscovery


APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _new_app() -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=10)
    app.run()
    return app


def _discovery() -> CompetitorDiscovery:
    return CompetitorDiscovery(
        candidates=[
            CompetitorCandidate(
                id="c1",
                name="竞品甲",
                product_or_service="企业知识助手",
                relationship="直接竞品",
                reason="产品和客户群体重合",
            )
        ]
    )


def _competitor_report() -> CompetitorAnalysis:
    return CompetitorAnalysis(
        overview="竞品报告内容",
        positioning_judgment="目标公司在垂直场景具备差异化",
        markdown="# 竞品矩阵分析\n\n竞品报告内容",
    )


def test_competitor_selection_screen_has_no_due_diligence_uploads() -> None:
    app = _new_app()
    app.session_state["stage"] = "select_competitors"
    app.session_state["discovery"] = _discovery()

    app.run()

    assert [u.label for u in app.file_uploader] == []
    assert "生成竞品矩阵分析报告" in [b.label for b in app.button]


def test_competitor_report_screen_is_read_only_before_due_diligence() -> None:
    app = _new_app()
    app.session_state["stage"] = "show_competitor_report"
    app.session_state["competitor_analysis"] = _competitor_report()

    app.run()

    assert any("竞品报告内容" in markdown.value for markdown in app.markdown)
    assert "进入深度尽调" in [b.label for b in app.button]
    assert [u.label for u in app.file_uploader] == []


def test_due_diligence_uploads_appear_only_in_upload_stage() -> None:
    app = _new_app()
    app.session_state["stage"] = "upload_due_diligence"
    app.session_state["competitor_analysis"] = _competitor_report()

    app.run()

    assert [u.label for u in app.file_uploader] == [
        "创始团队资料",
        "财务报表（建议 xlsx，便于程序自动算财务比率）",
        "商业计划书 / 业务规划书",
        "技术与知识产权资料",
        "法律文件摘要",
    ]
