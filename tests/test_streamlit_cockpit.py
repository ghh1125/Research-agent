from __future__ import annotations

from pathlib import Path


def test_streamlit_cockpit_keeps_research_memo_collapsed() -> None:
    source = Path("/Users/ghh/Documents/Code/mcpify/research-agent/streamlit_app.py").read_text(encoding="utf-8")

    assert 'with st.expander("展开查看研究备忘录", expanded=False):' in source
    assert "memo_tabs = st.tabs" not in source
    assert 'with st.expander("开发者模式", expanded=False):' in source
