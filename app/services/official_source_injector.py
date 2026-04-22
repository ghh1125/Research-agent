from __future__ import annotations

from app.models.question import Question
from app.models.source import Source, SourceTier
from app.models.topic import Topic
from app.services.listing_status_service import is_listed_company

CNINFO_ANNOUNCEMENT_API = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_BASE = "http://static.cninfo.com.cn/"
CNINFO_STOCK_PAGE_TEMPLATE = "http://www.cninfo.com.cn/new/disclosure/stock?stockCode={stock_code}&orgId={org_id}"
SSE_SEARCH_TEMPLATE = (
    "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
    "?productId={stock_code}"
)

A_STOCK_SYMBOL_MAP: dict[str, str] = {
    "宁德时代": "300750",
    "横店东磁": "002056",
    "比亚迪": "002594",
    "贵州茅台": "600519",
    "中国平安": "601318",
    "招商银行": "600036",
    "工商银行": "601398",
    "万科": "000002",
    "格力电器": "000651",
    "美的集团": "000333",
    "隆基绿能": "601012",
    "通威股份": "600438",
    "阳光电源": "300274",
    "亿纬锂能": "300014",
    "天齐锂业": "002466",
}

CNINFO_ORG_MAP: dict[str, str] = {
    "300750": "9900016654",
    "002056": "9900003935",
    "002594": "9900001654",
}


def get_stock_code(topic: Topic) -> str | None:
    if topic.entity and topic.entity in A_STOCK_SYMBOL_MAP:
        return A_STOCK_SYMBOL_MAP[topic.entity]
    symbol = getattr(topic, "symbol", None)
    if symbol:
        raw = symbol.replace(".SZ", "").replace(".SH", "")
        if raw.isdigit() and len(raw) == 6:
            return raw
    return None


def build_cninfo_urls(stock_code: str, entity: str) -> list[str]:
    urls = []
    org_id = CNINFO_ORG_MAP.get(stock_code)
    if org_id:
        urls.append(CNINFO_STOCK_PAGE_TEMPLATE.format(stock_code=stock_code, org_id=org_id))
    if stock_code.startswith("6"):
        urls.append(SSE_SEARCH_TEMPLATE.format(stock_code=stock_code))
    return urls


def discover_cninfo_announcements(stock_code: str, entity: str, limit: int = 3) -> list[dict]:
    """Discover recent official CNINFO announcement PDFs when the endpoint is reachable."""

    try:
        import httpx

        response = httpx.post(
            CNINFO_ANNOUNCEMENT_API,
            data={
                "stock": stock_code,
                "searchkey": f"{entity} 年报 季报",
                "category": "",
                "pageNum": "1",
                "pageSize": str(max(limit, 3)),
                "column": "szse",
                "tabName": "fulltext",
            },
            headers={
                "User-Agent": "Mozilla/5.0 research-agent/0.1",
                "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    announcements: list[dict] = []
    for item in payload.get("announcements", []) or []:
        adjunct_url = item.get("adjunctUrl")
        title = item.get("announcementTitle") or item.get("secName") or f"{entity} 官方公告"
        if not adjunct_url:
            continue
        if not any(token in title for token in ["年报", "年度报告", "季报", "季度报告", "财务", "审计"]):
            continue
        announcements.append(
            {
                "title": f"{entity}官方披露：{title}",
                "url": f"{CNINFO_STATIC_BASE}{adjunct_url.lstrip('/')}",
                "published_at": item.get("announcementTime"),
            }
        )
        if len(announcements) >= limit:
            break
    return announcements


def inject_official_sources(topic: Topic, questions: list[Question]) -> list[Source]:
    """Inject official disclosure PDFs where possible; fallback entries are discovery only."""

    if not is_listed_company(topic):
        return []
    stock_code = get_stock_code(topic)
    if not stock_code:
        return []
    entity = topic.entity or topic.topic
    question_id = next(
        (question.id for question in questions if question.framework_type in {"financial", "credit"}),
        questions[0].id if questions else "q_official",
    )
    sources: list[Source] = []
    announcements = discover_cninfo_announcements(stock_code, entity)
    for index, item in enumerate(announcements, start=1):
        sources.append(
            Source(
                id=f"official_{index}",
                question_id=question_id,
                flow_type="fact",
                search_query=f"{entity} 年报 季报 官方公告",
                title=item["title"],
                url=item["url"],
                source_type="regulatory",
                provider="official_injected",
                source_origin_type="official_disclosure",
                credibility_tier="tier1",
                tier=SourceTier.TIER1,
                source_score=0.95,
                source_rank_reason="official_pdf_discovered_from_cninfo",
                contains_entity=True,
                is_recent=True,
                is_pdf=True,
                pdf_parse_status="not_attempted",
                published_at=str(item.get("published_at")) if item.get("published_at") else None,
                content=f"{entity}官方公告PDF，股票代码{stock_code}，标题：{item['title']}。",
            )
        )
    if sources:
        return sources

    for index, url in enumerate(build_cninfo_urls(stock_code, entity), start=1):
        sources.append(
            Source(
                id=f"official_discovery_{index}",
                question_id=question_id,
                flow_type="fact",
                search_query=f"{entity} 官方公告发现入口",
                title=f"{entity} 官方公告发现入口 - 巨潮资讯/交易所",
                url=url,
                source_type="regulatory",
                provider="official_discovery",
                source_origin_type="regulatory",
                credibility_tier="tier2",
                tier=SourceTier.TIER2,
                source_score=0.55,
                source_rank_reason="official_discovery_entry_not_primary_filing",
                contains_entity=True,
                is_recent=True,
                is_pdf=False,
                pdf_parse_status="not_pdf",
                content=f"{entity}官方公告发现入口，股票代码{stock_code}，用于发现年报、季报和交易所公告；该入口本身不作为实质证据。",
            )
        )
    return sources
