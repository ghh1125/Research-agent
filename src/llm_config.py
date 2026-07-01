from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any, Collection

SUPPORTED_DASHSCOPE_MODELS = (
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
DEFAULT_DASHSCOPE_MODEL = "qwen3.7-plus"


class PromptTemplateError(ValueError):
    pass


def validate_model(model: str | None) -> str | None:
    if model is None or not model.strip():
        return None
    normalized = model.strip()
    if normalized not in SUPPORTED_DASHSCOPE_MODELS:
        raise ValueError(f"不支持的模型: {normalized}")
    return normalized


@dataclass(frozen=True)
class LLMCallConfig:
    model: str | None = None
    prompt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", validate_model(self.model))


def prompt_variables(template: str) -> tuple[str, ...]:
    try:
        fields = [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]
    except ValueError as exc:
        raise PromptTemplateError(f"Prompt 模板格式错误: {exc}") from exc
    return tuple(dict.fromkeys(fields))


def validate_prompt_template(template: str, allowed_variables: Collection[str]) -> None:
    if not template.strip():
        raise PromptTemplateError("Prompt 不能为空")
    allowed = set(allowed_variables)
    unknown = [field for field in prompt_variables(template) if field not in allowed]
    if unknown:
        raise PromptTemplateError(f"Prompt 包含未知模板变量: {', '.join(unknown)}")


def render_prompt(
    default_prompt: str,
    values: dict[str, Any],
    config: LLMCallConfig | None = None,
) -> str:
    template = config.prompt if config is not None and config.prompt is not None else default_prompt
    validate_prompt_template(template, values.keys())
    try:
        return template.format(**values)
    except (KeyError, ValueError) as exc:
        raise PromptTemplateError(f"Prompt 模板格式错误: {exc}") from exc


def llm_context(config: LLMCallConfig | None) -> dict[str, str] | None:
    return (
        {"model": config.model, "provider": "dashscope"}
        if config is not None and config.model
        else None
    )


__all__ = [
    "DEFAULT_DASHSCOPE_MODEL",
    "LLMCallConfig",
    "PromptTemplateError",
    "SUPPORTED_DASHSCOPE_MODELS",
    "llm_context",
    "prompt_variables",
    "render_prompt",
    "validate_model",
    "validate_prompt_template",
]
