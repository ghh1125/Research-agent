from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_workflow_page_contains_editor_configuration_and_review_surfaces() -> None:
    html = (ROOT / "workflow_web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "workflow_web" / "app.js").read_text(encoding="utf-8")

    assert 'id="palette"' in html
    assert 'id="canvas"' in html
    assert 'id="config-panel"' in html
    assert 'id="checkpoint-panel"' in html
    assert 'id="report-panel"' in html
    assert 'draggable="true"' in script
    assert "/api/functions" in script
    assert "/api/examples/research-workflow" in script
    assert "/api/uploads" in script
    assert "/api/workflows/validate" in script
    assert "/api/runs" in script
    assert "/resume" in script
    assert "pointerdown" in script
    assert "setPointerCapture" in script
    assert "addNodeFromPaletteDrop" in script
    assert "addNodeAtVisiblePosition" in script
    assert "点击左侧节点新增" in html
    assert "display_name" in script
    assert "description" in script
    assert "llm_steps" in script
    assert "defaultPrompt" in script
    assert "defaultModel" in script
    assert "恢复默认 Prompt" in script
    assert "可用变量" in script
    assert "variableHelp" in script
    assert "运行时会自动替换为对应材料" in script
    assert "请在运行前完成所有节点配置" in html
    assert "节点、连线、文件、模型和 Prompt" in html
    assert "checkpointSignature" in script
    assert "setWorkflowLocked" in script
    assert "当前运行使用启动时的工作流快照" in html


def test_server_entry_point_and_readme_document_the_independent_demo() -> None:
    server = (ROOT / "workflow_server.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "create_server" in server
    assert "--port" in server
    assert "workflow_server.py" in readme
    assert "拖拽" in readme
    assert "深度尽调" in readme
    assert "qwen3.7-plus" in readme
    assert "deepseek-v4-pro" in readme
    assert "kimi-k2.7-code" in readme
    assert "python workflow_server.py --host 127.0.0.1 --port 8765" in readme
    assert "手工测试场景 A：默认完整流程" in readme
    assert "手工测试场景 B：仅团队尽调" in readme
    assert "手工测试场景 C：团队 + 财务部分尽调" in readme
    assert "手工测试场景 D：五个专项尽调分支" in readme
