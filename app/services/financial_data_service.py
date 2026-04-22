from __future__ import annotations

import logging
import time
from typing import Any

from app.config import get_settings
from app.models.financial import FinancialMetric, FinancialSnapshot, ProviderAttempt
from app.models.topic import Topic
from app.services.listing_status_service import is_listed_company, is_private_or_unlisted
from app.services.search_service import search

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = {"SUCCESS", "PARTIAL_SUCCESS", "FALLBACK_USED"}

_SYMBOL_MAP = {
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

_PEER_SYMBOLS = {
    "PDD": ["BABA", "JD", "AMZN"],
    "BABA": ["PDD", "JD", "AMZN"],
    "JD": ["BABA", "PDD"],
    "300750.SZ": ["1211.HK", "TSLA"],
    "1211.HK": ["300750.SZ", "TSLA"],
    "TSLA": ["1211.HK", "300750.SZ"],
    "NVDA": ["AMD", "AVGO", "INTC"],
    "AMD": ["NVDA", "AVGO", "INTC"],
    "AVGO": ["NVDA", "AMD", "INTC"],
    "MSFT": ["AAPL", "GOOG", "AMZN"],
    "AAPL": ["MSFT", "GOOG", "AMZN"],
    "0700.HK": ["BABA", "3690.HK", "JD"],
    "3690.HK": ["0700.HK", "BABA", "JD"],
    "JPM": ["BAC", "C", "GS"],
    "BAC": ["JPM", "C", "WFC"],
}

_INVESTING_SLUGS = {
    "0700.HK": "tencent-holdings",
    "3690.HK": "meituan",
    "1211.HK": "byd",
    "BABA": "alibaba",
    "PDD": "pdd-holdings",
    "JD": "jd.com",
    "AAPL": "apple-computer-inc",
    "MSFT": "microsoft-corp",
    "NVDA": "nvidia-corp",
    "TSLA": "tesla-motors",
}

_PROVIDER_NAME_ALIASES = {
    "0700.HK": ["Tencent", "Tencent Holdings", "Tencent Holdings Ltd"],
    "3690.HK": ["Meituan", "Meituan Dianping"],
    "1211.HK": ["BYD", "BYD Company"],
    "300750.SZ": ["CATL", "Contemporary Amperex Technology"],
}

_INCOME_ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue", "营业总收入", "营业收入"],
    "gross_profit": ["Gross Profit", "毛利"],
    "net_income": ["Net Income", "Net Income Common Stockholders", "归母净利润", "净利润"],
}
_BALANCE_ROWS = {
    "total_assets": ["Total Assets", "总资产"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities", "总负债"],
}
_CASHFLOW_ROWS = {
    "operating_cash_flow": ["Operating Cash Flow", "Total Cash From Operating Activities", "经营活动现金流量净额"],
}


class FinancialProviderError(Exception):
    """Structured provider failure that can be surfaced to UI and logs."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        retryable: bool = False,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.retryable = retryable
        self.error_type = error_type or status


def _attempt(
    provider: str,
    symbol: str | None,
    market: str | None,
    status: str,
    message: str,
    *,
    retryable: bool = False,
    fallback_available: bool = False,
    next_provider: str | None = None,
    latency_ms: int | None = None,
    error_type: str | None = None,
) -> ProviderAttempt:
    return ProviderAttempt(
        provider=provider,
        symbol=symbol,
        market=market,
        status=status,
        message=message,
        retryable=retryable,
        fallback_available=fallback_available,
        next_provider=next_provider,
        latency_ms=latency_ms,
        error_type=error_type,
    )


def _record_provider_log(attempt: ProviderAttempt, fallback_used: bool, success_provider: str | None) -> None:
    logger.info(
        "financial_provider_attempt",
        extra={
            "provider": attempt.provider,
            "symbol": attempt.symbol,
            "market": attempt.market,
            "latency_ms": attempt.latency_ms,
            "status": attempt.status,
            "error_type": attempt.error_type,
            "fallback_used": fallback_used,
            "success_provider": success_provider,
        },
    )


def _classify_exception(exc: Exception) -> FinancialProviderError:
    if isinstance(exc, FinancialProviderError):
        return exc
    name = type(exc).__name__
    message = str(exc) or name
    lowered = message.lower()
    if "timeout" in lowered or name.lower().endswith("timeout"):
        return FinancialProviderError("PROVIDER_TIMEOUT", message, retryable=True, error_type=name)
    if "rate" in lowered or "429" in lowered or "too many" in lowered:
        return FinancialProviderError("PROVIDER_RATE_LIMIT", message, retryable=True, error_type=name)
    if "auth" in lowered or "token" in lowered or "permission" in lowered or "401" in lowered or "403" in lowered:
        return FinancialProviderError("AUTH_REQUIRED", message, retryable=False, error_type=name)
    if (
        "network" in lowered
        or "connection" in lowered
        or "dns" in lowered
        or "could not resolve" in lowered
        or "resolve host" in lowered
        or "name resolution" in lowered
        or "dns" in name.lower()
    ):
        return FinancialProviderError("NETWORK_ERROR", message, retryable=True, error_type=name)
    if "parse" in lowered or "dataframe" in lowered or "column" in lowered:
        return FinancialProviderError("PARSE_ERROR", message, retryable=False, error_type=name)
    return FinancialProviderError("UNKNOWN_ERROR", message, retryable=True, error_type=name)


def resolve_symbol(topic: Topic) -> str | None:
    if is_private_or_unlisted(topic.listing_status):
        return None
    if topic.entity and topic.entity in _SYMBOL_MAP:
        return _SYMBOL_MAP[topic.entity]
    if topic.topic in _SYMBOL_MAP:
        return _SYMBOL_MAP[topic.topic]
    return None


def _market(topic: Topic, symbol: str | None) -> str:
    market = getattr(topic, "market_type", None)
    if market and market != "other":
        return market
    if symbol and symbol.endswith((".SZ", ".SH")):
        return "A_share"
    if symbol and symbol.endswith(".HK"):
        return "HK"
    return "US" if symbol else "other"


def _provider_route(market: str) -> list[str]:
    if market == "A_share":
        # We record yfinance as unsupported for A-share before falling back to domestic providers.
        return ["yfinance", "akshare", "eastmoney"]
    if market == "HK":
        return ["yfinance", "akshare", "investing", "futu_api"]
    if market == "US":
        return ["yfinance", "polygon", "finnhub"]
    if market == "fund":
        return ["yfinance", "akshare"]
    return ["yfinance"]


def _coerce_number(value: Any) -> float | str | None:
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    return str(value)


def _unique_strings(items: list[str | None]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item is None:
            continue
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _provider_symbol_variants(provider: str, symbol: str, market: str, entity: str | None = None) -> list[str]:
    """Generate provider-specific query keys from one canonical symbol."""

    if market == "HK" and symbol.endswith(".HK"):
        code = symbol.removesuffix(".HK")
        stripped = code.lstrip("0") or code
        padded_4 = code.zfill(4)
        yahoo_variants = [f"{padded_4}.HK", f"{stripped}.HK", symbol]
        raw_variants = [padded_4, stripped, code]
        aliases = _PROVIDER_NAME_ALIASES.get(symbol, [])
        if provider == "yfinance":
            return _unique_strings(yahoo_variants)
        if provider == "akshare":
            return _unique_strings([padded_4, stripped, symbol, entity, *aliases])
        if provider == "investing":
            return _unique_strings([_INVESTING_SLUGS.get(symbol), *raw_variants, entity, *aliases])
        return _unique_strings([symbol, *raw_variants, entity, *aliases])

    if market == "A_share" and symbol.endswith((".SZ", ".SH")):
        code = symbol.removesuffix(".SZ").removesuffix(".SH")
        if provider in {"akshare", "eastmoney"}:
            return _unique_strings([code, symbol, entity, *_PROVIDER_NAME_ALIASES.get(symbol, [])])
        return _unique_strings([symbol, code, entity])

    if provider == "investing":
        return _unique_strings([_INVESTING_SLUGS.get(symbol), symbol, entity, *_PROVIDER_NAME_ALIASES.get(symbol, [])])
    return _unique_strings([symbol, entity, *_PROVIDER_NAME_ALIASES.get(symbol, [])])


def _compact_error_summary(errors: list[tuple[str, FinancialProviderError]]) -> str:
    return "；".join(f"{query_symbol}: {error.status}({error.message})" for query_symbol, error in errors[:4])


def _safe_info_value(info: dict, key: str) -> float | str | None:
    return _coerce_number(info.get(key))


def _statement_metrics(statement: Any, row_aliases: dict[str, list[str]], source_name: str, limit: int = 4) -> list[FinancialMetric]:
    metrics: list[FinancialMetric] = []
    if statement is None or getattr(statement, "empty", True):
        return metrics

    row_labels = [str(index) for index in statement.index]
    columns = list(statement.columns)[:limit]
    for metric_name, aliases in row_aliases.items():
        matched_label = next((label for label in row_labels if any(alias.lower() == label.lower() for alias in aliases)), None)
        if matched_label is None:
            matched_label = next((label for label in row_labels if any(alias.lower() in label.lower() for alias in aliases)), None)
        if matched_label is None:
            continue
        for column in columns:
            value = _coerce_number(statement.loc[matched_label, column])
            if value is None:
                continue
            period = column.strftime("%Y-%m-%d") if hasattr(column, "strftime") else str(column)
            metrics.append(
                FinancialMetric(
                    name=metric_name,
                    value=value,
                    unit=None,
                    period=period,
                    source=source_name,
                )
            )
    return metrics


def _info_metrics(info: dict) -> list[FinancialMetric]:
    info_keys = {
        "market_cap": ("marketCap", "currency"),
        "trailing_pe": ("trailingPE", None),
        "forward_pe": ("forwardPE", None),
        "profit_margins": ("profitMargins", "%"),
        "revenue_growth": ("revenueGrowth", "%"),
        "debt_to_equity": ("debtToEquity", None),
        "return_on_equity": ("returnOnEquity", "%"),
        "gross_margins": ("grossMargins", "%"),
    }
    metrics: list[FinancialMetric] = []
    currency = info.get("financialCurrency") or info.get("currency")
    for metric_name, (info_key, unit) in info_keys.items():
        value = _safe_info_value(info, info_key)
        if value is None:
            continue
        metrics.append(
            FinancialMetric(
                name=metric_name,
                value=value,
                unit=currency if unit == "currency" else unit,
                period="latest",
                source="yfinance.info",
            )
        )
    return metrics


def _fetch_yfinance_snapshot(symbol: str, peer_key: str | None = None) -> tuple[list[FinancialMetric], list[dict]]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    metrics = _info_metrics(info)
    metrics.extend(_statement_metrics(ticker.income_stmt, _INCOME_ROWS, "yfinance.income_stmt"))
    metrics.extend(_statement_metrics(ticker.balance_sheet, _BALANCE_ROWS, "yfinance.balance_sheet"))
    metrics.extend(_statement_metrics(ticker.cashflow, _CASHFLOW_ROWS, "yfinance.cashflow"))
    canonical_peer_key = peer_key or symbol
    peer_rows = build_peer_comparison(canonical_peer_key, _PEER_SYMBOLS.get(canonical_peer_key, []))
    return metrics, peer_rows


def _normalize_hk_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits.lstrip("0") or digits


def _fetch_akshare_hk_snapshot(query_symbol: str, entity: str | None = None) -> tuple[list[FinancialMetric], list[dict]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise FinancialProviderError(
            "PROVIDER_DOWN",
            "akshare 未安装，无法使用港股备用结构化数据源。",
            retryable=False,
            error_type=type(exc).__name__,
        ) from exc

    spot_func = getattr(ak, "stock_hk_spot_em", None)
    if spot_func is None:
        raise FinancialProviderError(
            "PROVIDER_DOWN",
            "当前 akshare 版本未提供 stock_hk_spot_em，无法查询港股快照。",
            retryable=False,
        )

    query_code = _normalize_hk_code(query_symbol)
    try:
        spot = spot_func()
    except Exception as exc:
        classified = _classify_exception(exc)
        classified.message = f"akshare 港股行情接口失败：{classified.message}"
        raise classified from exc

    if spot is None or getattr(spot, "empty", True):
        raise FinancialProviderError("EMPTY_RESPONSE", "akshare 港股行情接口未返回数据。", retryable=True)

    rows = []
    for _, row in spot.iterrows():
        row_dict = row.to_dict()
        code = row_dict.get("代码") or row_dict.get("symbol") or row_dict.get("证券代码")
        name = str(row_dict.get("名称") or row_dict.get("name") or row_dict.get("证券简称") or "")
        code_match = bool(query_code and _normalize_hk_code(code) == query_code)
        entity_match = bool(entity and entity in name)
        if code_match or entity_match:
            rows.append(row_dict)
            break

    if not rows:
        raise FinancialProviderError("EMPTY_RESPONSE", f"akshare 港股行情未匹配到 {query_symbol}。", retryable=True)

    first = rows[0]
    metric_map = {
        "latest_price": ["最新价", "现价", "最新"],
        "change_pct": ["涨跌幅", "涨幅"],
        "turnover": ["成交额"],
        "volume": ["成交量"],
        "market_cap": ["总市值", "市值"],
        "pe_ttm": ["市盈率", "市盈率-动态", "PE"],
    }
    metrics: list[FinancialMetric] = []
    for metric_name, columns in metric_map.items():
        column = next((item for item in columns if item in first), None)
        if column is None:
            continue
        value = _coerce_number(first.get(column))
        if value is not None:
            metrics.append(
                FinancialMetric(
                    name=metric_name,
                    value=value,
                    unit=None,
                    period="latest",
                    source="akshare.stock_hk_spot_em",
                )
            )
    if not metrics:
        raise FinancialProviderError("EMPTY_RESPONSE", f"akshare 港股行情匹配到 {query_symbol}，但没有可用指标。", retryable=True)
    return metrics, []


def _fetch_akshare_snapshot(symbol: str, market: str = "A_share", entity: str | None = None) -> tuple[list[FinancialMetric], list[dict]]:
    if market == "HK":
        return _fetch_akshare_hk_snapshot(symbol, entity)

    try:
        import akshare as ak
    except ImportError as exc:
        raise FinancialProviderError(
            "PROVIDER_DOWN",
            "akshare 未安装，无法使用 A 股备用结构化数据源。",
            retryable=False,
            error_type=type(exc).__name__,
        ) from exc

    code = symbol.replace(".SZ", "").replace(".SH", "")
    if not (code.isdigit() and len(code) == 6):
        raise FinancialProviderError(
            "INVALID_SYMBOL_FORMAT",
            f"A 股 symbol 格式无效：{symbol}",
            retryable=False,
        )

    metrics: list[FinancialMetric] = []
    try:
        spot = ak.stock_zh_a_spot_em()
        row = spot[spot["代码"].astype(str) == code]
        if not row.empty:
            first = row.iloc[0].to_dict()
            metric_map = {
                "latest_price": "最新价",
                "market_cap": "总市值",
                "pe_ttm": "市盈率-动态",
                "pb": "市净率",
                "turnover_rate": "换手率",
            }
            for metric_name, column in metric_map.items():
                if column in first:
                    value = _coerce_number(first.get(column))
                    if value is not None:
                        metrics.append(
                            FinancialMetric(
                                name=metric_name,
                                value=value,
                                unit=None,
                                period="latest",
                                source="akshare.stock_zh_a_spot_em",
                            )
                        )
    except Exception as exc:
        classified = _classify_exception(exc)
        classified.message = f"akshare A 股行情接口失败：{classified.message}"
        raise classified from exc

    try:
        financial_abstract = ak.stock_financial_abstract(symbol=code)
        if financial_abstract is not None and not financial_abstract.empty:
            rows = financial_abstract.head(24)
            for _, row in rows.iterrows():
                text = " ".join(str(value) for value in row.to_dict().values() if value is not None)
                if not any(token in text for token in ["营业收入", "净利润", "毛利率", "现金流", "资产负债率"]):
                    continue
                metrics.append(
                    FinancialMetric(
                        name="akshare_financial_abstract",
                        value=text[:180],
                        unit=None,
                        period="latest",
                        source="akshare.stock_financial_abstract",
                    )
                )
                if len(metrics) >= 16:
                    break
    except Exception:
        # Spot data is still useful for a partial snapshot; financial abstract failures should not discard it.
        pass

    if not metrics:
        raise FinancialProviderError("EMPTY_RESPONSE", "akshare 未返回可用 A 股行情或财务摘要。", retryable=True)
    return metrics, []


def _fetch_investing_snapshot(query_symbol: str, entity: str | None = None) -> tuple[list[FinancialMetric], list[dict]]:
    query = f"{entity or ''} {query_symbol} site:investing.com market cap PE revenue financials".strip()
    try:
        results = search(query)
    except Exception as exc:
        classified = _classify_exception(exc)
        classified.message = f"investing 搜索入口失败：{classified.message}"
        raise classified from exc
    if not results:
        raise FinancialProviderError("EMPTY_RESPONSE", f"investing 未返回 {query_symbol} 的可用结果。", retryable=True)

    top = results[0]
    title = top.get("title", "Investing result")
    url = top.get("url", "")
    content = top.get("content", "")
    return [
        FinancialMetric(name="market_search_title", value=title, period="latest_search", source="investing.search"),
        FinancialMetric(name="market_search_url", value=url, period="latest_search", source="investing.search"),
        FinancialMetric(name="market_search_snippet", value=content[:260], period="latest_search", source="investing.search"),
    ], []


def _fetch_finnhub_json(path: str, symbol: str, params: dict[str, str] | None = None) -> dict:
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise FinancialProviderError(
            "AUTH_REQUIRED",
            "FINNHUB_API_KEY 未配置，无法调用 Finnhub provider。",
            retryable=False,
        )
    try:
        import httpx

        response = httpx.get(
            f"{settings.finnhub_base_url.rstrip('/')}/{path.lstrip('/')}",
            params={"symbol": symbol, **(params or {}), "token": settings.finnhub_api_key},
            timeout=settings.search_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        classified = _classify_exception(exc)
        classified.message = f"Finnhub {path} 请求失败：{classified.message}"
        raise classified from exc
    if not isinstance(payload, dict):
        raise FinancialProviderError("PARSE_ERROR", f"Finnhub {path} 返回格式不是 JSON object。", retryable=False)
    return payload


def _fetch_finnhub_snapshot(symbol: str) -> tuple[list[FinancialMetric], list[dict]]:
    profile = _fetch_finnhub_json("stock/profile2", symbol)
    quote = _fetch_finnhub_json("quote", symbol)
    metric_payload = _fetch_finnhub_json("stock/metric", symbol, {"metric": "all"})
    metric_data = metric_payload.get("metric") if isinstance(metric_payload.get("metric"), dict) else {}

    metrics: list[FinancialMetric] = []
    metric_specs = [
        ("market_cap", profile.get("marketCapitalization"), profile.get("currency"), "finnhub.stock.profile2"),
        ("share_outstanding", profile.get("shareOutstanding"), None, "finnhub.stock.profile2"),
        ("latest_price", quote.get("c"), profile.get("currency"), "finnhub.quote"),
        ("previous_close", quote.get("pc"), profile.get("currency"), "finnhub.quote"),
        ("day_high", quote.get("h"), profile.get("currency"), "finnhub.quote"),
        ("day_low", quote.get("l"), profile.get("currency"), "finnhub.quote"),
        ("pe_ttm", metric_data.get("peTTM") or metric_data.get("peNormalizedAnnual"), None, "finnhub.stock.metric"),
        ("pb", metric_data.get("pbAnnual") or metric_data.get("pbQuarterly"), None, "finnhub.stock.metric"),
        ("gross_margins", metric_data.get("grossMarginTTM"), "%", "finnhub.stock.metric"),
        ("net_profit_margin", metric_data.get("netProfitMarginTTM"), "%", "finnhub.stock.metric"),
        ("revenue_growth", metric_data.get("revenueGrowthTTMYoy"), "%", "finnhub.stock.metric"),
        ("debt_to_equity", metric_data.get("totalDebt/totalEquityQuarterly"), None, "finnhub.stock.metric"),
        ("roe", metric_data.get("roeTTM"), "%", "finnhub.stock.metric"),
    ]
    for name, raw_value, unit, source in metric_specs:
        value = _coerce_number(raw_value)
        if value is None:
            continue
        metrics.append(FinancialMetric(name=name, value=value, unit=unit, period="latest", source=source))

    if not metrics:
        raise FinancialProviderError("EMPTY_RESPONSE", f"Finnhub 未返回 {symbol} 的可用金融指标。", retryable=True)
    return metrics, build_peer_comparison(symbol, _PEER_SYMBOLS.get(symbol, []))


def _fetch_massive_json(path: str, params: dict[str, str] | None = None) -> dict:
    settings = get_settings()
    if not settings.massive_api_key:
        raise FinancialProviderError(
            "AUTH_REQUIRED",
            "MASSIVE_API_KEY 未配置，无法调用 Massive/Polygon provider。",
            retryable=False,
        )
    try:
        import httpx

        response = httpx.get(
            f"{settings.massive_base_url.rstrip('/')}/{path.lstrip('/')}",
            params={**(params or {}), "apiKey": settings.massive_api_key},
            timeout=settings.search_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        classified = _classify_exception(exc)
        classified.message = f"Massive {path} 请求失败：{classified.message}"
        raise classified from exc
    if not isinstance(payload, dict):
        raise FinancialProviderError("PARSE_ERROR", f"Massive {path} 返回格式不是 JSON object。", retryable=False)
    if str(payload.get("status", "")).upper() in {"ERROR", "NOT_AUTHORIZED"}:
        raise FinancialProviderError(
            "AUTH_REQUIRED",
            f"Massive {path} 返回认证/权限错误：{payload.get('error') or payload.get('message') or payload.get('status')}",
            retryable=False,
        )
    return payload


def _fetch_massive_snapshot(symbol: str) -> tuple[list[FinancialMetric], list[dict]]:
    details_payload = _fetch_massive_json(f"v3/reference/tickers/{symbol}")
    prev_payload = _fetch_massive_json(f"v2/aggs/ticker/{symbol}/prev", {"adjusted": "true"})

    details = details_payload.get("results") if isinstance(details_payload.get("results"), dict) else {}
    prev_results = prev_payload.get("results") if isinstance(prev_payload.get("results"), list) else []
    prev_bar = prev_results[0] if prev_results and isinstance(prev_results[0], dict) else {}

    currency = details.get("currency_name") or details.get("currency") or "USD"
    metric_specs = [
        ("market_cap", details.get("market_cap"), currency, "massive.reference.tickers"),
        ("share_class_shares_outstanding", details.get("share_class_shares_outstanding"), None, "massive.reference.tickers"),
        ("weighted_shares_outstanding", details.get("weighted_shares_outstanding"), None, "massive.reference.tickers"),
        ("previous_close", prev_bar.get("c"), currency, "massive.aggs.prev"),
        ("previous_open", prev_bar.get("o"), currency, "massive.aggs.prev"),
        ("previous_high", prev_bar.get("h"), currency, "massive.aggs.prev"),
        ("previous_low", prev_bar.get("l"), currency, "massive.aggs.prev"),
        ("previous_volume", prev_bar.get("v"), None, "massive.aggs.prev"),
        ("previous_vwap", prev_bar.get("vw"), currency, "massive.aggs.prev"),
    ]

    metrics: list[FinancialMetric] = []
    for name, raw_value, unit, source in metric_specs:
        value = _coerce_number(raw_value)
        if value is None:
            continue
        metrics.append(FinancialMetric(name=name, value=value, unit=unit, period="latest", source=source))

    if not metrics:
        raise FinancialProviderError("EMPTY_RESPONSE", f"Massive 未返回 {symbol} 的可用市场快照指标。", retryable=True)
    return metrics, build_peer_comparison(symbol, _PEER_SYMBOLS.get(symbol, []))


def _fetch_provider_snapshot(
    provider: str,
    symbol: str,
    market: str,
    *,
    entity: str | None = None,
    canonical_symbol: str | None = None,
) -> tuple[list[FinancialMetric], list[dict]]:
    if provider == "yfinance":
        if market == "A_share":
            raise FinancialProviderError(
                "UNSUPPORTED_MARKET",
                "yfinance 对部分中国 A 股代码支持不稳定，当前市场优先使用 A 股本地 provider。",
                retryable=True,
            )
        return _fetch_yfinance_snapshot(symbol, peer_key=canonical_symbol)
    if provider == "akshare":
        return _fetch_akshare_snapshot(symbol, market, entity)
    if provider == "investing":
        return _fetch_investing_snapshot(symbol, entity)
    if provider == "finnhub":
        return _fetch_finnhub_snapshot(symbol)
    if provider == "polygon":
        return _fetch_massive_snapshot(symbol)
    raise FinancialProviderError(
        "PROVIDER_DOWN",
        f"{provider} provider 尚未配置可用凭证或实现，已跳过。",
        retryable=False,
    )


def _fetch_provider_snapshot_with_variants(
    provider: str,
    canonical_symbol: str,
    market: str,
    entity: str | None,
) -> tuple[list[FinancialMetric], list[dict], str, list[str]]:
    variants = _provider_symbol_variants(provider, canonical_symbol, market, entity)
    errors: list[tuple[str, FinancialProviderError]] = []
    for query_symbol in variants:
        try:
            metrics, peer_rows = _fetch_provider_snapshot(
                provider,
                query_symbol,
                market,
                entity=entity,
                canonical_symbol=canonical_symbol,
            )
            if metrics:
                return metrics, peer_rows, query_symbol, variants
            errors.append(
                (
                    query_symbol,
                    FinancialProviderError("EMPTY_RESPONSE", f"{provider} 使用 {query_symbol} 未返回可用财务指标。", retryable=True),
                )
            )
        except Exception as exc:
            errors.append((query_symbol, _classify_exception(exc)))
            continue

    if errors:
        last_symbol, last_error = errors[-1]
        tried = ", ".join(variants)
        summary = _compact_error_summary(errors)
        raise FinancialProviderError(
            last_error.status,
            f"{provider} 已尝试格式 [{tried}]，均未成功。最后失败格式 {last_symbol}: {last_error.message}。尝试摘要：{summary}",
            retryable=any(error.retryable for _, error in errors),
            error_type=last_error.error_type,
        )
    raise FinancialProviderError("EMPTY_RESPONSE", f"{provider} 未生成任何可查询 symbol 格式。", retryable=True)


def _valuation_from_metrics(metrics: list[FinancialMetric], peer_rows: list[dict]) -> dict:
    latest = {metric.name: metric.value for metric in metrics if metric.period == "latest"}
    valuation = {
        "market_cap": latest.get("market_cap"),
        "trailing_pe": latest.get("trailing_pe"),
        "forward_pe": latest.get("forward_pe"),
        "profit_margins": latest.get("profit_margins"),
        "revenue_growth": latest.get("revenue_growth"),
        "return_on_equity": latest.get("return_on_equity"),
        "peer_count": len(peer_rows),
    }
    valid_peers = [row for row in peer_rows if row.get("trailingPE") is not None]
    if valid_peers:
        valuation["peer_median_trailing_pe"] = sorted(float(row["trailingPE"]) for row in valid_peers)[len(valid_peers) // 2]
    return {key: value for key, value in valuation.items() if value is not None}


def build_peer_comparison(entity_symbol: str, peer_symbols: list[str]) -> list[dict]:
    import yfinance as yf

    rows: list[dict] = []
    for symbol in [entity_symbol, *peer_symbols[:3]]:
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception:
            continue
        row = {
            "symbol": symbol,
            "marketCap": _safe_info_value(info, "marketCap"),
            "trailingPE": _safe_info_value(info, "trailingPE"),
            "profitMargins": _safe_info_value(info, "profitMargins"),
            "revenueGrowth": _safe_info_value(info, "revenueGrowth"),
            "debtToEquity": _safe_info_value(info, "debtToEquity"),
            "returnOnEquity": _safe_info_value(info, "returnOnEquity"),
        }
        if any(value is not None for key, value in row.items() if key != "symbol"):
            rows.append(row)
    return rows


def _fetch_market_fallback_from_search(entity: str) -> FinancialSnapshot:
    query = f"{entity} 股价 市值 财报 股票"
    try:
        results = search(query)
    except Exception as exc:
        return FinancialSnapshot(
            entity=entity,
            symbol=None,
            provider="tavily_search_fallback",
            status="ALL_PROVIDERS_FAILED",
            provider_status=_attempt(
                "tavily_search_fallback",
                None,
                None,
                "NETWORK_ERROR",
                f"股票代码未解析，且轻量金融搜索失败：{type(exc).__name__}",
                retryable=True,
            ),
            note=f"股票代码未解析，且轻量金融搜索失败：{type(exc).__name__}",
        )

    if not results:
        return FinancialSnapshot(
            entity=entity,
            symbol=None,
            provider="tavily_search_fallback",
            status="SYMBOL_NOT_FOUND",
            provider_status=_attempt(
                "tavily_search_fallback",
                None,
                None,
                "EMPTY_RESPONSE",
                "股票代码未解析，轻量金融搜索未返回可用结果。",
                retryable=True,
            ),
            note="股票代码未解析，轻量金融搜索未返回可用结果。",
        )

    top = results[0]
    title = top.get("title", "未命名结果")
    url = top.get("url", "")
    content = top.get("content", "")
    return FinancialSnapshot(
        entity=entity,
        symbol=None,
        provider="tavily_search_fallback",
        status="FALLBACK_USED",
        provider_status=_attempt(
            "tavily_search_fallback",
            None,
            None,
            "SUCCESS",
            "股票代码未解析，已用真实搜索补充轻量金融信息。",
            retryable=False,
        ),
        provider_attempts=[
            _attempt("symbol_resolver", None, None, "SYMBOL_NOT_FOUND", "未能解析股票代码。", retryable=False),
            _attempt("tavily_search_fallback", None, None, "SUCCESS", "真实搜索补充轻量金融信息。"),
        ],
        fallback_used=True,
        success_provider="tavily_search_fallback",
        metrics=[
            FinancialMetric(name="market_search_title", value=title, period="latest_search", source="tavily_search_fallback"),
            FinancialMetric(name="market_search_url", value=url, period="latest_search", source="tavily_search_fallback"),
            FinancialMetric(name="market_search_snippet", value=content[:260], period="latest_search", source="tavily_search_fallback"),
        ],
        note="未能解析股票代码，已用真实搜索补充一条轻量金融信息；该结果仅用于避免初筛空白，不能替代结构化行情或财报数据。",
    )


def _all_providers_failed_snapshot(
    entity: str,
    symbol: str | None,
    market: str | None,
    attempts: list[ProviderAttempt],
) -> FinancialSnapshot:
    note = "；".join(f"{item.provider}: {item.status}({item.message})" for item in attempts)
    message = f"所有结构化金融 provider 均失败：{note}" if note else "未找到可用结构化金融 provider。"
    return FinancialSnapshot(
        entity=entity,
        symbol=symbol,
        provider="provider_router",
        status="ALL_PROVIDERS_FAILED",
        provider_status=_attempt(
            "provider_router",
            symbol,
            market,
            "ALL_PROVIDERS_FAILED",
            message,
            retryable=any(item.retryable for item in attempts),
            error_type="ALL_PROVIDERS_FAILED",
        ),
        provider_attempts=attempts,
        fallback_used=len(attempts) > 1,
        success_provider=None,
        peer_symbols=_PEER_SYMBOLS.get(symbol or "", []),
        note=message,
    )


def _fetch_market_fallback_for_symbol(
    entity: str,
    symbol: str,
    market: str,
    attempts: list[ProviderAttempt],
) -> FinancialSnapshot:
    query = f"{entity} {symbol} 股价 市值 财报 业绩"
    try:
        results = search(query)
    except Exception as exc:
        classified = _classify_exception(exc)
        fallback_attempt = _attempt(
            "tavily_search_fallback",
            symbol,
            market,
            classified.status,
            f"结构化 provider 均失败，搜索 fallback 也失败：{classified.message}",
            retryable=classified.retryable,
            error_type=classified.error_type,
        )
        return _all_providers_failed_snapshot(entity, symbol, market, [*attempts, fallback_attempt])

    if not results:
        fallback_attempt = _attempt(
            "tavily_search_fallback",
            symbol,
            market,
            "EMPTY_RESPONSE",
            "结构化 provider 均失败，搜索 fallback 未返回可用结果。",
            retryable=True,
        )
        return _all_providers_failed_snapshot(entity, symbol, market, [*attempts, fallback_attempt])

    top = results[0]
    title = top.get("title", "未命名结果")
    url = top.get("url", "")
    content = top.get("content", "")
    fallback_attempt = _attempt(
        "tavily_search_fallback",
        symbol,
        market,
        "SUCCESS",
        "结构化 provider 均失败，已用真实搜索补充轻量金融信息。",
        retryable=False,
    )
    return FinancialSnapshot(
        entity=entity,
        symbol=symbol,
        provider="tavily_search_fallback",
        status="FALLBACK_USED",
        provider_status=fallback_attempt,
        provider_attempts=[*attempts, fallback_attempt],
        fallback_used=True,
        success_provider="tavily_search_fallback",
        peer_symbols=_PEER_SYMBOLS.get(symbol, []),
        metrics=[
            FinancialMetric(name="market_search_title", value=title, period="latest_search", source="tavily_search_fallback"),
            FinancialMetric(name="market_search_url", value=url, period="latest_search", source="tavily_search_fallback"),
            FinancialMetric(name="market_search_snippet", value=content[:260], period="latest_search", source="tavily_search_fallback"),
        ],
        note=(
            "结构化金融 provider 全部失败，已用真实搜索补充一条轻量金融信息；"
            "该结果仅用于避免初筛空白，不能替代结构化行情、公司公告或审计财报。"
        ),
    )


def fetch_financial_snapshot(topic: Topic) -> FinancialSnapshot:
    """Fetch a no-key yfinance snapshot plus a small peer comparison table."""

    entity = topic.entity or topic.topic
    if not is_listed_company(topic):
        object_type = getattr(topic, "research_object_type", "unknown")
        if is_private_or_unlisted(topic.listing_status):
            status = "unlisted"
            note = (
                f"{entity}未公开上市，无法生成公开股票估值快照或公开 ticker。"
                "系统已切换为非上市公司经营质量、产业链机会、可比模式和潜在上市情景研究。"
            )
        elif object_type == "credit_issuer":
            status = "not_applicable_credit_issuer"
            note = "当前对象是信用主体/债券研究，应走偿债能力、再融资和评级路径，不调用股票金融快照。"
        elif object_type in {"industry_theme", "macro_theme", "event", "concept_theme", "fund_etf", "commodity"}:
            status = f"not_applicable_{object_type}"
            note = "当前对象不是单一上市公司，金融快照不适用；系统会使用行业/主题/资产研究路径。"
        else:
            status = "not_applicable"
            note = "当前对象未识别为上市公司，未调用结构化股票金融数据接口。"
        return FinancialSnapshot(
            entity=entity,
            symbol=None,
            provider="listing_status_engine" if status == "unlisted" else "object_classifier",
            status="UNSUPPORTED_MARKET" if status == "unlisted" else "UNSUPPORTED_MARKET",
            provider_status=_attempt(
                "object_classifier",
                None,
                getattr(topic, "market_type", None),
                "UNSUPPORTED_MARKET",
                note,
                retryable=False,
            ),
            note=note,
        )

    if is_private_or_unlisted(topic.listing_status):
        return FinancialSnapshot(
            entity=entity,
            symbol=None,
            provider="listing_status_engine",
            status="UNSUPPORTED_MARKET",
            provider_status=_attempt(
                "listing_status_engine",
                None,
                getattr(topic, "market_type", None),
                "UNSUPPORTED_MARKET",
                f"{entity}未公开上市，无法生成公开股票估值快照或公开 ticker。",
                retryable=False,
            ),
            note=(
                f"{entity}未公开上市，无法生成公开股票估值快照或公开 ticker。"
                "系统应切换为非上市公司经营质量、产业链机会、概念股筛选和潜在上市情景研究。"
            ),
        )
    symbol = resolve_symbol(topic)
    if not symbol:
        return _fetch_market_fallback_from_search(entity)

    market = _market(topic, symbol)
    providers = _provider_route(market)
    attempts: list[ProviderAttempt] = []
    for index, provider in enumerate(providers):
        start = time.perf_counter()
        next_provider = providers[index + 1] if index + 1 < len(providers) else None
        try:
            metrics, peer_rows, query_symbol, tried_symbols = _fetch_provider_snapshot_with_variants(provider, symbol, market, entity)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if not metrics:
                raise FinancialProviderError("EMPTY_RESPONSE", f"{provider} 未返回可用财务指标。", retryable=True)
            success_status = "SUCCESS" if not attempts else "FALLBACK_USED"
            attempt = _attempt(
                provider,
                query_symbol,
                market,
                "SUCCESS",
                f"{provider} 使用格式 {query_symbol} 返回 {len(metrics)} 个结构化指标；已尝试格式：{', '.join(tried_symbols)}。",
                retryable=False,
                latency_ms=latency_ms,
            )
            attempts.append(attempt)
            for item in attempts[:-1]:
                _record_provider_log(item, fallback_used=bool(attempts[:-1]), success_provider=provider)
            _record_provider_log(attempt, fallback_used=bool(attempts[:-1]), success_provider=provider)
            return FinancialSnapshot(
                entity=entity,
                symbol=symbol,
                provider=provider,
                status=success_status,
                provider_status=attempt,
                provider_attempts=attempts,
                fallback_used=success_status == "FALLBACK_USED",
                success_provider=provider,
                metrics=metrics,
                peer_symbols=_PEER_SYMBOLS.get(symbol, []),
                peer_comparison=peer_rows,
                valuation=_valuation_from_metrics(metrics, peer_rows),
                note=(
                    f"最终来源：{provider}。"
                    f"{' 已使用备用 provider。' if success_status == 'FALLBACK_USED' else ''}"
                    "该快照适合 Demo 初筛，不替代公司公告、审计财报或专业数据库。"
                ),
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            classified = _classify_exception(exc)
            attempt = _attempt(
                provider,
                symbol,
                market,
                classified.status,
                classified.message,
                retryable=classified.retryable,
                fallback_available=next_provider is not None,
                next_provider=next_provider,
                latency_ms=latency_ms,
                error_type=classified.error_type,
            )
            attempts.append(attempt)
            _record_provider_log(attempt, fallback_used=next_provider is not None, success_provider=None)
            continue

    return _fetch_market_fallback_for_symbol(entity, symbol, market, attempts)
