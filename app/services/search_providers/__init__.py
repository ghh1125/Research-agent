"""Search provider implementations for the research agent."""

from app.services.search_providers.base import SearchProvider, SearchResult
from app.services.search_providers.multi import MultiSearchProvider
from app.services.search_providers.supplemental import (
    AkshareSupplementalProvider,
    CompanyIRSupplementalProvider,
    ProviderSearchResult,
    SecEdgarSupplementalProvider,
    YFinanceSupplementalProvider,
    search_supplemental_sources,
)
from app.services.search_providers.tavily import TavilySearchProvider
from app.services.search_providers.web import ExaSearchProvider, GoogleCustomSearchProvider, SerperSearchProvider

__all__ = [
    "AkshareSupplementalProvider",
    "CompanyIRSupplementalProvider",
    "ExaSearchProvider",
    "GoogleCustomSearchProvider",
    "MultiSearchProvider",
    "ProviderSearchResult",
    "SecEdgarSupplementalProvider",
    "SearchProvider",
    "SearchResult",
    "SerperSearchProvider",
    "TavilySearchProvider",
    "YFinanceSupplementalProvider",
    "search_supplemental_sources",
]
