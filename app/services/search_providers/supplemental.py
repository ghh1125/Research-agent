from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Protocol

from app.config import Settings, get_settings
from app.models.topic import Topic
from app.services.search_providers.base import SearchResult

_ENTITY_SYMBOL_MAP = {
    "拼多多": "PDD",
    "PDD": "PDD",
    "PDD Holdings": "PDD",
    "阿里巴巴": "BABA",
    "京东": "JD",
    "百度": "BIDU",
    "网易": "NTES",
    "腾讯": "0700.HK",
    "美团": "3690.HK",
    "宁德时代": "300750.SZ",
    "比亚迪": "1211.HK",
    "特斯拉": "TSLA",
    "英伟达": "NVDA",
    "微软": "MSFT",
    "苹果": "AAPL",
    "AMD": "AMD",
    "博通": "AVGO",
    "摩根大通": "JPM",
    "美国银行": "BAC",
}

_SEC_CIK_MAP = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "AMD": "0000002488",
    "AVGO": "0001730168",
    "JPM": "0000019617",
    "BAC": "0000070858",
    "PDD": "0001737806",
    "BABA": "0001577552",
    "JD": "0001549802",
    "BIDU": "0001329099",
    "NTES": "0001110646",
}


@dataclass(frozen=True)
class ProviderSearchResult:
    provider: str
    status: str
    items: list[SearchResult] = field(default_factory=list)
    error: str | None = None


class SupplementalProvider(Protocol):
    name: str

    def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
        """Return provider-specific supplemental results without raising provider failures."""


def _resolve_symbol(topic: Topic | None) -> str | None:
    if topic is None:
        return None
    entity = topic.entity or topic.topic
    symbol = _ENTITY_SYMBOL_MAP.get(entity)
    if symbol:
        return symbol
    if entity and entity.upper() in _SEC_CIK_MAP:
        return entity.upper()
    return None


def _market(topic: Topic | None, symbol: str | None) -> str:
    if topic is not None and getattr(topic, "market_type", "other") != "other":
        return topic.market_type
    if symbol and symbol.endswith((".SZ", ".SH")):
        return "A_share"
    if symbol and symbol.endswith(".HK"):
        return "HK"
    if symbol:
        return "US"
    return "other"


def _compact_metadata(row: dict, keys: list[str]) -> str:
    parts = []
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip() in {"", "nan", "None"}:
            continue
        parts.append(f"{key}={value}")
    return "；".join(parts)


class AkshareSupplementalProvider:
    name = "akshare"

    def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
        symbol = _resolve_symbol(topic)
        market = _market(topic, symbol)
        entity = (topic.entity or topic.topic) if topic else None
        if market != "A_share" or not symbol or not entity:
            return ProviderSearchResult(provider=self.name, status="empty")
        try:
            import akshare as ak
        except Exception as exc:
            return ProviderSearchResult(provider=self.name, status="skipped", error=f"akshare unavailable: {type(exc).__name__}")

        code = symbol.replace(".SZ", "").replace(".SH", "")
        try:
            spot = ak.stock_zh_a_spot_em()
            matches = spot[spot["代码"].astype(str) == code]
        except Exception as exc:
            return ProviderSearchResult(provider=self.name, status="error", error=str(exc))
        if matches.empty:
            return ProviderSearchResult(provider=self.name, status="empty")

        row = matches.iloc[0].to_dict()
        fields = _compact_metadata(row, ["代码", "名称", "最新价", "涨跌幅", "总市值", "市盈率-动态", "市净率", "换手率"])
        content = (
            f"{entity} A股结构化行情快照：{fields}。"
            "该数据来自 AkShare 聚合的公开市场数据，用于补充 Tavily 检索结果，不能替代官方公告或审计财报。"
        )
        return ProviderSearchResult(
            provider=self.name,
            status="success",
            items=[
                {
                    "url": "",
                    "title": f"{entity} A股行情快照",
                    "source_type": "other",
                    "provider": self.name,
                    "published_at": None,
                    "content": content,
                    "source_origin_type": "professional_media",
                }
            ],
        )


class YFinanceSupplementalProvider:
    name = "yfinance"

    def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
        symbol = _resolve_symbol(topic)
        market = _market(topic, symbol)
        entity = (topic.entity or topic.topic) if topic else None
        if market not in {"US", "HK"} or not symbol:
            return ProviderSearchResult(provider=self.name, status="empty")
        try:
            import yfinance as yf
        except Exception as exc:
            return ProviderSearchResult(provider=self.name, status="skipped", error=f"yfinance unavailable: {type(exc).__name__}")
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as exc:
            return ProviderSearchResult(provider=self.name, status="error", error=str(exc))
        fields = _compact_metadata(
            info,
            ["marketCap", "trailingPE", "forwardPE", "priceToBook", "profitMargins", "revenueGrowth", "debtToEquity"],
        )
        if not fields:
            return ProviderSearchResult(provider=self.name, status="empty")
        content = (
            f"{entity or symbol} 轻量市场数据快照：symbol={symbol}；{fields}。"
            "该数据来自 yfinance/Yahoo Finance 公开接口，用于补充估值和市场指标，不替代官方披露。"
        )
        return ProviderSearchResult(
            provider=self.name,
            status="success",
            items=[
                {
                    "url": f"https://finance.yahoo.com/quote/{symbol}",
                    "title": f"{symbol} market snapshot",
                    "source_type": "other",
                    "provider": self.name,
                    "published_at": None,
                    "content": content,
                    "source_origin_type": "professional_media",
                }
            ],
        )


class SecEdgarSupplementalProvider:
    name = "sec_edgar"

    def __init__(self, settings: Settings | None = None) -> None:
        active_settings = settings or get_settings()
        self.user_agent_email = active_settings.sec_user_agent_email
        self.timeout = active_settings.search_timeout_seconds

    def search(self, query: str, topic: Topic | None = None) -> ProviderSearchResult:
        symbol = _resolve_symbol(topic)
        cik = _SEC_CIK_MAP.get(symbol or "")
        if not cik:
            return ProviderSearchResult(provider=self.name, status="empty")
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            import httpx

            response = httpx.get(
                url,
                headers={
                    "User-Agent": f"research-agent {self.user_agent_email}",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return ProviderSearchResult(provider=self.name, status="error", error=str(exc))

        name = data.get("name") or symbol or cik
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])[:8]
        filing_dates = recent.get("filingDate", [])[:8]
        form_summary = "；".join(
            f"{form}@{filing_dates[index] if index < len(filing_dates) else 'unknown'}"
            for index, form in enumerate(forms)
        )
        content = (
            f"{name} SEC EDGAR submissions 官方披露入口：CIK={cik}；recent_filings={form_summary or '暂无 recent filing 摘要'}。"
            "该来源来自 SEC data.sec.gov，可用于后续查找 10-K、10-Q、8-K 与 XBRL company facts。"
        )
        return ProviderSearchResult(
            provider=self.name,
            status="success",
            items=[
                {
                    "url": url,
                    "title": f"{name} SEC EDGAR submissions",
                    "source_type": "regulatory",
                    "provider": self.name,
                    "published_at": filing_dates[0] if filing_dates else None,
                    "content": content,
                    "source_origin_type": "official_disclosure",
                }
            ],
        )


def get_supplemental_providers(settings: Settings | None = None) -> list[SupplementalProvider]:
    active_settings = settings or get_settings()
    if not active_settings.supplemental_search_enabled:
        return []
    return [
        AkshareSupplementalProvider(),
        YFinanceSupplementalProvider(),
        SecEdgarSupplementalProvider(active_settings),
    ]


def search_supplemental_sources(
    query: str,
    topic: Topic | None = None,
    providers: list[SupplementalProvider] | None = None,
) -> tuple[list[SearchResult], list[ProviderSearchResult]]:
    """Run non-Tavily supplemental providers concurrently and skip failures."""

    active_providers = providers if providers is not None else get_supplemental_providers()
    if not active_providers:
        return [], []

    results: list[SearchResult] = []
    attempts: list[ProviderSearchResult] = []
    with ThreadPoolExecutor(max_workers=len(active_providers)) as executor:
        future_map = {executor.submit(provider.search, query, topic): provider for provider in active_providers}
        for future in as_completed(future_map):
            provider = future_map[future]
            try:
                attempt = future.result()
            except Exception as exc:  # pragma: no cover - defensive safety net
                attempt = ProviderSearchResult(provider=provider.name, status="error", error=str(exc))
            attempts.append(attempt)
            if attempt.status == "success":
                results.extend(attempt.items)
    return results, attempts
