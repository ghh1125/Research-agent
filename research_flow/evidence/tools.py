from __future__ import annotations

import csv
import json
import math
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from research_flow.schema import DataArtifact, ResearchPlan, ResearchTask
from research_flow.settings import RuntimeSettings, get_settings


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


class DataToolProvider(Protocol):
    category: str

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        ...


def _subject(task: ResearchTask) -> str:
    return task.symbols[0] if task.symbols else task.entity or task.raw_query


def _clean_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]", "", symbol).upper()


def _json_request(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _text_table(name: str, obj) -> str:
    if obj is None:
        return ""
    try:
        if hasattr(obj, "tail"):
            obj = obj.tail(6)
        if hasattr(obj, "to_csv"):
            return f"## {name}\n{obj.to_csv()}"
    except Exception:
        return ""
    return f"## {name}\n{obj}"


# ---------------------------------------------------------------------------
# Technical indicator helpers (pure Python, no extra deps)
# ---------------------------------------------------------------------------

def _rsi14(closes: list[float]) -> float:
    period = 14
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [max(d, 0.0) for d in recent]
    losses = [abs(min(d, 0.0)) for d in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_indicators(closes: list[float]) -> dict[str, float]:
    if not closes:
        return {}
    result: dict[str, float] = {}
    current = closes[-1]
    result["current_price"] = current
    if len(closes) >= 20:
        result["ma20"] = round(sum(closes[-20:]) / 20, 4)
    if len(closes) >= 60:
        result["ma60"] = round(sum(closes[-60:]) / 60, 4)
    if "ma20" in result and result["ma20"] != 0:
        result["price_vs_ma20_pct"] = round((current / result["ma20"] - 1) * 100, 2)
    if "ma60" in result and result["ma60"] != 0:
        result["price_vs_ma60_pct"] = round((current / result["ma60"] - 1) * 100, 2)
    window = closes[-252:] if len(closes) >= 252 else closes
    hi, lo = max(window), min(window)
    result["52w_high"] = hi
    result["52w_low"] = lo
    if hi != lo:
        result["52w_position_pct"] = round((current - lo) / (hi - lo) * 100, 2)
    if len(closes) >= 15:
        result["rsi14"] = round(_rsi14(closes), 2)
    return result


def _indicators_text(indicators: dict[str, float]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in indicators.items())


def _parse_close_series(csv_text: str) -> list[float]:
    closes: list[float] = []
    try:
        reader = csv.DictReader(csv_text.splitlines())
        for row in reader:
            raw = row.get("Close") or row.get("close")
            if raw:
                try:
                    closes.append(float(raw))
                except ValueError:
                    pass
    except Exception:
        pass
    return closes


# ---------------------------------------------------------------------------
# A-share helpers
# ---------------------------------------------------------------------------

def _is_a_share(task: ResearchTask) -> bool:
    return "A_share" in task.market or any(s.upper().endswith((".SZ", ".SH")) for s in task.symbols)


def _a_share_code(task: ResearchTask) -> str | None:
    for sym in task.symbols:
        clean = re.sub(r"\.(SZ|SH)$", "", sym.upper(), flags=re.IGNORECASE)
        if clean.isdigit() and len(clean) == 6:
            return clean
    candidate = re.search(r"\b(\d{6})\b", task.raw_query)
    if candidate:
        return candidate.group(1)
    return None


# ---------------------------------------------------------------------------
# Tool providers
# ---------------------------------------------------------------------------

@dataclass
class YFinanceMarketDataTool:
    category: str = "market_data"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        symbol = _clean_symbol(_subject(task))
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("yfinance is required for native market_data.") from exc

        end = date.today()
        start = end - timedelta(days=370)
        ticker = yf.Ticker(symbol)
        history = ticker.history(start=start.isoformat(), end=end.isoformat())
        fast_info = getattr(ticker, "fast_info", None)

        # Compute technical indicators from price history
        indicators_section = ""
        if history is not None and not history.empty:
            closes = history["Close"].dropna().tolist()
            indicators = _compute_indicators(closes)
            if indicators:
                indicators_section = f"\n## technical_indicators\n{_indicators_text(indicators)}"

        content = "\n".join(
            part
            for part in [
                f"symbol={symbol}",
                f"fast_info={dict(fast_info) if fast_info else {}}",
                _text_table("price_history", history),
            ]
            if part
        ) + indicators_section

        if not content.strip():
            return []
        return [
            DataArtifact(
                id="market_data_native_1",
                category="market_data",
                title=f"{symbol} yfinance price history",
                source_type="market_data",
                provider="yfinance",
                url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}",
                content=content,
                metadata={"symbol": symbol, "official": False},
            )
        ]


@dataclass
class YFinanceFinancialStatementsTool:
    category: str = "financial_statements"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        symbol = _clean_symbol(_subject(task))
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("yfinance is required for native financial_statements.") from exc

        ticker = yf.Ticker(symbol)
        parts = [
            _text_table("income_statement", getattr(ticker, "financials", None)),
            _text_table("balance_sheet", getattr(ticker, "balance_sheet", None)),
            _text_table("cashflow", getattr(ticker, "cashflow", None)),
        ]
        content = "\n\n".join(part for part in parts if part)
        if not content.strip():
            return []
        return [
            DataArtifact(
                id="financial_statements_native_1",
                category="financial_statements",
                title=f"{symbol} yfinance financial statements",
                source_type="financial_statements",
                provider="yfinance",
                url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}/financials",
                content=content,
                metadata={"symbol": symbol, "official": False},
            )
        ]


@dataclass
class YFinanceValuationTool:
    """Fetches analyst-facing valuation metrics (PE, EPS, target price) from yfinance ticker.info."""

    category: str = "valuation"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        symbol = _clean_symbol(_subject(task))
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info
        except Exception:
            return []

        val_keys = [
            "trailingPE", "forwardPE", "trailingEps", "forwardEps",
            "priceToBook", "bookValue", "priceToSalesTrailingI2Months",
            "enterpriseToEbitda", "enterpriseToRevenue", "pegRatio",
            "targetMeanPrice", "targetHighPrice", "targetLowPrice",
            "recommendationMean", "numberOfAnalystOpinions",
            "revenuePerShare", "earningsGrowth", "revenueGrowth",
        ]
        val_data = {k: v for k, v in info.items() if k in val_keys and isinstance(v, (int, float))}
        if not val_data:
            return []

        content = f"symbol={symbol}\n## valuation_metrics\n{json.dumps(val_data, ensure_ascii=False)}"
        return [
            DataArtifact(
                id="valuation_yfinance_1",
                category="valuation",
                title=f"{symbol} yfinance valuation metrics",
                source_type="valuation",
                provider="yfinance",
                url=f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}",
                content=content,
                metadata={"symbol": symbol, "official": False},
            )
        ]


@dataclass
class AKShareMarketDataTool:
    """A-share price history via akshare (optional dependency)."""

    category: str = "market_data"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        if not _is_a_share(task):
            return []
        try:
            import akshare as ak  # type: ignore[import]
        except ImportError:
            return []
        code = _a_share_code(task)
        if not code:
            return []
        try:
            end_str = date.today().strftime("%Y%m%d")
            start_str = (date.today() - timedelta(days=370)).strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_str, end_date=end_str, adjust="hfq")
            if df is None or df.empty:
                return []
            csv_text = df.tail(60).to_csv()
            closes = _parse_close_series(csv_text)
            indicators = _compute_indicators(closes)
            indicators_section = f"\n## technical_indicators\n{_indicators_text(indicators)}" if indicators else ""
            content = f"symbol={code}\n## price_history_a_share\n{csv_text}{indicators_section}"
            return [
                DataArtifact(
                    id="market_data_akshare_1",
                    category="market_data",
                    title=f"{code} A-share price history",
                    source_type="market_data",
                    provider="akshare",
                    url=f"https://finance.sina.com.cn/realstock/company/sh{code}/nc.shtml",
                    content=content,
                    metadata={"symbol": code, "official": False},
                )
            ]
        except Exception:
            return []


@dataclass
class AKShareFinancialStatementsTool:
    """A-share financial statements via akshare (optional dependency)."""

    category: str = "financial_statements"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        if not _is_a_share(task):
            return []
        try:
            import akshare as ak  # type: ignore[import]
        except ImportError:
            return []
        code = _a_share_code(task)
        if not code:
            return []
        parts: list[str] = []
        for func_name, label in [
            ("stock_profit_sheet_by_annual_em", "利润表"),
            ("stock_balance_sheet_by_annual_em", "资产负债表"),
            ("stock_cash_flow_sheet_by_annual_em", "现金流量表"),
        ]:
            try:
                func = getattr(ak, func_name, None)
                if func is None:
                    continue
                df = func(symbol=code)
                if df is not None and not df.empty:
                    parts.append(f"## {label}\n{df.head(6).to_csv()}")
            except Exception:
                continue
        if not parts:
            return []
        return [
            DataArtifact(
                id="financial_statements_akshare_1",
                category="financial_statements",
                title=f"{code} A-share financial statements",
                source_type="financial_statements",
                provider="akshare",
                url=f"https://data.eastmoney.com/bbsj/stock{code}.html",
                content="\n\n".join(parts),
                metadata={"symbol": code, "official": True},
            )
        ]


@dataclass
class SECFilingsTool:
    settings: RuntimeSettings | None = None
    category: str = "filings"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        if "US" not in task.market and not any(symbol.isalpha() for symbol in task.symbols):
            return []
        settings = self.settings or get_settings()
        symbol = _clean_symbol(_subject(task)).replace(".", "-")
        headers = {
            "User-Agent": settings.sec_user_agent_email or "research-agent@example.com",
            "Accept-Encoding": "gzip, deflate",
        }
        mapping = _json_request("https://www.sec.gov/files/company_tickers.json", headers=headers)
        cik = None
        company = symbol
        for item in mapping.values():
            if item.get("ticker", "").upper() == symbol.upper():
                cik = str(item.get("cik_str", "")).zfill(10)
                company = item.get("title") or company
                break
        if not cik:
            return []
        facts = _json_request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=headers)
        submissions = _json_request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers)
        recent = submissions.get("filings", {}).get("recent", {})
        recent_rows = []
        for idx, form in enumerate(recent.get("form", [])[:20]):
            recent_rows.append(
                {
                    "form": form,
                    "filingDate": recent.get("filingDate", [None] * 20)[idx],
                    "accessionNumber": recent.get("accessionNumber", [None] * 20)[idx],
                    "primaryDocument": recent.get("primaryDocument", [None] * 20)[idx],
                }
            )
        content = json.dumps(
            {
                "company": company,
                "cik": cik,
                "recent_filings": recent_rows,
                "companyfacts": facts,
            },
            ensure_ascii=False,
        )[:30000]
        return [
            DataArtifact(
                id="filings_sec_1",
                category="filings",
                title=f"{company} SEC filings and company facts",
                source_type="sec_filings",
                provider="sec",
                url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                content=content,
                metadata={"symbol": symbol, "cik": cik, "official": True},
            )
        ]


@dataclass
class CNInfoFilingsTool:
    category: str = "filings"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        if "A_share" not in task.market and not any(symbol.endswith((".SZ", ".SH")) for symbol in task.symbols):
            return []
        symbol = re.sub(r"\D", "", _subject(task))
        if len(symbol) != 6:
            return []
        org_id = self._org_id(symbol)
        if not org_id:
            return []
        column = "szse" if symbol.startswith(("000", "002", "300")) else "sse"
        plate = "sz" if column == "szse" else "sh"
        payload = urllib.parse.urlencode(
            {
                "pageNum": "1",
                "pageSize": "10",
                "column": column,
                "tabName": "fulltext",
                "plate": plate,
                "stock": f"{symbol},{org_id}",
                "category": "category_ndbg_szsh;category_bndbg_szsh;category_sjdbg_szsh;",
                "seDate": "",
                "isHLtitle": "true",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=payload,
            method="POST",
            headers=self._headers(),
        )
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
        announcements = data.get("announcements") or []
        content = json.dumps(announcements[:10], ensure_ascii=False)
        return [
            DataArtifact(
                id="filings_cninfo_1",
                category="filings",
                title=f"{symbol} CNINFO filings",
                source_type="a_share_filings",
                provider="cninfo",
                url="http://www.cninfo.com.cn/new/disclosure",
                content=content,
                metadata={"symbol": symbol, "org_id": org_id, "official": True},
            )
        ] if announcements else []

    def _org_id(self, symbol: str) -> str | None:
        payload = urllib.parse.urlencode({"keyWord": symbol}).encode("utf-8")
        req = urllib.request.Request(
            "http://www.cninfo.com.cn/new/information/topSearch/query",
            data=payload,
            method="POST",
            headers=self._headers(),
        )
        with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310
            rows = json.loads(response.read().decode("utf-8"))
        for row in rows or []:
            if row.get("code") == symbol:
                return row.get("orgId")
        return rows[0].get("orgId") if rows else None

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 research-agent/1.0",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "http://www.cninfo.com.cn",
            "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastPage=index",
            "X-Requested-With": "XMLHttpRequest",
        }


@dataclass
class HKEXFilingsTool:
    """Hong Kong Exchange filings via HKEX disclosure search API."""

    category: str = "filings"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        if "HK" not in task.market and not any(s.upper().endswith(".HK") for s in task.symbols):
            return []
        symbol = _subject(task)
        code_raw = re.sub(r"\.HK$", "", symbol.upper(), flags=re.IGNORECASE)
        if not re.match(r"^\d+$", code_raw):
            return []
        code = code_raw.zfill(5)
        try:
            payload = json.dumps({
                "searchAll": False,
                "listingType": 0,
                "code": code,
                "market": "MAIN",
                "category": "0",
                "selDepth": 0,
                "tier": "",
                "from": 0,
                "size": 10,
                "lang": "SC",
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://www1.hkexnews.hk/search/getTitleSummary.do",
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 research-agent/1.0",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
                    "Origin": "https://www1.hkexnews.hk",
                },
            )
            with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
            tables = data.get("tables") or []
            records = tables[0].get("records", []) if tables else []
            if not records:
                return []
            content = json.dumps(records[:10], ensure_ascii=False)
            return [
                DataArtifact(
                    id="filings_hkex_1",
                    category="filings",
                    title=f"{code} HKEX filings",
                    source_type="hk_filings",
                    provider="hkex",
                    url=f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=ZH&stock={code}",
                    content=content,
                    metadata={"symbol": symbol, "code": code, "official": True},
                )
            ]
        except Exception:
            return []


def default_tool_providers(settings: RuntimeSettings | None = None) -> list[DataToolProvider]:
    settings = settings or get_settings()
    return [
        YFinanceMarketDataTool(),
        YFinanceFinancialStatementsTool(),
        YFinanceValuationTool(),
        AKShareMarketDataTool(),
        AKShareFinancialStatementsTool(),
        SECFilingsTool(settings),
        CNInfoFilingsTool(),
        HKEXFilingsTool(),
    ]
