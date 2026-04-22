from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ListingStatus = Literal["listed", "private", "unlisted", "not_applicable", "concept", "asset", "unknown"]
ResearchObjectType = Literal[
    "listed_company",
    "private_company",
    "industry_theme",
    "credit_issuer",
    "macro_theme",
    "event",
    "concept_theme",
    "fund_etf",
    "commodity",
    "unknown",
]
MarketType = Literal["A_share", "HK", "US", "bond", "private", "thematic", "macro", "commodity", "fund", "other"]

_PRIVATE_COMPANY_ALIASES = {
    "华为": ["华为", "Huawei", "华为技术有限公司", "华为投资控股有限公司"],
    "字节跳动": ["字节跳动", "ByteDance", "抖音集团"],
    "蚂蚁集团": ["蚂蚁集团", "Ant Group"],
    "小红书": ["小红书", "Xiaohongshu"],
}

_LISTED_COMPANY_ALIASES = {
    "拼多多": ["拼多多", "PDD", "PDD Holdings"],
    "阿里巴巴": ["阿里巴巴", "Alibaba", "BABA"],
    "腾讯": ["腾讯", "Tencent"],
    "美团": ["美团"],
    "京东": ["京东", "JD"],
    "百度": ["百度", "Baidu"],
    "网易": ["网易", "NetEase"],
    "宁德时代": ["宁德时代", "CATL"],
    "比亚迪": ["比亚迪", "BYD"],
    "特斯拉": ["特斯拉", "Tesla"],
    "英伟达": ["英伟达", "NVIDIA"],
    "微软": ["微软", "Microsoft"],
    "苹果": ["苹果", "Apple"],
    "AMD": ["AMD", "Advanced Micro Devices"],
    "博通": ["博通", "Broadcom", "AVGO"],
    "摩根大通": ["摩根大通", "JPMorgan", "JPM"],
    "美国银行": ["美国银行", "Bank of America", "BAC"],
}

_A_SHARE_COMPANIES = {"宁德时代"}
_HK_COMPANIES = {"腾讯", "美团", "比亚迪"}
_US_COMPANIES = {"拼多多", "阿里巴巴", "京东", "百度", "网易", "特斯拉", "英伟达", "微软", "苹果", "AMD", "博通", "摩根大通", "美国银行"}

_STOCK_WORDS = ["股票", "股价", "证券", "上市", "ticker", "stock", "shares"]
_CONCEPT_WORDS = ["概念股", "产业链", "供应链", "受益标的", "ETF", "指数"]
_CREDIT_WORDS = ["债", "债券", "城投", "城投债", "发债", "信用", "评级", "偿债", "违约主体"]
_MACRO_WORDS = ["宏观", "利率", "通胀", "降息", "加息", "汇率", "财政", "货币政策", "GDP"]
_EVENT_WORDS = ["事件", "收购", "并购", "制裁", "处罚", "事故", "突发", "重组"]
_COMMODITY_WORDS = ["黄金", "原油", "铜", "铝", "煤炭", "铁矿", "锂", "商品", "资源品"]
_INDUSTRY_WORDS = ["行业", "赛道", "产业", "市场空间", "格局", "AI Agent", "半导体", "SaaS", "银行"]


@dataclass(frozen=True)
class ListingProfile:
    entity: str | None
    listing_status: ListingStatus
    listing_note: str | None = None
    topic_type_override: str | None = None
    research_object_type: ResearchObjectType = "unknown"
    market_type: MarketType = "other"


def _match_alias(text: str, alias_map: dict[str, list[str]]) -> str | None:
    lowered = text.lower()
    for canonical, aliases in alias_map.items():
        if any(alias.lower() in lowered for alias in aliases):
            return canonical
    return None


def normalize_entity_candidate(query: str, candidate: str | None) -> str | None:
    """Normalize entity text so words like 股票 do not become part of the company name."""

    text = " ".join(item for item in [query, candidate or ""] if item)
    private_match = _match_alias(text, _PRIVATE_COMPANY_ALIASES)
    if private_match:
        return private_match
    listed_match = _match_alias(text, _LISTED_COMPANY_ALIASES)
    if listed_match:
        return listed_match
    if not candidate:
        return None
    normalized = candidate
    for word in _STOCK_WORDS:
        normalized = normalized.replace(word, "")
    normalized = normalized.strip("：:，, 的")
    return normalized or candidate


def infer_listing_profile(query: str, entity: str | None) -> ListingProfile:
    """Classify whether the user is asking about a listed stock, private company, concept, or asset."""

    normalized_entity = normalize_entity_candidate(query, entity)
    text = f"{query} {normalized_entity or ''}"
    lowered = query.lower()

    if any(word.lower() in lowered for word in ["etf", "指数", "基金"]):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近 ETF/指数/基金等资产研究路径。",
            topic_type_override="theme",
            research_object_type="fund_etf",
            market_type="fund",
        )
    if any(word in query for word in _CREDIT_WORDS):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近信用主体或债券研究路径，不应进入股票估值流程。",
            topic_type_override="theme",
            research_object_type="credit_issuer",
            market_type="bond",
        )
    if any(word in query for word in _MACRO_WORDS):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近宏观主题研究路径。",
            topic_type_override="theme",
            research_object_type="macro_theme",
            market_type="macro",
        )
    if any(word in query for word in _COMMODITY_WORDS):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近商品或资源品研究路径。",
            topic_type_override="theme",
            research_object_type="commodity",
            market_type="commodity",
        )
    if any(word in query for word in _EVENT_WORDS):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近事件驱动研究路径。",
            topic_type_override="theme",
            research_object_type="event",
            market_type="thematic",
        )
    if any(word in query for word in _CONCEPT_WORDS):
        concept_entity = normalized_entity or _match_alias(text, _PRIVATE_COMPANY_ALIASES)
        return ListingProfile(
            entity=concept_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近概念/产业链研究，不应直接当作单一上市股票估值。",
            topic_type_override="theme",
            research_object_type="concept_theme",
            market_type="thematic",
        )
    if _match_alias(text, _PRIVATE_COMPANY_ALIASES):
        entity_name = _match_alias(text, _PRIVATE_COMPANY_ALIASES)
        return ListingProfile(
            entity=entity_name,
            listing_status="private",
            listing_note=f"{entity_name}未公开上市，不能按公开股票直接生成估值或交易型研究路径。",
            research_object_type="private_company",
            market_type="private",
        )
    listed_entity = _match_alias(text, _LISTED_COMPANY_ALIASES)
    if listed_entity:
        if listed_entity in _A_SHARE_COMPANIES:
            market_type: MarketType = "A_share"
        elif listed_entity in _HK_COMPANIES:
            market_type = "HK"
        elif listed_entity in _US_COMPANIES:
            market_type = "US"
        else:
            market_type = "other"
        return ListingProfile(
            entity=listed_entity,
            listing_status="listed",
            listing_note="已识别为公开上市或可交易主体，可进入股票初筛研究路径。",
            research_object_type="listed_company",
            market_type=market_type,
        )
    if any(word in query for word in _INDUSTRY_WORDS):
        return ListingProfile(
            entity=normalized_entity,
            listing_status="not_applicable",
            listing_note="用户问题更接近行业/赛道主题研究路径，不对应单一股票估值。",
            topic_type_override="theme",
            research_object_type="industry_theme",
            market_type="thematic",
        )
    return ListingProfile(entity=normalized_entity, listing_status="unknown", research_object_type="unknown")


def is_private_or_unlisted(listing_status: str | None) -> bool:
    return listing_status in {"private", "unlisted"}


def is_listed_company(topic) -> bool:
    return getattr(topic, "research_object_type", "unknown") == "listed_company" or (
        getattr(topic, "research_object_type", "unknown") == "unknown"
        and getattr(topic, "listing_status", "unknown") == "listed"
    ) or (
        getattr(topic, "research_object_type", "unknown") == "unknown"
        and getattr(topic, "type", None) == "company"
        and getattr(topic, "listing_status", "unknown") not in {"private", "unlisted", "not_applicable", "concept", "asset"}
    )
