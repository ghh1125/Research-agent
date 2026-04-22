from __future__ import annotations

import re
from html import unescape
from typing import Any

from app.config import Settings
from app.services.search_providers.base import SearchProvider, SearchResult


def _clean_text(value: str | None, limit: int = 4000) -> str:
    text = unescape(value or "")
    text = re.sub(r"<(script|style|nav|footer|header).*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _source_type_from_url(url: str, title: str) -> str:
    lowered = f"{url} {title}".lower()
    if ".pdf" in lowered or "annual report" in lowered or "10-k" in lowered or "20-f" in lowered:
        return "report"
    if "sec.gov" in lowered or "hkexnews.hk" in lowered or "cninfo.com.cn" in lowered:
        return "regulatory"
    if "investor" in lowered or "/ir" in lowered:
        return "company"
    return "website"


def _first_meta_date(item: dict[str, Any]) -> str | None:
    pagemap = item.get("pagemap") or {}
    for meta in pagemap.get("metatags", []) or []:
        for key in ["article:published_time", "date", "dc.date", "pubdate", "og:updated_time"]:
            if meta.get(key):
                return str(meta[key])
    return item.get("date") or item.get("publishedDate") or item.get("published_at")


class SerperSearchProvider(SearchProvider):
    """Google SERP search provider backed by Serper."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.serper_api_key
        self.base_url = settings.serper_base_url

    def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is not configured")
        try:
            import httpx

            response = httpx.post(
                self.base_url,
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": query, "num": self.settings.serper_max_results},
                timeout=self.settings.search_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network/provider dependency
            raise RuntimeError(f"Serper search request failed: {type(exc).__name__}: {exc}") from exc

        payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("organic", []) or []:
            url = item.get("link") or item.get("url") or ""
            title = item.get("title") or "Untitled Result"
            content = _clean_text(item.get("snippet") or item.get("description") or "")
            if not url or not content:
                continue
            results.append(
                {
                    "url": url,
                    "title": title,
                    "source_type": _source_type_from_url(url, title),  # type: ignore[typeddict-item]
                    "provider": "serper",
                    "published_at": item.get("date"),
                    "content": content,
                }
            )
        return results


class GoogleCustomSearchProvider(SearchProvider):
    """Google Programmable Search provider."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.google_search_api_key
        self.cx = settings.google_search_cx
        self.base_url = settings.google_search_base_url

    def search(self, query: str) -> list[SearchResult]:
        if not self.api_key or not self.cx:
            raise RuntimeError("GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX are not configured")
        try:
            import httpx

            response = httpx.get(
                self.base_url,
                params={
                    "key": self.api_key,
                    "cx": self.cx,
                    "q": query,
                    "num": min(max(self.settings.google_search_max_results, 1), 10),
                },
                timeout=self.settings.search_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network/provider dependency
            raise RuntimeError(f"Google Custom Search request failed: {type(exc).__name__}: {exc}") from exc

        payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("items", []) or []:
            url = item.get("link") or ""
            title = item.get("title") or "Untitled Result"
            content = _clean_text(item.get("snippet") or "")
            if not url or not content:
                continue
            results.append(
                {
                    "url": url,
                    "title": title,
                    "source_type": _source_type_from_url(url, title),  # type: ignore[typeddict-item]
                    "provider": "google_custom_search",
                    "published_at": _first_meta_date(item),
                    "content": content,
                }
            )
        return results


class ExaSearchProvider(SearchProvider):
    """Research-oriented web search provider backed by Exa."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.exa_api_key
        self.base_url = settings.exa_base_url

    def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            raise RuntimeError("EXA_API_KEY is not configured")
        try:
            import httpx

            response = httpx.post(
                self.base_url,
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                json={
                    "query": query,
                    "numResults": self.settings.exa_max_results,
                    "contents": {"text": True},
                },
                timeout=self.settings.search_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network/provider dependency
            raise RuntimeError(f"Exa search request failed: {type(exc).__name__}: {exc}") from exc

        payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("results", []) or []:
            url = item.get("url") or ""
            title = item.get("title") or "Untitled Result"
            content = _clean_text(item.get("text") or item.get("snippet") or item.get("summary") or "")
            if not url or not content:
                continue
            results.append(
                {
                    "url": url,
                    "title": title,
                    "source_type": _source_type_from_url(url, title),  # type: ignore[typeddict-item]
                    "provider": "exa",
                    "published_at": item.get("publishedDate") or item.get("published_at"),
                    "content": content,
                }
            )
        return results
