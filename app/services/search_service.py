from __future__ import annotations

import re
from html import unescape

from app.config import Settings, get_settings
from app.services.search_providers import (
    ExaSearchProvider,
    GoogleCustomSearchProvider,
    MultiSearchProvider,
    SearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
)


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Return the configured search provider."""

    active_settings = settings or get_settings()
    provider_name = active_settings.search_provider.strip().lower()

    if provider_name in {"tavily", "real"}:
        return TavilySearchProvider(active_settings)
    if provider_name in {"serper", "google_serper"}:
        return SerperSearchProvider(active_settings)
    if provider_name in {"google", "google_custom_search"}:
        return GoogleCustomSearchProvider(active_settings)
    if provider_name == "exa":
        return ExaSearchProvider(active_settings)
    if provider_name in {"", "auto", "multi"}:
        return MultiSearchProvider(_configured_web_search_providers(active_settings))

    raise ValueError(f"Unsupported search provider: {active_settings.search_provider}")


def _configured_web_search_providers(settings: Settings) -> list[SearchProvider]:
    providers: list[SearchProvider] = []
    if settings.tavily_api_key:
        providers.append(TavilySearchProvider(settings))
    if settings.serper_api_key:
        providers.append(SerperSearchProvider(settings))
    if settings.google_search_api_key and settings.google_search_cx:
        providers.append(GoogleCustomSearchProvider(settings))
    if settings.exa_api_key:
        providers.append(ExaSearchProvider(settings))
    return providers


def get_search_provider_status(settings: Settings | None = None) -> list[dict]:
    """Return UI-safe search provider configuration status without exposing secrets."""

    active_settings = settings or get_settings()
    return [
        {
            "provider": "Tavily",
            "enabled": bool(active_settings.tavily_api_key),
            "required_env": "TAVILY_API_KEY",
            "max_results": active_settings.tavily_max_results,
            "purpose": "通用网页搜索",
            "note": "已配置" if active_settings.tavily_api_key else "未配置 key",
        },
        {
            "provider": "Serper",
            "enabled": bool(active_settings.serper_api_key),
            "required_env": "SERPER_API_KEY",
            "max_results": active_settings.serper_max_results,
            "purpose": "Google SERP 召回",
            "note": "已配置" if active_settings.serper_api_key else "未配置 key",
        },
        {
            "provider": "Google Custom Search",
            "enabled": bool(active_settings.google_search_api_key and active_settings.google_search_cx),
            "required_env": "GOOGLE_SEARCH_API_KEY + GOOGLE_SEARCH_CX",
            "max_results": active_settings.google_search_max_results,
            "purpose": "Google Programmable Search",
            "note": (
                "已配置"
                if active_settings.google_search_api_key and active_settings.google_search_cx
                else "需要同时配置 API key 和 CX"
            ),
        },
        {
            "provider": "Exa",
            "enabled": bool(active_settings.exa_api_key),
            "required_env": "EXA_API_KEY",
            "max_results": active_settings.exa_max_results,
            "purpose": "研究类语义搜索",
            "note": "已配置" if active_settings.exa_api_key else "未配置 key",
        },
    ]


def _normalize_search_results(results: list[dict]) -> list[dict]:
    source_type_map = {
        "policy": "regulatory",
        "company_filing": "company",
    }

    normalized: list[dict] = []
    for item in results:
        content = unescape(item.get("content", ""))
        content = re.sub(r"<(script|style|nav|footer|header).*?</\1>", " ", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        if not _is_meaningful_text(content):
            continue

        raw_source_type = item.get("source_type", "website")
        source_type = source_type_map.get(raw_source_type, raw_source_type)
        if source_type not in {"news", "report", "regulatory", "company", "website", "other"}:
            source_type = "other"

        normalized_item = {
            "url": (item.get("url") or "").strip(),
            "title": item.get("title", "Untitled Result").strip() or "Untitled Result",
            "source_type": source_type,
            "provider": (item.get("provider") or "unknown").strip() or "unknown",
            "published_at": item.get("published_at"),
            "content": content,
        }
        if item.get("source_origin_type"):
            normalized_item["source_origin_type"] = item["source_origin_type"]
        normalized.append(normalized_item)
    return normalized


def _is_meaningful_text(text: str) -> bool:
    lowered = text.lower()
    if len(text) < 30:
        return False
    noise_tokens = [
        "javascript",
        "cookie",
        "privacy policy",
        "login",
        "sign up",
        "subscribe",
        "404",
        "403",
        "版权所有",
        "登录",
        "注册",
        "导航",
        "菜单",
        "首页",
        "免责声明",
    ]
    if any(token in lowered or token in text for token in noise_tokens):
        return False
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    alpha_chars = len(re.findall(r"[A-Za-z]", text))
    return chinese_chars + alpha_chars >= 20


def search(query: str) -> list[dict]:
    """Search with the configured provider and return normalized results."""

    provider = get_search_provider()
    return _normalize_search_results(provider.search(query))
