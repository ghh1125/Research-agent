from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from research_flow.settings import RuntimeSettings, get_settings

T = TypeVar("T", bound=BaseModel)


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
    return "timeout" in name or "timed out" in message or "read operation timed out" in message


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
    text = str(exc)
    lowered = text.lower()
    if "allocationquota.freetieronly" in lowered or "free tier" in lowered:
        return (
            " Action: DashScope reported free tier only/quota exhaustion. "
            "Fix it: disable free tier only mode in the DashScope management console, "
            "or set DASHSCOPE_QUICK_MODEL/DASHSCOPE_DEEP_MODEL to another enabled model, "
            "or configure another API key/provider in LLM_FALLBACK_PROVIDERS."
        )
    if "permissiondenied" in lowered or "403" in lowered:
        return " Action: check whether this API key/account has access to the selected model, or switch model/provider."
    if _is_timeout_error(exc):
        return " Action: increase LLM_TIMEOUT_SECONDS/--llm-timeout or switch to a faster model."
    return ""


class RealLLMClient:
    """OpenAI-compatible provider chain used by every LLM step."""

    def __init__(self, settings: RuntimeSettings | None = None, progress_callback: Callable[[str], None] | None = None) -> None:
        self.settings = settings or get_settings()
        self.progress_callback = progress_callback

    def provider_candidates(self, role: str = "quick", explicit_model: str | None = None) -> list[ProviderConfig]:
        order = self._provider_order()
        candidates: list[ProviderConfig] = []
        for provider in order:
            candidates.extend(self._provider(provider, role=role, explicit_model=explicit_model))
        return candidates

    def complete_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        role: str = "quick",
        context: dict[str, Any] | None = None,
    ) -> T:
        explicit_model = self._explicit_model(role, context)
        candidates = self.provider_candidates(role=role, explicit_model=explicit_model)
        if not candidates:
            raise RuntimeError("No configured LLM provider. Set OPENAI_API_KEY, DASHSCOPE_API_KEY, OPENROUTER_API_KEY, or DEEPSEEK_API_KEY.")
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\n"
            "Return strict JSON only. It must validate against this JSON schema:\n"
            f"{schema_text}"
        )
        last_error: Exception | None = None
        for provider in candidates:
            label = f"llm[{role}] schema={schema.__name__} provider={provider.name} model={provider.model}"
            self._emit(f"    {label} start")
            try:
                from openai import OpenAI

                client = OpenAI(
                    api_key=provider.api_key,
                    base_url=provider.base_url,
                    timeout=self.settings.llm_timeout_seconds,
                    max_retries=0,
                )
                kwargs = {
                    "model": provider.model,
                    "messages": [
                        {"role": "system", "content": "你是严谨的买方投研系统组件。只输出合法 JSON，不输出解释。"},
                        {"role": "user", "content": full_prompt},
                    ],
                    "temperature": 0.1 if role == "quick" else 0.2,
                }
                try:
                    response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
                except Exception as exc:
                    if _is_timeout_error(exc) or _is_access_or_quota_error(exc):
                        raise
                    response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                result = schema.model_validate(_json_payload(content))
                self._emit(f"    {label} done")
                return result
            except Exception as exc:  # pragma: no cover - external API
                last_error = exc
                self._emit(f"    {label} error={type(exc).__name__}: {str(exc)[:240]}")
                continue
        detail = f"{type(last_error).__name__}: {last_error}" if last_error else "no provider attempted"
        raise RuntimeError(
            f"All configured LLM providers failed for {schema.__name__}/{role}; last_error={detail}.{_actionable_error(last_error)}"
        ) from last_error

    def _explicit_model(self, role: str, context: dict[str, Any] | None) -> str | None:
        if not context:
            return None
        explicit = context.get("model") or context.get("explicit_model")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        key = "deep_model" if role == "deep" else "quick_model"
        routed = context.get(key)
        return routed.strip() if isinstance(routed, str) and routed.strip() else None

    def _provider_order(self) -> list[str]:
        if self.settings.llm_provider and self.settings.llm_provider != "auto":
            order = [self.settings.llm_provider]
        else:
            order = ["dashscope", "openai", "openrouter", "deepseek"]
        for provider in self.settings.llm_fallback_providers:
            if provider not in order:
                order.append(provider)
        return order

    def _provider(self, provider: str, *, role: str, explicit_model: str | None = None) -> list[ProviderConfig]:
        s = self.settings
        if provider == "dashscope" and s.dashscope_api_key:
            model = explicit_model or (s.dashscope_deep_model if role == "deep" and s.dashscope_deep_model else s.dashscope_quick_model if role == "quick" and s.dashscope_quick_model else s.dashscope_model)
            return [ProviderConfig("dashscope", s.dashscope_api_key, s.dashscope_base_url, item) for item in _model_candidates(model)]
        if provider == "openai" and s.openai_api_key:
            model = explicit_model or (s.openai_deep_model if role == "deep" and s.openai_deep_model else s.openai_quick_model if role == "quick" and s.openai_quick_model else s.openai_model)
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
