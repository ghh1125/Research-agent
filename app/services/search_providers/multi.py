from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.search_providers.base import SearchProvider, SearchResult


class MultiSearchProvider(SearchProvider):
    """Run multiple configured web search providers and merge their results."""

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    def search(self, query: str) -> list[SearchResult]:
        if not self.providers:
            raise RuntimeError("No configured search providers. Configure TAVILY_API_KEY, SERPER_API_KEY, GOOGLE_SEARCH_API_KEY/GOOGLE_SEARCH_CX, or EXA_API_KEY.")

        results: list[SearchResult] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            future_map = {executor.submit(provider.search, query): provider for provider in self.providers}
            for future in as_completed(future_map):
                provider = future_map[future]
                try:
                    provider_results = future.result()
                except Exception as exc:
                    errors.append(f"{provider.__class__.__name__}: {exc}")
                    continue
                results.extend(provider_results)

        deduped = _dedupe_results(results)
        if not deduped and errors:
            raise RuntimeError("All configured search providers failed: " + " | ".join(errors[:4]))
        return deduped


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for item in results:
        url_key = (item.get("url") or "").strip().lower()
        title_key = item.get("title", "").strip().lower()
        key = url_key or f"{item.get('provider', 'unknown')}::{title_key}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
