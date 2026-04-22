from __future__ import annotations

import json
from hashlib import md5
import re

from app.agent.prompts.define_prompt import DEFINE_PROMPT_TEMPLATE
from app.models.topic import Topic
from app.services.listing_status_service import infer_listing_profile, normalize_entity_candidate
from app.services.llm_service import call_llm

_KNOWN_COMPANY_ALIASES = [
    "拼多多",
    "PDD",
    "PDD Holdings",
    "宁德时代",
    "阿里巴巴",
    "腾讯",
    "美团",
    "京东",
    "华为",
    "Huawei",
    "小米",
    "比亚迪",
    "特斯拉",
    "苹果",
    "英伟达",
]


def _infer_topic_type(query: str) -> str:
    lowered = query.lower()
    if "政策" in query or "监管" in query or "合规" in query or "policy" in lowered or "compliance" in lowered:
        return "compliance"
    if _infer_entity(query, ""):
        return "company"
    if "违约" in query:
        return "theme"
    if "公司" in query or "企业" in query or "company" in lowered:
        return "company"
    if "行业" in query or "模式" in query or "主题" in query or "theme" in lowered:
        return "theme"
    return "general"


def _clean_topic_text(query: str) -> str:
    cleaned = query.strip("？?。 ")
    cleaned = re.sub(r"^(请)?(帮我)?(研究|分析|判断|看看|评估)", "", cleaned)
    cleaned = re.sub(r"(是否|有没有|值不值得|是否值得|需不需要|能不能|可以不可以)", "", cleaned)
    cleaned = re.sub(r"(有没有合规风险|是否有合规风险)$", "", cleaned)
    cleaned = re.sub(r"(是否值得进一步研究|值不值得进一步研究)$", "", cleaned)
    cleaned = re.sub(r"(是否值得进入深度研究阶段|值得进入深度研究阶段|进入深度研究阶段)$", "", cleaned)
    cleaned = re.sub(r"(是否具有可持续性|具有可持续性)$", "可持续性", cleaned)
    cleaned = re.sub(r"(值得进一步研究|进一步研究|研究价值)$", "", cleaned)
    cleaned = re.sub(r"当前的?", "", cleaned)
    cleaned = cleaned.strip("：:，, ")
    return cleaned or query.strip()


def _infer_goal(query: str, topic_type: str, topic_text: str) -> str:
    if "违约" in query:
        return f"识别“{topic_text}”的成因、风险信号与共性模式"
    if "增长" in query and "可持续" in query:
        return f"评估“{topic_text}”的增长质量、核心驱动、风险约束与是否值得进入深度研究"
    if any(token in query for token in ["合规", "监管", "经营权模式"]):
        return f"评估“{topic_text}”的合规边界、监管约束与潜在违规风险"
    if "值得进一步研究" in query or "值不值得进一步研究" in query:
        return f"判断“{topic_text}”是否具备继续深挖的研究价值，并识别关键验证点"
    if topic_type == "company":
        return f"评估“{topic_text}”的经营质量、风险暴露与后续研究优先级"
    if topic_type == "compliance":
        return f"厘清“{topic_text}”的规则边界、执行约束与潜在影响"
    return f"围绕“{topic_text}”形成初步研究判断并识别风险与未知点"


def _infer_entity(query: str, topic_text: str) -> str | None:
    for alias in _KNOWN_COMPANY_ALIASES:
        if alias in query:
            return normalize_entity_candidate(query, "拼多多" if alias in {"PDD", "PDD Holdings"} else alias)

    company_match = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{2,20}(公司|集团|股份|有限责任公司))", query)
    if company_match:
        return normalize_entity_candidate(query, company_match.group(1))

    cleaned = _clean_topic_text(query) if query else topic_text
    cleaned = re.sub(r"(的)?(财务|现金流|治理|行业|竞争|风险|合规|基本面|研究价值|违约|增长模式|高增长|可持续).*", "", cleaned)
    cleaned = cleaned.strip("：:，, 的")
    if 2 <= len(cleaned) <= 12 and not any(token in cleaned for token in ["贸易企业", "经营权模式", "这个", "这家"]):
        return normalize_entity_candidate(query, cleaned)

    if any(token in query for token in ["模式", "机制", "经营权"]):
        return normalize_entity_candidate(query, topic_text)

    return None


def _build_concise_topic(query: str, topic_type: str, entity: str | None, topic_text: str) -> str:
    if topic_type == "company" and entity:
        if "增长" in query and "可持续" in query:
            return f"{entity}高增长模式可持续性"
        if "违约" in query:
            return f"{entity}违约风险"
        if "值得" in query or "进一步研究" in query or "研究价值" in query:
            return f"{entity}研究价值"
        return f"{entity}基本面"
    if topic_type == "compliance":
        return f"{entity or topic_text}合规风险".strip()
    if "违约" in query:
        return "贸易企业违约原因" if "贸易企业" in query else f"{topic_text}违约原因"
    return topic_text[:20]


def _extract_hypothesis(query: str) -> str | None:
    match = re.search(r"(我认为|假设|假说|是否因为|会不会)(.+)$", query)
    if not match:
        return None
    text = (match.group(1) + match.group(2)).strip(" ，。?？")
    return text or None


def _coerce_topic_type(topic_type: str | None, query: str) -> str:
    allowed = {"company", "theme", "compliance", "general"}
    normalized = (topic_type or "").strip().lower()
    if normalized in {"policy", "regulatory", "event"}:
        normalized = "compliance" if normalized != "event" else "theme"
    if normalized in allowed:
        return normalized
    return _infer_topic_type(query)


def _parse_llm_topic(raw: str, query: str, topic_id: str) -> Topic | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    raw_topic_text = str(payload.get("topic", "")).strip() or _clean_topic_text(query)
    topic_type = _coerce_topic_type(payload.get("type"), query)
    entity_value = payload.get("entity")
    entity = str(entity_value).strip() if isinstance(entity_value, str) and entity_value.strip() else _infer_entity(query, raw_topic_text)
    inferred_entity = _infer_entity(query, raw_topic_text)
    if inferred_entity and (not entity or len(entity) > 12 or entity in query):
        entity = inferred_entity
    entity = normalize_entity_candidate(query, entity)
    listing_profile = infer_listing_profile(query, entity)
    entity = listing_profile.entity or entity
    if listing_profile.topic_type_override:
        topic_type = listing_profile.topic_type_override
    topic_text = _build_concise_topic(query, topic_type, entity, raw_topic_text)
    goal = str(payload.get("goal", "")).strip() or _infer_goal(query, topic_type, topic_text)
    if listing_profile.listing_status in {"private", "unlisted"} and "股票" in query:
        goal = f"识别“{entity}”未上市边界，评估其经营质量、产业链投资机会和潜在上市情景，而不是直接生成股票估值判断"
    hypothesis_value = payload.get("hypothesis")
    hypothesis = (
        str(hypothesis_value).strip()
        if isinstance(hypothesis_value, str) and hypothesis_value.strip()
        else _extract_hypothesis(query)
    )

    return Topic(
        id=topic_id,
        query=query,
        entity=entity,
        topic=topic_text,
        goal=goal,
        type=topic_type,
        hypothesis=hypothesis,
        research_object_type=listing_profile.research_object_type,
        listing_status=listing_profile.listing_status,
        market_type=listing_profile.market_type,
        listing_note=listing_profile.listing_note,
    )


def _fallback_define(query: str) -> Topic:
    topic_id = f"topic_{md5(query.encode('utf-8')).hexdigest()[:8]}"
    topic_type = _infer_topic_type(query)
    raw_topic_text = _clean_topic_text(query)
    entity = _infer_entity(query, raw_topic_text)
    listing_profile = infer_listing_profile(query, entity)
    entity = listing_profile.entity or entity
    if listing_profile.topic_type_override:
        topic_type = listing_profile.topic_type_override
    topic_text = _build_concise_topic(query, topic_type, entity, raw_topic_text)
    goal = _infer_goal(query, topic_type, topic_text)
    if listing_profile.listing_status in {"private", "unlisted"} and "股票" in query:
        goal = f"识别“{entity}”未上市边界，评估其经营质量、产业链投资机会和潜在上市情景，而不是直接生成股票估值判断"
    return Topic(
        id=topic_id,
        query=query,
        entity=entity,
        topic=topic_text or query,
        goal=goal,
        type=topic_type,
        hypothesis=_extract_hypothesis(query),
        research_object_type=listing_profile.research_object_type,
        listing_status=listing_profile.listing_status,
        market_type=listing_profile.market_type,
        listing_note=listing_profile.listing_note,
    )


def define_problem(query: str) -> Topic:
    """Convert a fuzzy user query into a structured topic."""

    prompt = DEFINE_PROMPT_TEMPLATE.format(query=query)
    topic_id = f"topic_{md5(query.encode('utf-8')).hexdigest()[:8]}"
    try:
        raw = call_llm(prompt)
        parsed = _parse_llm_topic(raw, query, topic_id)
        if parsed is not None:
            return parsed
    except RuntimeError:
        return _fallback_define(query)
    return _fallback_define(query)
