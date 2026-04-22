from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.models.source import Source
from app.models.source import SourceTier
from app.models.topic import Topic

_ENTITY_ALIASES = {
    "拼多多": ["拼多多", "PDD", "PDD Holdings", "Temu", "多多买菜"],
    "宁德时代": ["宁德时代", "CATL"],
}

_TIER1_DOMAINS = [
    "sec.gov",
    "catl.com",
    "byd.com",
    "pinduoduo.com",
    "pddholdings.com",
    "investor.pddholdings.com",
    "ir.tencent.com",
    "investor.alibaba.com",
    "sse.com.cn",
    "szse.cn",
    "csrc.gov.cn",
    "ndrc.gov.cn",
    "cninfo.com.cn",
    "hkexnews.hk",
    "nyse.com",
    "nasdaq.com",
    "annualreports.com",
]

_OFFICIAL_COMPANY_DOMAINS = [
    "catl.com",
    "byd.com",
    "ir.tencent.com",
    "investor.alibaba.com",
    "investor.pddholdings.com",
    "pddholdings.com",
    "tencent.com",
    "meituan.com",
    "alibabagroup.com",
    "nvidia.com",
    "tesla.com",
    "apple.com",
    "microsoft.com",
]

_OFFICIAL_PATH_TOKENS = [
    "/uploads/",
    "/ir/",
    "/investor/",
    "/investors/",
    "/report/",
    "/reports/",
    "/annual/",
    "/disclosure/",
    "/financial/",
    "/earnings/",
    "/results/",
]

_OFFICIAL_TITLE_TOKENS = [
    "年度报告",
    "年报摘要",
    "季度报告",
    "半年度报告",
    "annual_report",
    "annual report",
    "quarterly_results",
    "quarterly results",
    "earnings_release",
    "earnings release",
    "financial results",
]

_DISCLOSURE_KEYWORD_TOKENS = [
    "A股股票代码",
    "H股股票代码",
    "董事会秘书",
    "利润分配预案",
    "资产负债率",
    "流动比率",
    "证券交易所",
    "主要会计数据",
    "营业收入",
    "归属于上市公司股东的净利润",
]

_TIER2_DOMAINS = [
    "eastmoney.com",
    "wind.com",
    "10jqka.com.cn",
    "stcn.com",
    "yicai.com",
    "caixin.com",
    "finance.sina.com.cn",
    "nasdaq.com",
    "futunn.com",
    "wallstreetcn.com",
    "36kr.com",
    "latepost.com",
    "thepaper.cn",
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "morningstar.com",
    "spglobal.com",
    "moodys.com",
    "fitchratings.com",
    "seekingalpha.com",
]

_COMMUNITY_DOMAINS = [
    "xueqiu.com",
    "zhihu.com",
    "reddit.com",
    "guba.eastmoney.com",
]

_SELF_MEDIA_DOMAINS = [
    "mp.weixin.qq.com",
    "baijiahao.baidu.com",
    "toutiao.com",
    "sohu.com",
]

_AGGREGATOR_DOMAINS = [
    "news.qq.com",
    "163.com",
    "ifeng.com",
]

_FINANCIAL_SIGNAL_TOKENS = [
    "财报",
    "年报",
    "季报",
    "annual report",
    "form 20-f",
    "10-k",
    "营收",
    "收入",
    "净利润",
    "利润",
    "现金流",
    "毛利率",
    "经营利润",
    "用户",
    "订单",
    "GMV",
    "Temu",
    "商家",
    "货币化率",
]

_SOURCE_NOISE_TOKENS = [
    "高质量数据集",
    "数据集规模化",
    "机器学习",
    "论文",
    "作文",
    "招聘",
    "下载站",
    "网盘",
]

_REPRINT_OR_AGGREGATION_TOKENS = [
    "转载自",
    "本文转载",
    "来源：",
    "文章来源",
    "编辑：",
    "责任编辑",
    "相关推荐",
    "相关阅读",
    "免责声明",
    "版权归原作者",
    "仅代表作者观点",
    "股吧",
    "网友",
    "用户评论",
]

_RECENT_YEAR_FLOOR = datetime.now(timezone.utc).year - 2
_INVALID_PROVIDER_DATES = {"1970-01-01", "1970-01-01T00:00:00", "1970-01-01T00:00:00Z"}

_COMMON_RESEARCH_TOKENS = [
    "增长",
    "可持续",
    "深度研究",
    "商业模式",
    "盈利",
    "现金流",
    "竞争",
    "监管",
    "风险",
    "财务",
    "估值",
]
_EVIDENCE_SIGNAL_TOKENS = _FINANCIAL_SIGNAL_TOKENS + [
    "增长",
    "下降",
    "研发",
    "份额",
    "领先",
    "集中度",
    "客户",
    "商家",
    "补贴",
    "竞争",
    "风险",
    "监管",
    "治理",
    "改善",
    "转正",
    "可持续",
]


def get_entity_aliases(topic: Topic) -> list[str]:
    entity = topic.entity or topic.topic
    aliases = _ENTITY_ALIASES.get(entity, [entity])
    return [alias for alias in aliases if alias]


def _domain(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def assign_credibility_tier(url: str | None) -> str:
    tier = classify_source_tier(url)
    return {
        SourceTier.TIER1: "tier1",
        SourceTier.TIER2: "tier2",
        SourceTier.TIER3: "tier3",
    }[tier]


def classify_source_tier(url: str | None) -> SourceTier:
    origin = classify_source_origin(url=url, title="", source_type="other", content="")
    return classify_tier_from_origin(origin)


def classify_tier_from_origin(origin: str) -> SourceTier:
    if origin in {"official_disclosure", "company_ir", "regulatory"}:
        return SourceTier.TIER1
    if origin in {"professional_media", "research_media"}:
        return SourceTier.TIER2
    return SourceTier.TIER3


def classify_source_origin(
    url: str | None,
    title: str,
    source_type: str,
    content: str = "",
) -> str:
    """Classify where a source originated, separately from quality score."""

    domain = _domain(url)
    text = f"{url or ''} {title} {content[:500]}".lower()
    official_score = score_official_source(url, title, source_type, content)

    regulatory_tokens = ["sec.gov", "csrc.gov.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "cninfo.com.cn", "ndrc.gov.cn"]
    if source_type == "regulatory" or any(token in domain for token in regulatory_tokens):
        return "regulatory"

    if official_score >= 0.58 and any(item in domain for item in _OFFICIAL_COMPANY_DOMAINS):
        return "company_ir"

    official_disclosure_tokens = [
        "10-k",
        "10-q",
        "20-f",
        "8-k",
        "annual report",
        "quarterly report",
        "earnings release",
        "financial results",
        "业绩公告",
        "年度报告",
        "季度报告",
        "财报",
    ]
    if any(token in text for token in official_disclosure_tokens):
        if any(item in domain for item in _TIER1_DOMAINS) or "investor" in domain or "ir." in domain:
            return "official_disclosure"

    company_ir_tokens = ["investor", "investors", "ir.", "/ir", "investor-relations", "newsroom", "press-release", "official"]
    if source_type == "company" or any(token in text for token in company_ir_tokens):
        if not any(item in domain for item in _COMMUNITY_DOMAINS + _SELF_MEDIA_DOMAINS + _AGGREGATOR_DOMAINS):
            return "company_ir"

    if any(item in domain for item in _TIER1_DOMAINS):
        return "official_disclosure"
    if any(item in domain for item in _TIER2_DOMAINS):
        if any(token in text for token in ["research", "report", "rating", "研报", "评级", "industry report"]):
            return "research_media"
        return "professional_media"
    if any(item in domain for item in _COMMUNITY_DOMAINS):
        return "community"
    if any(item in domain for item in _SELF_MEDIA_DOMAINS):
        return "self_media"
    if any(item in domain for item in _AGGREGATOR_DOMAINS):
        return "aggregator"
    return "unknown"


def score_official_source(url: str | None, title: str, source_type: str, content: str = "") -> float:
    """Score whether a source is an official disclosure or company IR document."""

    url_text = (url or "").lower()
    domain = _domain(url)
    title_text = title.lower()
    content_text = content[:2000]
    score = 0.0
    if source_type in {"regulatory", "company"}:
        score += 0.2
    if any(item in domain for item in _OFFICIAL_COMPANY_DOMAINS):
        score += 0.35
    if any(item in domain for item in _TIER1_DOMAINS):
        score += 0.28
    if any(token in url_text for token in _OFFICIAL_PATH_TOKENS):
        score += 0.18
    if any(token.lower() in title_text or token.lower() in url_text for token in _OFFICIAL_TITLE_TOKENS):
        score += 0.2
    keyword_hits = sum(1 for token in _DISCLOSURE_KEYWORD_TOKENS if token in content_text or token.lower() in content_text.lower())
    score += min(keyword_hits, 4) * 0.08
    if ".pdf" in url_text or "pdf" in title_text:
        score += 0.08
    return max(0.0, min(1.0, round(score, 3)))


def _source_origin(source: Source) -> str:
    if source.source_origin_type != "unknown":
        return source.source_origin_type
    return classify_source_origin(source.url, source.title, source.source_type, _source_text(source))


def _source_tier(source: Source) -> SourceTier:
    return _downgrade_tier_for_content_signals(classify_tier_from_origin(_source_origin(source)), source)


def is_official_pdf_source(source: Source) -> bool:
    return bool(
        _is_pdf_like(source)
        and classify_tier_from_origin(_source_origin(source)) == SourceTier.TIER1
        and _source_origin(source) in {"company_ir", "official_disclosure", "regulatory"}
    )


def _is_pdf_like(source: Source) -> bool:
    text = f"{source.url or ''} {source.title}".lower()
    return ".pdf" in text or "[pdf]" in text or "pdf" in text


def _source_text(source: Source) -> str:
    return source.enriched_content or source.fetched_content or source.content


def _parse_provider_date(raw_date: str | None) -> datetime | None:
    if not raw_date:
        return None
    cleaned = raw_date.strip()
    if not cleaned or cleaned in _INVALID_PROVIDER_DATES:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(cleaned[:10], fmt)
        except ValueError:
            continue
    return None


def _valid_extracted_date(year: int, month: int, day: int = 1) -> datetime | None:
    current_year = datetime.now(timezone.utc).year
    if not 2000 <= year <= current_year:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def resolve_source_date(source: Source) -> tuple[datetime | None, str]:
    """Resolve date from provider, URL, then content; unknown is not stale."""

    provider_date = _parse_provider_date(source.published_at)
    if provider_date is not None and provider_date.year != 1970:
        return provider_date, "provider"

    url = source.url or ""
    for pattern in [r"(\d{4})[/-](\d{2})[/-](\d{2})", r"(\d{4})(\d{2})(\d{2})"]:
        match = re.search(pattern, url)
        if match:
            year, month, day = (int(item) for item in match.groups())
            candidate = _valid_extracted_date(year, month, day)
            if candidate is not None:
                return candidate, "url_extracted"

    text = f"{source.title} {_source_text(source)[:1200]}"
    for pattern in [r"(20\d{2})年(\d{1,2})月(?:([0-3]?\d)日)?", r"\b(20\d{2})[./-](\d{1,2})(?:[./-]([0-3]?\d))?\b"]:
        match = re.search(pattern, text)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3) or 1)
            candidate = _valid_extracted_date(year, month, day)
            if candidate is not None:
                return candidate, "content_extracted"

    return None, "unknown"


def compute_is_recent(resolved_date: datetime | None, threshold_days: int = 180) -> bool | None:
    if resolved_date is None:
        return None
    now = (
        datetime.now(resolved_date.tzinfo)
        if resolved_date.tzinfo is not None
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    return (now - resolved_date).days <= threshold_days


def text_quality_score(text: str) -> float:
    """Score whether text is readable enough for evidence extraction."""

    if not text:
        return 0.0

    compact = re.sub(r"\s+", "", text)
    if len(compact) < 8:
        return 0.0

    cjk = len(re.findall(r"[\u4e00-\u9fff]", compact))
    latin = len(re.findall(r"[A-Za-z]", compact))
    digits = len(re.findall(r"\d", compact))
    common_punct = len(re.findall(r"""[，,。！？!?；;：:（）()《》“”"'/%+.\-]""", compact))
    readable = cjk + latin + digits + common_punct
    weird = max(len(compact) - readable, 0)
    weird_ratio = weird / max(len(compact), 1)

    if "�" in text or "\x00" in text:
        weird_ratio += 0.3

    if len(compact) < 30 and cjk == 0 and weird_ratio > 0.02:
        return 0.0

    signal_hits = sum(1 for token in _EVIDENCE_SIGNAL_TOKENS if token.lower() in text.lower())
    readable_ratio = (cjk + latin + digits) / max(len(compact), 1)
    if len(compact) < 20 and signal_hits == 0 and not re.search(r"\d", compact):
        return 0.0
    score = readable_ratio * 0.65 + min(signal_hits, 5) * 0.07 - weird_ratio * 0.9
    return max(0.0, min(1.0, round(score, 3)))


def is_gibberish_text(text: str) -> bool:
    return text_quality_score(text) < 0.22


def _has_entity_signal(source: Source, topic: Topic) -> bool:
    content = _source_text(source)
    haystack = f"{source.title} {content[:1200]}".lower()
    return any(alias.lower() in haystack for alias in get_entity_aliases(topic))


def contains_target_entity(text: str, topic: Topic) -> bool:
    haystack = text.lower()
    return any(alias.lower() in haystack for alias in get_entity_aliases(topic))


def is_recent_source(source: Source) -> bool | None:
    resolved_date, _date_source = resolve_source_date(source)
    if resolved_date is not None:
        return compute_is_recent(resolved_date)
    text = " ".join(item for item in [source.title, _source_text(source)[:500]] if item)
    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return None
    return max(years) >= _RECENT_YEAR_FLOOR


def _topic_relevance_score(source: Source, topic: Topic) -> float:
    content = _source_text(source)
    haystack = f"{source.title} {content[:2000]}".lower()
    aliases = get_entity_aliases(topic)
    entity_hits = sum(1 for alias in aliases if alias.lower() in haystack)
    topic_tokens = [token for token in _COMMON_RESEARCH_TOKENS if token in topic.query or token in topic.topic or token in topic.goal]
    topic_hits = sum(1 for token in topic_tokens if token.lower() in haystack)
    financial_hits = sum(1 for token in _FINANCIAL_SIGNAL_TOKENS if token.lower() in haystack)
    return min(1.0, entity_hits * 0.35 + topic_hits * 0.08 + financial_hits * 0.04)


def score_source(source: Source, topic: Topic) -> tuple[float, str]:
    content = _source_text(source)
    quality = text_quality_score(content)
    relevance = _topic_relevance_score(source, topic)
    tier = _source_tier(source)
    tier_bonus = {
        SourceTier.TIER1: 0.34,
        SourceTier.TIER2: 0.2,
        SourceTier.TIER3: 0.03,
    }.get(tier, 0.0)
    entity_bonus = 0.12 if _has_entity_signal(source, topic) else 0.0
    recency_status = is_recent_source(source)
    recency_bonus = 0.06 if recency_status is True else 0.0
    pdf_penalty = 0.18 if _is_pdf_like(source) and quality < 0.45 else 0.0
    noise_penalty = 0.25 if any(token in f"{source.title}{content[:500]}" for token in _SOURCE_NOISE_TOKENS) else 0.0
    reprint_penalty = 0.16 if _looks_reprinted_or_aggregated(source) else 0.0
    entity_penalty = 0.28 if topic.type == "company" and topic.entity and not _has_entity_signal(source, topic) else 0.0
    score = quality * 0.38 + relevance * 0.32 + tier_bonus + entity_bonus + recency_bonus - pdf_penalty - noise_penalty - reprint_penalty - entity_penalty
    score = max(0.0, min(1.0, round(score, 3)))

    reasons = [
        f"quality={quality:.2f}",
        f"relevance={relevance:.2f}",
        f"tier={tier.value}",
        f"contains_entity={str(_has_entity_signal(source, topic)).lower()}",
        f"is_recent={str(recency_status).lower()}",
    ]
    if pdf_penalty:
        reasons.append("pdf_text_low_quality")
    if noise_penalty:
        reasons.append("source_noise")
    if reprint_penalty:
        reasons.append("reprint_or_aggregation")
    if entity_penalty:
        reasons.append("entity_missing")
    return score, ";".join(reasons)


def _downgrade_tier_for_content_signals(tier: SourceTier, source: Source) -> SourceTier:
    if not _looks_reprinted_or_aggregated(source):
        return tier
    if tier == SourceTier.TIER1:
        return SourceTier.TIER2
    if tier == SourceTier.TIER2:
        return SourceTier.TIER3
    return tier


def _looks_reprinted_or_aggregated(source: Source) -> bool:
    content = _source_text(source)
    text = f"{source.title}\n{content[:1200]}"
    return any(token in text for token in _REPRINT_OR_AGGREGATION_TOKENS)


def is_usable_source(source: Source, topic: Topic) -> bool:
    score, _ = score_source(source, topic)
    content = _source_text(source)
    if is_gibberish_text(content):
        return False
    if topic.type == "company" and topic.entity and not _has_entity_signal(source, topic):
        return False
    if _is_pdf_like(source) and text_quality_score(content) < 0.45:
        return False
    return score >= 0.22


def rank_sources(sources: list[Source], topic: Topic, limit: int) -> list[Source]:
    usable: list[Source] = []
    for source in sources:
        origin = _source_origin(source)
        tier = _downgrade_tier_for_content_signals(classify_tier_from_origin(origin), source)
        legacy_tier = {
            SourceTier.TIER1: "tier1",
            SourceTier.TIER2: "tier2",
            SourceTier.TIER3: "tier3",
        }[tier]
        score, reason = score_source(source, topic)
        resolved_date, date_source = resolve_source_date(source)
        enriched = source.model_copy(
            update={
                "credibility_tier": legacy_tier,
                "tier": tier,
                "source_origin_type": origin,
                "source_score": score,
                "source_rank_reason": reason,
                "contains_entity": _has_entity_signal(source, topic),
                "is_recent": compute_is_recent(resolved_date) if resolved_date is not None else is_recent_source(source),
                "date_source": date_source,
                "is_official_pdf": is_official_pdf_source(source),
            }
        )
        if is_usable_source(enriched, topic):
            usable.append(enriched)

    flow_order = {"fact": 0, "risk": 1, "counter": 2}
    usable.sort(
        key=lambda item: (
            0 if item.tier == SourceTier.TIER1 else 1 if item.tier == SourceTier.TIER2 else 2,
            -(item.source_score or 0),
            flow_order.get(item.flow_type, 99),
            item.id,
        )
    )

    selected: list[Source] = []
    seen_flows: set[str] = set()
    for flow in ["fact", "risk", "counter"]:
        for source in usable:
            if source.flow_type == flow and source.id not in {item.id for item in selected}:
                selected.append(source)
                seen_flows.add(flow)
                break

    for source in usable:
        if len(selected) >= limit:
            break
        if source.id in {item.id for item in selected}:
            continue
        selected.append(source)

    return selected[:limit]


def relevance_score_for_text(text: str, topic: Topic, source: Source | None = None) -> float:
    haystack = text.lower()
    entity = 0.35 if contains_target_entity(text, topic) else 0.0
    topic_tokens = [token for token in _COMMON_RESEARCH_TOKENS if token in topic.query or token in topic.topic or token in topic.goal]
    topic_hits = sum(1 for token in topic_tokens if token.lower() in haystack)
    signal_hits = sum(1 for token in _EVIDENCE_SIGNAL_TOKENS if token.lower() in haystack)
    source_bonus = 0.1 if source is not None and source.contains_entity else 0.0
    if topic.type != "company" and not topic.entity:
        entity = 0.1
    return max(0.0, min(1.0, round(entity + topic_hits * 0.08 + signal_hits * 0.04 + source_bonus, 3)))


def recency_score_for_source(source: Source) -> float:
    recency_status = source.is_recent
    if recency_status is None:
        recency_status = is_recent_source(source)
    if recency_status is True:
        return 1.0
    if recency_status is False:
        return 0.35
    return 0.85


def score_evidence_text(text: str, source: Source, topic: Topic | None = None) -> tuple[float, list[str]]:
    clarity_score = text_quality_score(text)
    source_score = source.source_score if source.source_score is not None else 0.35
    relevance_score = relevance_score_for_text(text, topic, source) if topic is not None else clarity_score
    recency_score = recency_score_for_source(source)
    score = 0.4 * source_score + 0.3 * relevance_score + 0.2 * recency_score + 0.1 * clarity_score
    notes = [
        f"clarity_score={clarity_score:.2f}",
        f"source_score={source_score:.2f}",
        f"relevance_score={relevance_score:.2f}",
        f"recency_score={recency_score:.2f}",
    ]
    if re.search(r"\d", text):
        score += 0.06
        notes.append("has_number")
    if any(token in text for token in _FINANCIAL_SIGNAL_TOKENS):
        score += 0.06
        notes.append("has_financial_signal")
    if is_gibberish_text(text):
        score = 0.0
        notes.append("gibberish_rejected")
    return max(0.0, min(1.0, round(score, 3))), notes


def is_readable_text(text: str) -> bool:
    return text_quality_score(text) >= 0.28 and not is_gibberish_text(text)


def looks_like_noise(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    lower_text = text.lower()
    html_like = bool(re.search(r"</?[a-z][^>]*>", lower_text))
    nav_tokens = ["登录", "注册", "首页", "导航", "免责声明", "版权所有", "cookie", "javascript"]
    return html_like or any(token in lower_text or token in compact for token in nav_tokens)


def is_usable_evidence_text(text: str, source: Source, topic: Topic | None = None) -> bool:
    score, _ = score_evidence_text(text, source, topic)
    if looks_like_noise(text):
        return False
    if topic is not None and topic.type == "company" and topic.entity:
        has_entity = contains_target_entity(text, topic) or source.contains_entity
        relevance = relevance_score_for_text(text, topic, source)
        if not has_entity and relevance < 0.45:
            return False
    return score >= 0.28 and is_readable_text(text)
