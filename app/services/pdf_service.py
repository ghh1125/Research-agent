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

HEADER_FOOTER_PATTERNS = [
    r"^第\s*\d+\s*页$",
    r"^\d+\s*/\s*\d+$",
    r"^\d+$",
    r"年度报告全文",
    r"目录",
    r"章节",
    r"联系电话",
    r"公司网址",
    r"传真",
    r"邮箱",
    r"法律声明",
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

_PAGE_TYPE_MARKERS = {
    "balance_sheet": ["资产负债表", "总资产", "总负债", "货币资金"],
    "income_statement": ["利润表", "营业收入", "营业成本", "净利润"],
    "cashflow_statement": ["现金流量表", "经营活动产生的现金流量净额", "投资活动现金流"],
    "financial_summary": ["主要会计数据", "营业收入", "净利润", "毛利率"],
    "toc": ["目录", "第一节", "释义", "公司简介"],
}

_STRUCTURED_METRIC_PATTERNS = [
    (
        "revenue",
        "营业收入",
        re.compile(r"(营业收入|营业总收入)[^\d\-+]{0,20}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*亿元|\s*万元|\s*元|%)?"),
        1.0,
    ),
    (
        "net_income_attributable",
        "归母净利润",
        re.compile(r"(归属于上市公司股东的净利润|归母净利润|净利润)[^\d\-+]{0,20}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*亿元|\s*万元|\s*元|%)?"),
        1.0,
    ),
    (
        "gross_margin",
        "毛利率",
        re.compile(r"(毛利率|Gross margin)[^\d\-+]{0,20}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*%|个百分点)?", re.IGNORECASE),
        0.95,
    ),
    (
        "operating_cash_flow",
        "经营现金流",
        re.compile(r"(经营活动产生的现金流量净额|经营活动现金流量净额|Operating cash flow)[^\d\-+]{0,24}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*亿元|\s*万元|\s*元|%)?", re.IGNORECASE),
        0.95,
    ),
    (
        "capex",
        "资本开支",
        re.compile(r"(购建固定资产、无形资产和其他长期资产支付的现金|资本开支|CAPEX|capital expenditure)[^\d\-+]{0,28}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*亿元|\s*万元|\s*元|%)?", re.IGNORECASE),
        0.9,
    ),
    (
        "asset_liability_ratio",
        "资产负债率",
        re.compile(r"(资产负债率)[^\d\-+]{0,20}([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(\s*%|个百分点)?"),
        0.9,
    ),
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


def classify_pdf_page(text: str) -> str:
    compact = re.sub(r"\s+", " ", text or "")
    if not compact.strip():
        return "empty"
    if all(token in compact for token in ["目录", "第一节"]) or compact.strip().startswith("目录"):
        return "toc"
    if "主要会计数据" in compact:
        return "financial_summary"
    for page_type, markers in _PAGE_TYPE_MARKERS.items():
        if page_type in {"toc", "financial_summary"}:
            continue
        hits = sum(1 for marker in markers if marker in compact)
        if hits >= 2:
            return page_type
    low_hits = sum(1 for token in _LOW_VALUE_PAGE_TOKENS if token in compact[:1200])
    if low_hits:
        return "low_value"
    high_hits = sum(1 for token in _HIGH_VALUE_PAGE_TOKENS if token in compact)
    return "financial" if high_hits >= 2 else "general"


def _normalize_noise_line(line: str) -> str:
    return re.sub(r"\s+", " ", line or "").strip()


def _is_noise_line(line: str, repeated_lines: set[str] | None = None) -> bool:
    normalized = _normalize_noise_line(line)
    if not normalized:
        return True
    if repeated_lines and normalized in repeated_lines:
        return True
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in HEADER_FOOTER_PATTERNS)


def detect_repeated_headers_footers(page_texts: list[str], min_repeats: int = 2) -> list[str]:
    counts: dict[str, int] = {}
    for text in page_texts:
        candidates = [line for line in (text or "").splitlines() if _normalize_noise_line(line)]
        edge_lines = candidates[:3] + candidates[-3:]
        for line in set(edge_lines):
            normalized = _normalize_noise_line(line)
            if len(normalized) < 4:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    return sorted([line for line, count in counts.items() if count >= min_repeats])


def remove_pdf_noise_lines(text: str, repeated_lines: list[str] | None = None) -> str:
    repeated = set(repeated_lines or [])
    lines = [
        _normalize_noise_line(line)
        for line in (text or "").splitlines()
        if not _is_noise_line(line, repeated)
    ]
    return "\n".join(line for line in lines if line)


def _parse_numeric_value(value: str) -> float | None:
    try:
        return round(float(value.replace(",", "")), 4)
    except Exception:
        return None


def _is_truncated_metric_fragment(raw_number: str, unit: str | None, metric_name: str) -> bool:
    digits = re.sub(r"\D", "", raw_number or "")
    normalized_unit = (unit or "").strip()
    if metric_name in {"gross_margin", "asset_liability_ratio"}:
        return "%" not in normalized_unit and len(digits) <= 2
    return not normalized_unit and len(digits) <= 2


def _metric_source_text(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 30)
    end = min(len(text), match.end() + 55)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def extract_structured_pdf_metrics(text: str, table_rows: list[dict] | None = None, page_number: int | None = None) -> list[dict]:
    """Extract normalized financial metrics from annual-report text.

    This is intentionally conservative: short number fragments are retained for audit,
    but marked as non-summary evidence so they cannot dominate the conclusion layer.
    """

    combined = text or ""
    if table_rows:
        combined = "\n".join([combined, *[str(row.get("raw") or " ".join(row.get("row", []))) for row in table_rows]])
    metrics: list[dict] = []
    seen: set[tuple[str, float | None, str]] = set()
    for metric_name, display_name, pattern, base_weight in _STRUCTURED_METRIC_PATTERNS:
        for match in pattern.finditer(combined):
            raw_number = match.group(2)
            raw_unit = (match.group(3) or "").strip()
            value = _parse_numeric_value(raw_number)
            if value is None:
                continue
            unit = raw_unit or None
            if unit == "个百分点":
                unit = "pct"
            key = (metric_name, value, unit or "")
            if key in seen:
                continue
            seen.add(key)
            is_truncated = _is_truncated_metric_fragment(raw_number, raw_unit, metric_name)
            metrics.append(
                {
                    "metric_name": metric_name,
                    "display_name": display_name,
                    "value": value,
                    "unit": unit,
                    "raw_text": _metric_source_text(combined, match),
                    "page_number": page_number,
                    "is_truncated": is_truncated,
                    "can_enter_summary": not is_truncated,
                    "weight": round(base_weight * (0.3 if is_truncated else 1.0), 3),
                }
            )
    metrics.sort(key=lambda item: (item["can_enter_summary"], item["weight"]), reverse=True)
    return metrics


def needs_ocr_fallback(text: str, image_count: int = 0, page_score: float | None = None) -> bool:
    compact_len = len(re.sub(r"\s+", "", text or ""))
    return image_count > 0 and compact_len < 40 and (page_score is None or page_score >= 0.35)


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
    classified_type = classify_pdf_page(compact)
    if classified_type in {"financial_summary", "income_statement", "balance_sheet", "cashflow_statement"}:
        page_type = "financial"
    else:
        page_type = classified_type if classified_type not in {"general"} else "financial" if score >= 0.42 or markers else "general"
    return {
        "page_number": page_number,
        "page_score": max(0.0, min(1.0, round(score, 3))),
        "page_type": page_type,
        "page_subtype": classified_type,
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
                image_count = len(getattr(page, "images", []) or [])
                meta["image_count"] = image_count
                meta["ocr_required"] = needs_ocr_fallback(text, image_count=image_count, page_score=meta["page_score"])
                page_records.append({"index": index, "text": text, "meta": meta})

            selected_indices = _select_high_value_pages(page_records, settings.pdf_max_pages)
            selected_raw_texts = [page_records[index]["text"] for index in selected_indices]
            repeated_noise = detect_repeated_headers_footers(selected_raw_texts)
            for index in selected_indices:
                record = page_records[index]
                page = pdf.pages[index]
                text = remove_pdf_noise_lines(record["text"], repeated_noise)
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
        structured_metrics = extract_structured_pdf_metrics("\n".join(page_texts), table_rows=table_rows)
        merged_content = f"{source.content}\n\nPDF解析正文：{parsed_text}".strip()
        best_page_score = max((page["page_score"] for page in parsed_pages), default=None)
        page_type = "financial_pages" if any(
            page["page_type"] in {"financial", "financial_summary", "income_statement", "balance_sheet", "cashflow_statement"}
            for page in parsed_pages
        ) else "general_pages"
        return source.model_copy(
            update={
                "fetched_content": parsed_text,
                "enriched_content": merged_content,
                "pdf_parse_status": "parsed",
                "parsed_tables": table_rows[:12],
                "parsed_pages": parsed_pages[: get_settings().pdf_max_pages],
                "structured_metrics": structured_metrics[:24],
                "ocr_required": any(page.get("ocr_required") for page in parsed_pages),
                "page_score": best_page_score,
                "page_type": page_type,
            }
        )
    except Exception:
        return source.model_copy(update={"pdf_parse_status": "failed"})


def enrich_pdf_sources(sources: list[Source]) -> list[Source]:
    """Parse PDF sources where possible and preserve non-PDF sources unchanged."""

    return [parse_pdf_source(source) if source.is_pdf else source for source in sources]
