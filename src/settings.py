from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class RuntimeSettings:
    llm_provider: str
    llm_fallback_providers: tuple[str, ...]
    llm_timeout_seconds: float
    openai_api_key: str
    openai_base_url: str | None
    openai_model: str
    dashscope_api_key: str
    dashscope_base_url: str
    dashscope_model: str
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    tavily_api_key: str
    tavily_base_url: str
    serper_api_key: str
    serper_base_url: str
    google_search_api_key: str
    google_search_cx: str
    google_search_base_url: str


def get_settings() -> RuntimeSettings:
    load_env()
    fallback = tuple(item.strip().lower() for item in _first("LLM_FALLBACK_PROVIDERS").split(",") if item.strip())
    return RuntimeSettings(
        llm_provider=_first("LLM_PROVIDER", default="auto").lower(),
        llm_fallback_providers=fallback,
        llm_timeout_seconds=float(_first("LLM_TIMEOUT_SECONDS", default="240")),
        openai_api_key=_first("OPENAI_API_KEY"),
        openai_base_url=_first("OPENAI_BASE_URL") or None,
        openai_model=_first("OPENAI_MODEL", default="gpt-4.1"),
        dashscope_api_key=_first("DASHSCOPE_API_KEY"),
        dashscope_base_url=_first("DASHSCOPE_BASE_URL", default="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        dashscope_model=_first("DASHSCOPE_MODEL", default="qwen3.7-max-2026-06-08"),
        openrouter_api_key=_first("OPENROUTER_API_KEY"),
        openrouter_base_url=_first("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1"),
        openrouter_model=_first("OPENROUTER_MODEL", default="openai/gpt-4.1"),
        deepseek_api_key=_first("DEEPSEEK_API_KEY"),
        deepseek_base_url=_first("DEEPSEEK_BASE_URL", default="https://api.deepseek.com"),
        deepseek_model=_first("DEEPSEEK_MODEL", default="deepseek-chat"),
        tavily_api_key=_first("TAVILY_API_KEY"),
        tavily_base_url=_first("TAVILY_BASE_URL", default="https://api.tavily.com/search"),
        serper_api_key=_first("SERPER_API_KEY"),
        serper_base_url=_first("SERPER_BASE_URL", default="https://google.serper.dev/search"),
        google_search_api_key=_first("GOOGLE_SEARCH_API_KEY"),
        google_search_cx=_first("GOOGLE_SEARCH_CX"),
        google_search_base_url=_first("GOOGLE_SEARCH_BASE_URL", default="https://www.googleapis.com/customsearch/v1"),
    )
