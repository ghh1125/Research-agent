from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.models.source import Source

SKIP_DOMAINS = [
    "wind.com",
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
    "ft.com",
    "caixin.com",
    "twitter.com",
    "x.com",
    "weibo.com",
    "finance.yahoo.com",
    "example.com",
    "localhost",
]
NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "menu", "noscript", "iframe", "form"]
MAX_CONTENT_LENGTH = 4000


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def should_fetch(url: str | None, source_score: float) -> bool:
    """Return whether a non-PDF high-quality source is worth full-page fetching."""

    if not url:
        return False
    lowered = url.lower()
    if source_score < 0.5:
        return False
    if lowered.endswith(".pdf") or ".pdf?" in lowered:
        return False
    if lowered.endswith(".json") or "/api/" in lowered:
        return False
    domain = _domain(url)
    return not any(skip_domain in domain for skip_domain in SKIP_DOMAINS)


def fetch_full_content(url: str, timeout: int = 12) -> str | None:
    """Fetch and clean full-page text. Fail closed and let caller keep snippet."""

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        with httpx.Client(trust_env=False, follow_redirects=True) as client:
            response = client.get(url, timeout=timeout, headers=headers)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(NOISE_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        lines = [line for line in lines if len(line) >= 8]
        cleaned = "\n".join(lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if len(cleaned) < 100:
            return None
        return cleaned[:MAX_CONTENT_LENGTH]
    except Exception:
        return None


def enrich_source_content(url: str | None, original_content: str, source_score: float) -> str | None:
    """Fetch full content when available; keep original content immutable."""

    if not should_fetch(url, source_score):
        return None
    full_text = fetch_full_content(url or "")
    if full_text and len(full_text) > len(original_content) * 1.5:
        return full_text
    return None


def enrich_sources_content(sources: list[Source], max_workers: int = 5) -> list[Source]:
    """Concurrently enrich high-score non-PDF sources without blocking failures."""

    if not sources:
        return []

    enriched_by_index: dict[int, Source] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                enrich_source_content,
                source.url,
                source.content,
                source.source_score or 0.0,
            ): (index, source)
            for index, source in enumerate(sources)
            if should_fetch(source.url, source.source_score or 0.0) and not source.is_pdf
        }
        for future in as_completed(future_map):
            index, source = future_map[future]
            try:
                new_content = future.result()
            except Exception:
                new_content = None
            if new_content:
                enriched_by_index[index] = source.model_copy(
                    update={"fetched_content": new_content, "enriched_content": new_content}
                )

    return [enriched_by_index.get(index, source) for index, source in enumerate(sources)]
