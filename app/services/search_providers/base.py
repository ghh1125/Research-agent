from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, TypedDict

from typing_extensions import NotRequired


class SearchResult(TypedDict):
    """Normalized search result contract shared across providers."""

    url: str
    title: str
    source_type: Literal["news", "report", "regulatory", "company", "website", "other"]
    provider: str
    published_at: str | None
    content: str
    source_origin_type: NotRequired[
        Literal[
            "official_disclosure",
            "company_ir",
            "regulatory",
            "professional_media",
            "research_media",
            "aggregator",
            "community",
            "self_media",
            "unknown",
        ]
    ]


class SearchProvider(ABC):
    """Abstract interface implemented by all search providers."""

    @abstractmethod
    def search(self, query: str) -> list[SearchResult]:
        """Return normalized search results for the given query."""
