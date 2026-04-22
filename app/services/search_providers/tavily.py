from __future__ import annotations

import re
from html import unescape

from app.config import Settings
from app.services.search_providers.base import SearchProvider, SearchResult

_NOISE_PHRASES = [
    "热门搜索",
    "搜索历史",
    "收藏",
    "评论",
    "点赞",
    "微信",
    "微博",
    "空间",
    "扫码",
    "二维码",
    "登录",
    "注册",
    "免责声明",
]


def _clean_search_content(content: str) -> str:
    """Convert Tavily raw content into readable text before retrieval stores it."""

    cleaned = unescape(content)
    cleaned = re.sub(r"<(script|style|nav|footer|header).*?</\1>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"#{1,6}\s*", " ", cleaned)
    cleaned = re.sub(r"[*_`]+", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.startswith("热门搜索") or cleaned.startswith("搜索历史"):
        cleaned = re.sub(r"^.*?作者[:：]\S+\s+", "", cleaned)

    parts = re.split(r"(?<=[。！？!?；;])\s+|\n+", cleaned)
    meaningful_parts = []
    for part in parts:
        part = part.strip(" ，,")
        if not part:
            continue
        if any(phrase in part for phrase in _NOISE_PHRASES) and len(part) < 80:
            continue
        meaningful_parts.append(part)
    return " ".join(meaningful_parts).strip()


class TavilySearchProvider(SearchProvider):
    """Real-provider skeleton backed by the Tavily search API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.tavily_api_key
        self.base_url = settings.tavily_base_url

    def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured")

        try:
            import httpx

            response = httpx.post(
                self.base_url,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": self.settings.tavily_max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                    "include_raw_content": True,
                    "include_images": False,
                    "days": self.settings.tavily_days,
                },
                timeout=self.settings.search_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network/provider dependency
            raise RuntimeError(f"Tavily search request failed: {type(exc).__name__}: {exc}") from exc

        payload = response.json()
        results: list[SearchResult] = []
        for item in payload.get("results", []):
            content = _clean_search_content(
                item.get("raw_content") or item.get("content") or item.get("snippet") or ""
            )[:4000]
            if not content.strip():
                continue
            url = item.get("url", "")
            title = item.get("title", "Untitled Result")
            lowered = f"{url} {title}".lower()
            source_type = "report" if ".pdf" in lowered or "[pdf]" in lowered or "annual report" in lowered else "website"
            results.append(
                {
                    "url": url,
                    "title": title,
                    "source_type": source_type,
                    "provider": "tavily",
                    "published_at": item.get("published_date") or item.get("published_at") or item.get("date"),
                    "content": content.strip(),
                }
            )
        return results
