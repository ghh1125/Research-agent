from __future__ import annotations

from pathlib import Path

from src.report import render_meta_section, write_node_report
from src.schema import NodeMeta, Source


def test_render_meta_section_includes_all_fields() -> None:
    meta = NodeMeta(
        sources=[Source(title="示例来源", url="https://example.com", provider="tavily")],
        assumptions=["假设一"],
        confidence="medium",
        missing_info=["缺口一"],
        risk_flags=["风险一"],
    )
    text = render_meta_section(meta)
    assert "示例来源" in text
    assert "假设一" in text
    assert "缺口一" in text
    assert "风险一" in text
    assert "medium" in text


def test_write_node_report_creates_markdown_and_docx(tmp_path: Path) -> None:
    markdown = "# 标题\n\n## 小节\n- 要点一\n- 要点二\n"
    paths = write_node_report(markdown, tmp_path, "report")
    assert Path(paths["markdown"]).exists()
    assert Path(paths["markdown"]).read_text(encoding="utf-8") == markdown
    assert "docx" in paths
    assert Path(paths["docx"]).exists()
