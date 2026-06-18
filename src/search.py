from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any

from src.schema import Source
from src.settings import RuntimeSettings, get_settings


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:  # noqa: S310 - user-configured research URL
        return json.loads(response.read().decode("utf-8"))


class RealSearchClient:
    """Real web search provider chain: Tavily -> Serper -> Google CSE."""

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def search(self, query: str, *, category: str = "general", max_results: int = 5) -> list[dict[str, Any]]:
        errors: list[str] = []
        if self.settings.tavily_api_key:
            try:
                return self._tavily(query, max_results=max_results)
            except Exception as exc:  # pragma: no cover - external API
                errors.append(f"tavily: {exc}")
        if self.settings.serper_api_key:
            try:
                return self._serper(query, max_results=max_results)
            except Exception as exc:  # pragma: no cover - external API
                errors.append(f"serper: {exc}")
        if self.settings.google_search_api_key and self.settings.google_search_cx:
            try:
                return self._google(query, max_results=max_results)
            except Exception as exc:  # pragma: no cover - external API
                errors.append(f"google: {exc}")
        detail = "; ".join(errors) if errors else "no search API key configured"
        raise RuntimeError(f"Search failed for {category}: {detail}")

    def _tavily(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        payload = {"query": query, "max_results": max_results, "include_raw_content": False}
        data = _request_json(self.settings.tavily_base_url, method="POST", headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"}, payload=payload)
        return [
            {"title": item.get("title") or item.get("url") or "Untitled", "url": item.get("url"), "content": item.get("content") or "", "provider": "tavily"}
            for item in data.get("results", [])
        ]

    def _serper(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        data = _request_json(self.settings.serper_base_url, method="POST", headers={"X-API-KEY": self.settings.serper_api_key}, payload={"q": query, "num": max_results})
        rows = data.get("organic", [])[:max_results]
        return [
            {"title": item.get("title") or item.get("link") or "Untitled", "url": item.get("link"), "content": item.get("snippet") or "", "provider": "serper"}
            for item in rows
        ]

    def _google(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"key": self.settings.google_search_api_key, "cx": self.settings.google_search_cx, "q": query, "num": min(max_results, 10)})
        data = _request_json(f"{self.settings.google_search_base_url}?{params}")
        return [
            {"title": item.get("title") or item.get("link") or "Untitled", "url": item.get("link"), "content": item.get("snippet") or "", "provider": "google_cse"}
            for item in data.get("items", [])
        ]


def collect_evidence(
    client: RealSearchClient,
    queries: list[str],
    *,
    category: str = "general",
    max_results: int = 5,
) -> tuple[str, list[Source]]:
    """Run several search queries and return (joined context text, Source list) for an LLM prompt."""

    blocks: list[str] = []
    sources: list[Source] = []
    for query in queries:
        try:
            results = client.search(query, category=category, max_results=max_results)
        except Exception as exc:  # pragma: no cover - external API
            blocks.append(f"[query={query}] search_error={exc}")
            continue
        for item in results:
            blocks.append(f"[query={query}] {item['title']}\n{item['content']}\nsource_url={item.get('url')}")
            sources.append(Source(title=item["title"], url=item.get("url"), provider=item.get("provider")))
    return "\n\n".join(blocks), sources
