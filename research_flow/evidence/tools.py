from __future__ import annotations

import json
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
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:  # noqa: S310 - user-requested market research source
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


@dataclass
class YFinanceMarketDataTool:
    category: str = "market_data"

    def collect(self, task: ResearchTask, plan: ResearchPlan) -> list[DataArtifact]:
        symbol = _clean_symbol(_subject(task))
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("yfinance is required for native market_data. Install yfinance or configure search API.") from exc

        end = date.today()
        start = end - timedelta(days=370)
        ticker = yf.Ticker(symbol)
        history = ticker.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
        info = getattr(ticker, "fast_info", None)
        content = "\n".join(
            part
            for part in [
                f"symbol={symbol}",
                f"fast_info={dict(info) if info else {}}",
                _text_table("price_history", history),
            ]
            if part
        )
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
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("yfinance is required for native financial_statements. Install yfinance or configure search API.") from exc

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
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 - public filing endpoint
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
        with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310 - public filing endpoint
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


def default_tool_providers(settings: RuntimeSettings | None = None) -> list[DataToolProvider]:
    settings = settings or get_settings()
    return [
        YFinanceMarketDataTool(),
        YFinanceFinancialStatementsTool(),
        SECFilingsTool(settings),
        CNInfoFilingsTool(),
    ]
