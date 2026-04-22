from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import httpx
import pdfplumber

from app.config import get_settings
from app.models.source import Source

_FINANCIAL_KEYWORDS = [
    "营业收入",
    "营收",
    "净利润",
    "毛利率",
    "经营活动",
    "现金流",
    "资产负债",
    "总资产",
    "总负债",
    "Revenue",
    "Net income",
    "Gross margin",
    "Cash flow",
    "Operating cash",
    "Total assets",
    "Total liabilities",
]

_START_MARKERS = [
    "主要会计数据",
    "营业收入",
    "净利润",
    "经营活动产生的现金流量净额",
    "资产负债表",
    "利润表",
    "现金流量表",
    "毛利率",
    "研发投入",
    "产能利用率",
]

_LOW_VALUE_PAGE_TOKENS = [
    "目录",
    "释义",
    "董事长致辞",
    "重要提示",
    "签字",
    "公司简介",
    "联系方式",
    "备查文件",
]

_HIGH_VALUE_PAGE_TOKENS = [
    "同比",
    "同比增减",
    "营业收入",
    "归属于上市公司股东的净利润",
    "经营活动产生的现金流量净额",
    "资产负债率",
    "流动比率",
    "毛利率",
    "研发投入",
    "现金流量表",
    "利润表",
]


def _cache_path(url: str) -> Path:
    settings = get_settings()
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
    cache_dir = Path(settings.pdf_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}.pdf"


def _download_pdf(url: str) -> bytes:
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()

    settings = get_settings()
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=settings.pdf_download_timeout_seconds,
        headers={"User-Agent": "research-agent/0.1"},
    )
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF") and b"%PDF" not in content[:1024]:
        raise ValueError("downloaded content is not a PDF")
    path.write_bytes(content)
    return content


def _clean_pdf_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"([。！？；])", r"\1 ", text)
    return text.strip()


def _page_markers(text: str) -> list[str]:
    return [marker for marker in _START_MARKERS if marker in text]


def _score_pdf_page(text: str, page_number: int) -> dict:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return {
            "page_number": page_number,
            "page_score": 0.0,
            "page_type": "empty",
            "markers": [],
            "excerpt": "",
        }

    markers = _page_markers(compact)
    number_count = len(re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", compact))
    percent_count = len(re.findall(r"\d+(?:\.\d+)?%", compact))
    high_hits = sum(1 for token in _HIGH_VALUE_PAGE_TOKENS if token in compact)
    low_hits = sum(1 for token in _LOW_VALUE_PAGE_TOKENS if token in compact[:1200])
    score = min(number_count, 45) * 0.012 + min(percent_count, 12) * 0.025 + high_hits * 0.12 + len(markers) * 0.16
    score -= low_hits * 0.16
    if len(compact) < 80:
        score -= 0.18
    page_type = "financial" if score >= 0.42 or markers else "low_value" if low_hits else "general"
    return {
        "page_number": page_number,
        "page_score": max(0.0, min(1.0, round(score, 3))),
        "page_type": page_type,
        "markers": markers,
        "excerpt": compact[:260],
    }


def _select_high_value_pages(page_records: list[dict], max_pages: int) -> list[int]:
    if not page_records:
        return []
    first_marker = next(
        (record["index"] for record in page_records if record["meta"]["markers"]),
        None,
    )
    seed_indices: set[int] = set()
    if first_marker is not None:
        for index in range(max(0, first_marker - 2), min(len(page_records), first_marker + max_pages)):
            seed_indices.add(index)

    ranked = sorted(
        page_records,
        key=lambda record: (record["meta"]["page_score"], bool(record["meta"]["markers"]), -record["index"]),
        reverse=True,
    )
    selected = set(seed_indices)
    for record in ranked:
        if len(selected) >= max_pages:
            break
        if record["meta"]["page_score"] <= 0 and selected:
            continue
        selected.add(record["index"])
    if not selected:
        selected = {record["index"] for record in page_records[:max_pages]}
    selected_records = [record for record in page_records if record["index"] in selected]
    selected_records = sorted(
        selected_records,
        key=lambda record: (record["meta"]["page_score"], bool(record["meta"]["markers"]), -record["index"]),
        reverse=True,
    )[:max_pages]
    return sorted(record["index"] for record in selected_records)


def _extract_table_like_rows(text: str, limit: int = 12) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if len(compact) < 12:
            continue
        numbers = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", compact)
        if len(numbers) < 2:
            continue
        if not any(token in compact for token in ["收入", "利润", "现金流", "资产", "负债", "毛利", "Revenue", "income", "cash"]):
            continue
        rows.append({"raw": compact, "numbers": numbers[:8]})
        if len(rows) >= limit:
            break
    return rows


def extract_financial_rows(tables: list[list[list[str | None]]], limit: int = 24) -> list[dict]:
    rows: list[dict] = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [str(cell).strip() if cell is not None else "" for cell in table[0]]
        for row in table[1:]:
            cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
            row_text = " ".join(cell for cell in cleaned_row if cell)
            if not row_text:
                continue
            if any(keyword.lower() in row_text.lower() for keyword in _FINANCIAL_KEYWORDS):
                rows.append(
                    {
                        "header": header,
                        "row": cleaned_row,
                        "raw": row_text,
                    }
                )
                if len(rows) >= limit:
                    return rows
    return rows


def parse_pdf_source(source: Source) -> Source:
    """Download and parse a PDF source using pdfplumber.

    The parser extracts readable text and real table structures where available.
    It still avoids claiming OCR or full financial-statement reconstruction.
    """

    if not source.url or not source.is_pdf:
        return source.model_copy(update={"pdf_parse_status": "not_pdf"})

    try:
        raw = _download_pdf(source.url)
        page_texts: list[str] = []
        tables: list[list[list[str | None]]] = []
        parsed_pages: list[dict] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            settings = get_settings()
            scan_limit = min(len(pdf.pages), max(50, settings.pdf_max_pages))
            page_records: list[dict] = []
            for index, page in enumerate(pdf.pages[:scan_limit]):
                text = page.extract_text() or ""
                meta = _score_pdf_page(text, index + 1)
                page_records.append({"index": index, "text": text, "meta": meta})

            selected_indices = _select_high_value_pages(page_records, settings.pdf_max_pages)
            for index in selected_indices:
                record = page_records[index]
                page = pdf.pages[index]
                text = record["text"]
                if text.strip():
                    page_texts.append(text)
                    parsed_pages.append(record["meta"])
                try:
                    for table in page.extract_tables() or []:
                        if table and len(table) > 1:
                            tables.append(table)
                except Exception:
                    continue
        parsed_text = _clean_pdf_text("\n".join(page_texts))
        if not parsed_text:
            return source.model_copy(update={"pdf_parse_status": "failed"})
        table_rows = extract_financial_rows(tables)
        if not table_rows:
            table_rows = _extract_table_like_rows("\n".join(page_texts), limit=12)
        merged_content = f"{source.content}\n\nPDF解析正文：{parsed_text}".strip()
        best_page_score = max((page["page_score"] for page in parsed_pages), default=None)
        page_type = "financial_pages" if any(page["page_type"] == "financial" for page in parsed_pages) else "general_pages"
        return source.model_copy(
            update={
                "fetched_content": parsed_text,
                "enriched_content": merged_content,
                "pdf_parse_status": "parsed",
                "parsed_tables": table_rows[:12],
                "parsed_pages": parsed_pages[: get_settings().pdf_max_pages],
                "page_score": best_page_score,
                "page_type": page_type,
            }
        )
    except Exception:
        return source.model_copy(update={"pdf_parse_status": "failed"})


def enrich_pdf_sources(sources: list[Source]) -> list[Source]:
    """Parse PDF sources where possible and preserve non-PDF sources unchanged."""

    return [parse_pdf_source(source) if source.is_pdf else source for source in sources]
