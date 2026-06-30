from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.schema import CompetitorAnalysis, CompetitorCandidate, CompetitorDiscovery, CompetitorProfile, NodeMeta, SingleCompetitorAnalysis


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
    profile = CompetitorProfile(
        name="竞品甲",
        capability_summary="能力概述",
        business_model="订阅制",
        customer_and_scene="企业客户",
        tech_barrier="技术壁垒",
        funding_and_progress="A轮",
        strengths=["相对优势"],
        weaknesses=["相对劣势"],
    )
    return CompetitorAnalysis(
        overview="竞品报告内容",
        individual_results=[
            SingleCompetitorAnalysis(
                candidate_id="c1",
                profile=profile,
                matrix_values={"产品能力": "产品矩阵值"},
                meta=NodeMeta(confidence="high", missing_info=["待核实收入"]),
            )
        ],
        competitor_profiles=[profile],
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


def test_competitor_report_screen_supports_structured_review_before_due_diligence() -> None:
    app = _new_app()
    app.session_state["stage"] = "review_competitor_report"
    app.session_state["competitor_analysis"] = _competitor_report()

    app.run()

    assert any("竞品报告内容" in markdown.value for markdown in app.markdown)
    assert "竞品甲" in [expander.label for expander in app.expander]
    assert "审核意见 / 修改指令（必填）" in [area.label for area in app.text_area]
    labels = [button.label for button in app.button]
    assert "按反馈重新汇总" in labels
    assert "按反馈重新分析全部竞品" in labels
    assert "确认并进入深度尽调" in labels
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
