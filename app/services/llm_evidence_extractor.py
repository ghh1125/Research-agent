from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.llm_evidence_qa import qa_candidate_evidence
from app.services.listing_status_service import _LISTED_COMPANY_ALIASES, get_known_entity_aliases
from app.services.llm_service import call_llm

EXTRACTION_PROMPT = """
你是一个金融文档结构化抽取专家。

从以下文本中抽取财务和经营数据，严格按 JSON schema 输出。

规则：
1. 只抽取文本中明确存在的数据，不推断、不补全
2. 无法确定 period 时，period = null，不要猜
3. 文本是导航栏/页脚/目录时，返回空数组
4. 卖方预测数据必须标注 is_estimate = true
5. 跨主体数据（如竞争对手数据混入）标注 requires_cross_check = true

输出格式：
{{
  "evidences": [
    {{
      "metric_name": "revenue_growth",
      "metric_value": 12,
      "unit": "%",
      "period": "FY2025Q4",
      "entity": "淘天集团",
      "segment": "客户管理收入",
      "is_estimate": false,
      "requires_cross_check": false,
      "extraction_confidence": 0.9,
      "quote": "原文原句"
    }}
  ]
}}

文本：
{chunk_text}
""".strip()

_OFFICIAL_ORIGINS = {"company_ir", "official_disclosure", "regulatory"}
_WEAK_TIERS = {"content", "weak"}
_PEER_TOKENS = {"peer", "peers", "competitor", "competitors", "同行", "竞争对手", "可比公司"}
_DANGLING_NUMBER_PATTERNS = [
    re.compile(r"(?:to|至)\s*(?:RMB|CNY|USD|US\$|HK\$|人民币|人民幣)\s*\d{1,3}\s*$", re.I),
    re.compile(r"^(?:ent|ment|venue|come|flow)\s+", re.I),
]
_PERIOD_PATTERN = re.compile(
    r"^(?:FY)?20\d{2}(?:Q[1-4])?$|^20\d{2}Q[1-4]$|^20\d{2}-\d{2}-\d{2}$|^TTM$",
    re.I,
)


class CandidateEvidence(BaseModel):
    metric_name: str | None = None
    metric_value: str | float | int | None = None
    unit: str | None = None
    period: str | None = None
    entity: str | None = None
    segment: str | None = None
    is_estimate: bool = False
    requires_cross_check: bool = False
    extraction_confidence: float = 0.0
    quote: str = ""
    comparison_type: str | None = None
    source_page: int | None = None
    source_table_id: str | None = None


class ExtractionResponse(BaseModel):
    evidences: list[CandidateEvidence] = Field(default_factory=list)


def _source_text(source: Source) -> str:
    return source.enriched_content or source.fetched_content or source.content


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text


def _target_aliases(topic: Topic) -> set[str]:
    aliases = set(get_known_entity_aliases(topic.entity or topic.topic))
    if topic.entity:
        aliases.add(topic.entity)
    if topic.topic:
        aliases.add(topic.topic)
    return {item for item in aliases if item}


def _is_known_other_entity(text: str, topic: Topic) -> bool:
    lowered = text.lower()
    target_aliases = {alias.lower() for alias in _target_aliases(topic)}
    if any(token.lower() in lowered for token in _PEER_TOKENS):
        return False
    for canonical, aliases in _LISTED_COMPANY_ALIASES.items():
        if canonical.lower() in target_aliases:
            continue
        if any(alias.lower() in lowered for alias in aliases):
            return True
    return False


def is_cross_entity_contaminated(ev: CandidateEvidence, target_entity: str | None, topic: Topic | None = None) -> bool:
    if not target_entity:
        return False
    text = " ".join(item for item in [ev.entity or "", ev.quote] if item)
    target_aliases = {target_entity.lower()}
    if topic is not None:
        target_aliases.update(alias.lower() for alias in _target_aliases(topic))
    if ev.entity and ev.entity.lower() not in target_aliases:
        known_entities = {canonical.lower() for canonical in _LISTED_COMPANY_ALIASES}
        known_entities.update(alias.lower() for aliases in _LISTED_COMPANY_ALIASES.values() for alias in aliases)
        if ev.entity.lower() in known_entities:
            return True
    return _is_known_other_entity(text, topic) if topic is not None else False


def has_dangling_numbers(quote: str) -> bool:
    return any(pattern.search((quote or "").strip()) for pattern in _DANGLING_NUMBER_PATTERNS)


def is_valid_period_format(period: str | None) -> bool:
    if period is None:
        return True
    return bool(_PERIOD_PATTERN.match(str(period).strip()))


def verify_value_grounded_in_quote(ev: CandidateEvidence) -> bool:
    if ev.metric_value is None:
        return True
    quote = ev.quote or ""
    value_str = str(ev.metric_value)
    candidates = {
        value_str,
        value_str.replace(".0", ""),
        value_str.replace(",", ""),
    }
    if isinstance(ev.metric_value, (int, float)):
        candidates.add(f"{float(ev.metric_value):g}")
    normalized_quote = quote.replace(",", "")
    return any(candidate and (candidate in quote or candidate in normalized_quote) for candidate in candidates)


def validate_candidate_evidence(ev: CandidateEvidence, source: Source, topic: Topic | None = None) -> bool:
    # 1. 跨主体污染
    if ev.requires_cross_check:
        return False
    target_entity = topic.entity if topic else None
    if is_cross_entity_contaminated(ev, target_entity, topic):
        return False

    # 2. 截断数字
    if ev.metric_value is None and has_dangling_numbers(ev.quote):
        return False
    if not verify_value_grounded_in_quote(ev):
        return False

    # 3. source tier 上限
    if source.tier.value in _WEAK_TIERS and ev.extraction_confidence < 0.8:
        return False

    # 4. period 一致性
    if not is_valid_period_format(ev.period):
        return False
    return True


def _parse_candidates(raw: str) -> list[CandidateEvidence]:
    payload = json.loads(_extract_json_object(raw))
    if "evidence" in payload and "evidences" not in payload:
        payload["evidences"] = payload["evidence"]
    return ExtractionResponse.model_validate(payload).evidences


def extract_candidate_evidence(chunk_text: str) -> list[CandidateEvidence]:
    if not chunk_text.strip():
        return []
    try:
        raw = call_llm(EXTRACTION_PROMPT.format(chunk_text=chunk_text[:6000]), temperature=0.0)
        return _parse_candidates(raw)
    except Exception:
        return []


def _normalize_metric_name(metric_name: str | None) -> str | None:
    if not metric_name:
        return None
    normalized = re.sub(r"[\s\-/]+", "_", metric_name.strip())
    aliases = {
        "EV_EBITDA": "ev_ebitda",
        "EV/EBITDA": "ev_ebitda",
        "PE": "pe",
        "PB": "pb",
        "customer_management_revenue": "customer_management_revenue",
        "CMR": "cmr",
    }
    return aliases.get(normalized, normalized.lower())


def _question_id(metric_name: str | None, source: Source, questions: list[Question]) -> str | None:
    metric = _normalize_metric_name(metric_name) or ""
    preferred = ["financial"]
    if metric in {"operating_cash_flow", "free_cash_flow", "capex", "cash_balance", "total_liabilities"}:
        preferred = ["credit", "financial"]
    elif metric in {"pe", "pb", "ev_ebitda"}:
        preferred = ["valuation", "financial"]
    elif metric == "market_share":
        preferred = ["industry"]
    for framework in preferred:
        for question in questions:
            if question.framework_type == framework:
                return question.id
    return source.question_id or (questions[0].id if questions else None)


def _candidate_to_evidence(ev: CandidateEvidence, source: Source, topic: Topic, questions: list[Question], index: int) -> Evidence:
    qa_result = qa_candidate_evidence(
        source_metadata={"title": source.title, "url": source.url, "tier": source.tier.value},
        raw_chunk=_source_text(source),
        candidate_evidence=ev,
        target_profile=(
            {"entity": topic.entity, "aliases": sorted(_target_aliases(topic))}
            if topic.type == "company" and topic.entity
            else None
        ),
    )
    metric_name = _normalize_metric_name(qa_result.fixed_metric_name or ev.metric_name)
    valid = validate_candidate_evidence(ev, source, topic) and qa_result.keep
    notes = ["llm_structured_candidate"]
    if source.source_origin_type in _OFFICIAL_ORIGINS or source.tier.value == "official" or source.is_official_pdf:
        notes.append("official_structured_financial")
    if ev.is_estimate or qa_result.is_estimate:
        notes.append("estimate")
    if ev.requires_cross_check:
        notes.append("requires_cross_check")
    if not valid:
        notes.append("validation_rejected")
    quality = max(0.0, min(float(ev.extraction_confidence or qa_result.grounding_score or 0.0), 1.0))
    quality = min(quality, qa_result.grounding_score or quality)
    if not valid:
        quality = min(quality, 0.25)
    return Evidence(
        id=f"e{index}",
        topic_id=topic.id,
        question_id=_question_id(metric_name, source, questions),
        source_id=source.id,
        flow_type=source.flow_type,
        content=(ev.quote or "").strip()[:180],
        evidence_type="data",
        stance="neutral",
        grounded=True,
        is_noise=False,
        is_truncated=has_dangling_numbers(ev.quote),
        cross_entity_contamination=is_cross_entity_contaminated(ev, topic.entity, topic),
        can_enter_main_chain=valid,
        quality_score=quality,
        quality_notes=[*notes, f"grounding={qa_result.grounding_score}", f"qa_reason={qa_result.reason}"],
        source_tier=source.tier.value,
        source_score=source.source_score,
        relevance_score=0.9 if valid else 0.2,
        clarity_score=0.9 if ev.quote else 0.0,
        recency_score=1.0,
        evidence_score=quality,
        metric_name=metric_name,
        metric_value=qa_result.fixed_metric_value if qa_result.fixed_metric_value is not None else ev.metric_value,
        unit=qa_result.fixed_unit or ev.unit,
        period=qa_result.fixed_period or ev.period,
        segment=ev.segment,
        comparison_type=ev.comparison_type,
        entity=ev.entity or topic.entity or topic.topic,
        source_type="official" if source.source_origin_type in _OFFICIAL_ORIGINS or source.tier.value == "official" else source.source_origin_type,
        source_page=ev.source_page,
        source_table_id=ev.source_table_id,
        extraction_confidence=quality,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def extract_structured_evidence_candidates(
    source: Source,
    topic: Topic,
    questions: list[Question],
    start_index: int = 1,
) -> list[Evidence]:
    candidates = extract_candidate_evidence(_source_text(source))
    evidence: list[Evidence] = []
    seen: set[tuple[str | None, str | float | int | None, str | None, str | None]] = set()
    for candidate in candidates:
        key = (_normalize_metric_name(candidate.metric_name), candidate.metric_value, candidate.period, candidate.segment)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(_candidate_to_evidence(candidate, source, topic, questions, start_index + len(evidence)))
    return evidence


def official_parse_metrics(sources: list[Source], evidence: list[Evidence]) -> dict[str, float]:
    official_sources = [
        source
        for source in sources
        if source.is_official_pdf
        or source.source_origin_type in _OFFICIAL_ORIGINS
        or source.tier.value == "official"
    ]
    if not official_sources:
        return {
            "official_source_parse_rate": 0.0,
            "official_source_to_evidence_rate": 0.0,
            "official_evidence_used_in_judgment_rate": 0.0,
        }
    parsed_sources = [
        source
        for source in official_sources
        if source.pdf_parse_status == "parsed" or source.fetched_content or source.enriched_content or source.content
    ]
    evidence_source_ids = {
        item.source_id
        for item in evidence
        if "llm_structured_candidate" in (item.quality_notes or [])
        and (item.source_tier == "official" or "official_structured_financial" in (item.quality_notes or []))
    }
    return {
        "official_source_parse_rate": round(len(parsed_sources) / len(official_sources), 3),
        "official_source_to_evidence_rate": round(len(evidence_source_ids) / len(official_sources), 3),
        "official_evidence_used_in_judgment_rate": 0.0,
    }
