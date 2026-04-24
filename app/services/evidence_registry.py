from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.models.evidence import Evidence
from app.models.source import Source
from app.models.topic import Topic
from app.services.listing_status_service import get_known_entity_aliases

_VALID_SOURCE_TIERS = {"official", "professional", "content"}
_REPORT_TOKENS = {
    "annual report",
    "annual results",
    "financial highlights",
    "financial report",
    "form 20-f",
    "form 10-k",
    "earnings release",
    "investor presentation",
    "results announcement",
    "年度报告",
    "年报",
    "财务摘要",
    "业绩公告",
}
_NAV_TOKENS = {"home", "menu", "login", "register", "site map", "导航", "首页", "登录", "注册"}
_AGGREGATOR_TOKENS = {
    "revenue model",
    "makes money explained",
    "statistics facts",
    "stock analysis blog",
    "gurufocus",
    "guru focus",
    "motley fool",
    "seekingalpha",
    "seeking alpha",
    "transcript/news",
}


def _compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (value or "").lower())


def _domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def _source_text(source: Source | None) -> str:
    if source is None:
        return ""
    return "\n".join(
        item
        for item in [
            source.title,
            source.url or "",
            source.enriched_content or source.fetched_content or source.content,
        ]
        if item
    )


def _target_aliases(topic: Topic | None) -> set[str]:
    if topic is None or topic.type != "company" or not topic.entity:
        return set()
    aliases = set(get_known_entity_aliases(topic.entity))
    if topic.entity:
        aliases.add(topic.entity)
    return {alias for alias in aliases if alias}


def _matches_alias(text: str, aliases: set[str]) -> bool:
    compact_text = _compact(text)
    if not compact_text or not aliases:
        return False
    return any(alias and _compact(alias) in compact_text for alias in aliases)


def _domain_related_to_target(domain: str, aliases: set[str]) -> bool:
    compact_domain = _compact(domain.removeprefix("www."))
    if not compact_domain or not aliases:
        return False
    return any(_compact(alias) and _compact(alias) in compact_domain for alias in aliases)


def _looks_like_navigation(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    return sum(1 for token in _NAV_TOKENS if token in lowered) >= 2


def _is_aggregator_source(source: Source | None) -> bool:
    if source is None:
        return False
    haystack = f"{source.title}\n{source.url or ''}".lower()
    return (
        source.source_origin_type in {"aggregator", "community", "self_media"}
        or any(token in haystack for token in _AGGREGATOR_TOKENS)
    )


def _grounding_score(item: Evidence) -> float:
    candidates = [item.evidence_score, item.quality_score, item.extraction_confidence]
    for note in item.quality_notes or []:
        if note.startswith("grounding="):
            try:
                candidates.append(float(note.split("=", 1)[1]))
            except ValueError:
                continue
    return max((float(candidate) for candidate in candidates if candidate is not None), default=0.0)


def _quote_or_summary_non_empty(item: Evidence) -> bool:
    return bool((item.content or "").strip() or (item.metric_name or "").strip())


def _is_registry_eligible(item: Evidence) -> bool:
    tier = (item.source_tier or "content").strip()
    return (
        item.can_enter_main_chain
        and not item.is_truncated
        and not item.cross_entity_contamination
        and not item.is_noise
        and tier in _VALID_SOURCE_TIERS
        and _quote_or_summary_non_empty(item)
    )


def _display_priority(item: Evidence) -> tuple[int, int, float]:
    tier_rank = {"official": 0, "professional": 1, "content": 2}.get(item.source_tier or "content", 9)
    metric_rank = 0 if item.metric_name else 1
    score = item.evidence_score or item.quality_score or 0.0
    return (tier_rank, metric_rank, -score)


def _source_reject_reason(item: Evidence, source: Source | None, topic: Topic | None, aliases: set[str]) -> str | None:
    explicit_grounding_signal = any(
        candidate is not None for candidate in [item.evidence_score, item.quality_score, item.extraction_confidence]
    ) or any(note.startswith("grounding=") for note in (item.quality_notes or []))
    if not item.grounded or (explicit_grounding_signal and _grounding_score(item) < 0.45):
        return "LOW_GROUNDING"
    if source is not None and _is_aggregator_source(source):
        return "AGGREGATOR_SOURCE"
    if source is not None and _looks_like_navigation(_source_text(source)[:600]):
        return "NAV_PAGE_ONLY"
    if topic is None or not aliases:
        return None

    entity_text = (item.entity or "").strip()
    source_text = _source_text(source)
    source_domain = _domain(source.url if source is not None else None)
    has_target_signal = _matches_alias(" ".join([entity_text, item.content or "", source_text]), aliases) or _domain_related_to_target(source_domain, aliases)

    title = (source.title if source is not None else "").lower()
    if source is not None and any(token in title for token in _REPORT_TOKENS) and not has_target_signal:
        return "OFF_TARGET_REPORT"
    if entity_text and not _matches_alias(entity_text, aliases):
        return "ENTITY_MISMATCH"
    if source is not None and not has_target_signal and source.source_origin_type in {"company_ir", "official_disclosure", "regulatory"}:
        return "SOURCE_ENTITY_MISMATCH"
    return None


@dataclass(frozen=True)
class EvidenceRegistry:
    total_count: int
    evidence_by_id: dict[str, Evidence]
    debug_stats: dict[str, object] = field(default_factory=dict)

    @property
    def evidence(self) -> list[Evidence]:
        return list(self.evidence_by_id.values())

    @property
    def displayable_count(self) -> int:
        return len(self.evidence_by_id)

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self.evidence_by_id

    def get(self, evidence_id: str) -> Evidence | None:
        return self.evidence_by_id.get(evidence_id)

    def filter_existing(self, evidence_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        filtered: list[str] = []
        for evidence_id in evidence_ids:
            if evidence_id in self.evidence_by_id and evidence_id not in seen:
                filtered.append(evidence_id)
                seen.add(evidence_id)
        return filtered

    def project_for_display(self, evidence_ids: list[str], max_items: int = 12) -> list[Evidence]:
        projected = [self.evidence_by_id[evidence_id] for evidence_id in self.filter_existing(evidence_ids)]
        return sorted(projected, key=_display_priority)[:max_items]


def build_evidence_registry(
    evidence_list: list[Evidence],
    *,
    topic: Topic | None = None,
    sources: list[Source] | None = None,
) -> EvidenceRegistry:
    evidence_by_id: dict[str, Evidence] = {}
    source_map = {item.id: item for item in (sources or [])}
    aliases = _target_aliases(topic)
    reject_reasons: Counter[str] = Counter()
    entity_mismatch_dropped = 0
    off_target_source_dropped = 0

    for item in evidence_list:
        normalized_item = item if item.source_tier else item.model_copy(update={"source_tier": "content"})
        if not _is_registry_eligible(normalized_item):
            continue
        reject_reason = _source_reject_reason(normalized_item, source_map.get(normalized_item.source_id), topic, aliases)
        if reject_reason:
            reject_reasons[reject_reason] += 1
            if reject_reason == "ENTITY_MISMATCH" or (
                reject_reason == "OFF_TARGET_REPORT" and normalized_item.entity and not _matches_alias(normalized_item.entity, aliases)
            ):
                entity_mismatch_dropped += 1
            if reject_reason in {"SOURCE_ENTITY_MISMATCH", "OFF_TARGET_REPORT", "ENTITY_MISMATCH"}:
                off_target_source_dropped += 1
            continue
        if normalized_item.id not in evidence_by_id:
            evidence_by_id[normalized_item.id] = normalized_item

    return EvidenceRegistry(
        total_count=len(evidence_list),
        evidence_by_id=evidence_by_id,
        debug_stats={
            "ENTITY_MISMATCH_DROPPED": entity_mismatch_dropped,
            "OFF_TARGET_SOURCE_DROPPED": off_target_source_dropped,
            "REGISTRY_REJECT_REASONS": dict(reject_reasons),
        },
    )
