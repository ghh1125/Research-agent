from __future__ import annotations

import pytest

from src.llm_config import (
    LLMCallConfig,
    PromptTemplateError,
    SUPPORTED_DASHSCOPE_MODELS,
    llm_context,
    render_prompt,
    validate_model,
)
from src.settings import get_settings


def test_default_dashscope_model_is_qwen_37_plus(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DASHSCOPE_MODEL", raising=False)

    assert get_settings().dashscope_model == "qwen3.7-plus"


def test_supported_models_are_limited_to_structured_output_choices() -> None:
    assert SUPPORTED_DASHSCOPE_MODELS == (
        "qwen3.7-plus",
        "qwen3.6-plus",
        "qwen3.6-flash",
        "qwen3.5-plus",
        "qwen3.5-flash",
        "qwen-plus",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "glm-5.2",
        "glm-5.1",
        "kimi-k2.7-code",
        "kimi-k2.6",
    )
    with pytest.raises(ValueError, match="不支持的模型"):
        validate_model("qwen3.7-max")


def test_prompt_template_uses_override_and_known_variables() -> None:
    rendered = render_prompt(
        "默认 {company_name}",
        {"company_name": "示例科技"},
        LLMCallConfig(model="qwen3.7-plus", prompt="自定义 {company_name}"),
    )

    assert rendered == "自定义 示例科技"


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("", "不能为空"),
        ("内容 {unknown}", "未知模板变量"),
        ("内容 {company_name", "格式错误"),
    ],
)
def test_prompt_template_rejects_invalid_content(template: str, message: str) -> None:
    with pytest.raises(PromptTemplateError, match=message):
        render_prompt(
            "默认 {company_name}",
            {"company_name": "示例科技"},
            LLMCallConfig(prompt=template),
        )


def test_literal_braces_can_be_escaped() -> None:
    assert render_prompt("JSON: {{\"name\": \"{company_name}\"}}", {"company_name": "Acme"}) == 'JSON: {"name": "Acme"}'


def test_selected_bailian_model_is_scoped_to_dashscope_provider() -> None:
    assert llm_context(LLMCallConfig(model="qwen3.7-plus")) == {
        "model": "qwen3.7-plus",
        "provider": "dashscope",
    }
