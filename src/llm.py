from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from src.settings import RuntimeSettings, get_settings

T = TypeVar("T", bound=BaseModel)
DASHSCOPE_JSON_FALLBACK_MODELS = ("qwen3.7-plus", "qwen3.6-plus")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    base_url: str | None
    model: str


def _json_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    return json.loads(raw)


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return "timeout" in name or "timed out" in message


def _is_access_or_quota_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        "permissiondenied" in name
        or "permission denied" in message
        or "403" in message
        or "allocationquota" in message
        or "free tier" in message
        or "quota" in message
    )


def _model_candidates(raw: str) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for item in raw.split(","):
        model = item.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _actionable_error(exc: Exception | None) -> str:
    if exc is None:
        return ""
    lowered = str(exc).lower()
    if "allocationquota.freetieronly" in lowered or "free tier" in lowered:
        return (
            " Action: provider reported free tier only/quota exhaustion. "
            "Disable free-tier-only mode in the provider console, switch the model, "
            "or configure LLM_FALLBACK_PROVIDERS."
        )
    if "permissiondenied" in lowered or "403" in lowered:
        return " Action: check whether this API key/account has access to the selected model."
    if _is_timeout_error(exc):
        return " Action: increase LLM_TIMEOUT_SECONDS or switch to a faster model."
    return ""


class RealLLMClient:
    """OpenAI-compatible provider chain used by every LLM-backed node."""

    def __init__(self, settings: RuntimeSettings | None = None, progress_callback: Callable[[str], None] | None = None) -> None:
        self.settings = settings or get_settings()
        self.progress_callback = progress_callback

    def provider_candidates(self, explicit_model: str | None = None) -> list[ProviderConfig]:
        order = self._provider_order()
        candidates: list[ProviderConfig] = []
        for provider in order:
            candidates.extend(self._provider(provider, explicit_model=explicit_model))
        return candidates

    def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        context: dict[str, Any] | None = None,
    ) -> T:
        explicit_model = self._explicit_model(context)
        explicit_provider = self._explicit_provider(context)
        candidates = (
            self._provider(explicit_provider, explicit_model=explicit_model)
            if explicit_provider
            else self.provider_candidates(explicit_model=explicit_model)
        )
        if not candidates:
            raise RuntimeError("No configured LLM provider. Set DASHSCOPE_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, or DEEPSEEK_API_KEY.")
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        full_prompt = f"{prompt}\n\nReturn strict JSON only. It must validate against this JSON schema:\n{schema_text}"
        last_error: Exception | None = None
        max_repair_attempts = 3
        for provider in candidates:
            label = f"llm schema={schema.__name__} provider={provider.name} model={provider.model}"
            messages: list[dict[str, str]] = [
                {"role": "system", "content": "你是严谨的一级市场投资尽调系统组件。只输出合法 JSON，不输出解释，不编造没有来源支撑的事实。"},
                {"role": "user", "content": full_prompt},
            ]
            for attempt in range(max_repair_attempts):
                attempt_label = f"{label} start" if attempt == 0 else f"{label} repair-retry attempt={attempt}"
                self._emit(f"    {attempt_label}")
                try:
                    content = self._request_content(provider, messages)
                except Exception as exc:  # pragma: no cover - external API
                    last_error = exc
                    self._emit(f"    {label} error={type(exc).__name__}: {str(exc)[:240]}")
                    break  # network/timeout/quota error: don't retry this provider, move to next one
                try:
                    result = schema.model_validate(_json_payload(content))
                    self._emit(f"    {label} done")
                    return result
                except (json.JSONDecodeError, ValidationError) as parse_exc:
                    last_error = parse_exc
                    self._emit(f"    {label} schema_error attempt={attempt}: {str(parse_exc)[:240]}")
                    if attempt < max_repair_attempts - 1:
                        if content.strip():
                            messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "上一次没有返回内容或返回的 JSON 未通过 schema 校验。"
                                    f"\n错误信息：\n{parse_exc}"
                                    "\n请重新生成完整结果，只输出合法 JSON，不要输出解释文字。"
                                ),
                            }
                        )
                        continue
        detail = f"{type(last_error).__name__}: {last_error}" if last_error else "no provider attempted"
        raise RuntimeError(f"All configured LLM providers failed for {schema.__name__}; last_error={detail}.{_actionable_error(last_error)}") from last_error

    def _request_content(self, provider: ProviderConfig, messages: list[dict[str, str]]) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=self.settings.llm_timeout_seconds, max_retries=0)
        kwargs = {"model": provider.model, "messages": messages}
        if provider.name != "dashscope" or provider.model.startswith(("qwen",)):
            kwargs["temperature"] = 0.2
        if provider.name == "dashscope" and provider.model.startswith(
            ("qwen3.5", "qwen3.6", "qwen3.7", "deepseek-v4", "glm-5.", "kimi-k2.6")
        ):
            kwargs["extra_body"] = {"enable_thinking": False}
        try:
            response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception as exc:
            if _is_timeout_error(exc) or _is_access_or_quota_error(exc):
                raise
            response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def _explicit_model(self, context: dict[str, Any] | None) -> str | None:
        if not context:
            return None
        explicit = context.get("model") or context.get("explicit_model")
        return explicit.strip() if isinstance(explicit, str) and explicit.strip() else None

    def _explicit_provider(self, context: dict[str, Any] | None) -> str | None:
        if not context:
            return None
        explicit = context.get("provider")
        if not isinstance(explicit, str) or not explicit.strip():
            return None
        provider = explicit.strip().lower()
        if provider not in {"dashscope", "openai", "openrouter", "deepseek"}:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        return provider

    def _provider_order(self) -> list[str]:
        if self.settings.llm_provider and self.settings.llm_provider != "auto":
            order = [self.settings.llm_provider]
        else:
            order = ["dashscope", "openai", "openrouter", "deepseek"]
        for provider in self.settings.llm_fallback_providers:
            if provider not in order:
                order.append(provider)
        return order

    def _provider(self, provider: str, *, explicit_model: str | None = None) -> list[ProviderConfig]:
        s = self.settings
        if provider == "dashscope" and s.dashscope_api_key:
            model = explicit_model or s.dashscope_model
            models = _model_candidates(model)
            for fallback_model in DASHSCOPE_JSON_FALLBACK_MODELS:
                if fallback_model not in models:
                    models.append(fallback_model)
            return [
                ProviderConfig("dashscope", s.dashscope_api_key, s.dashscope_base_url, item)
                for item in models
            ]
        if provider == "openai" and s.openai_api_key:
            model = explicit_model or s.openai_model
            return [ProviderConfig("openai", s.openai_api_key, s.openai_base_url, item) for item in _model_candidates(model)]
        if provider == "openrouter" and s.openrouter_api_key:
            model = explicit_model or s.openrouter_model
            return [ProviderConfig("openrouter", s.openrouter_api_key, s.openrouter_base_url, item) for item in _model_candidates(model)]
        if provider == "deepseek" and s.deepseek_api_key:
            model = explicit_model or s.deepseek_model
            return [ProviderConfig("deepseek", s.deepseek_api_key, s.deepseek_base_url, item) for item in _model_candidates(model)]
        return []

    def _emit(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
