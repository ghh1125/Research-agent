from __future__ import annotations

import json
import re
from collections import Counter

from app.agent.prompts.reason_prompt import LOGIC_GAP_PROMPT_TEMPLATE, REASON_PROMPT_TEMPLATE
from app.models.evidence import Evidence
from app.models.judgment import (
    BearThesis,
    Catalyst,
    ConfidenceBasis,
    EvidenceCluster,
    EvidenceGap,
    Judgment,
    PressureTest,
    ResearchAction,
    RiskItem,
)
from app.models.question import Question
from app.models.topic import Topic
from app.models.variable import ResearchVariable
from app.services.llm_service import call_llm

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_STRONG_JUDGMENT_TOKENS = [
    "已企稳",
    "FCF企稳",
    "形成壁垒",
    "护城河已成立",
    "估值具吸引力",
    "现金流改善确定",
    "费用率见顶",
    "长期ROI确定",
    "具备明确投资价值",
    "明确投资价值",
]


def _collect_theme_hits(evidence: list[Evidence]) -> Counter[str]:
    theme_keywords = {
        "高杠杆": ["资产负债率", "杠杆", "短债"],
        "现金流承压": ["现金流", "回款", "应收账款", "回收慢"],
        "治理或内控薄弱": ["关联交易", "资金占用", "治理", "内控"],
        "客户或业务集中": ["客户集中", "单一客户", "单一业务", "依赖过高", "大客户"],
        "合规边界不清": ["合规", "监管", "牌照", "许可", "经营权", "授权", "整改", "处罚"],
        "经营质量改善": ["订单增长", "毛利率改善", "市场份额提升", "续约率", "研发投入"],
    }
    hits: Counter[str] = Counter()
    for item in evidence:
        for theme, keywords in theme_keywords.items():
            if any(keyword in item.content for keyword in keywords):
                hits[theme] += 1
    return hits


def _validate_evidence_ids(referenced_ids: list[str], evidence_map: dict[str, Evidence]) -> list[str]:
    valid_ids = [
        evidence_id
        for evidence_id in referenced_ids
        if evidence_id in evidence_map
        and evidence_map[evidence_id].can_enter_main_chain
        and not evidence_map[evidence_id].is_truncated
        and not evidence_map[evidence_id].cross_entity_contamination
        and not evidence_map[evidence_id].is_noise
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for evidence_id in valid_ids:
        if evidence_id not in seen:
            deduped.append(evidence_id)
            seen.add(evidence_id)
    return deduped


def _merge_unknowns(primary: list[str], secondary: list[str], limit: int = 3) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in primary + secondary:
        text = str(item).strip()
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
        if len(merged) >= limit:
            break
    return merged


def _build_evidence_gaps(questions: list[Question], evidence: list[Evidence]) -> list[EvidenceGap]:
    if not questions:
        return []

    covered_question_ids = {item.question_id for item in evidence if item.question_id}
    gaps: list[EvidenceGap] = []
    for question in questions:
        coverage_level = getattr(question, "coverage_level", "covered" if question.id in covered_question_ids else "uncovered")
        if coverage_level != "covered":
            if question.priority <= 1:
                importance = "high"
            elif question.priority == 2:
                importance = "medium"
            else:
                importance = "low"
            prefix = "子问题仅部分覆盖" if coverage_level == "partial" else "子问题证据不足"
            gaps.append(
                EvidenceGap(
                    question_id=question.id,
                    text=f"{prefix}：{question.content}",
                    importance=importance,
                )
            )
    return gaps


def _build_gap_unknown_texts(evidence_gaps: list[EvidenceGap]) -> list[str]:
    ordered = sorted(
        evidence_gaps,
        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item.importance, 3),
    )
    return [item.text for item in ordered]


def _select_unknowns(topic: Topic, evidence: list[Evidence], evidence_gaps: list[EvidenceGap]) -> list[str]:
    unknowns = _build_gap_unknown_texts(evidence_gaps)
    if not unknowns:
        unknowns.append("样本覆盖范围仍有限")
    if not any(item.evidence_type == "data" for item in evidence):
        unknowns.append("缺少连续财务或经营数据验证")
    if topic.type == "compliance":
        unknowns.append("关键合同条款、许可文件或监管口径尚未核实")
    elif topic.type == "company" or "值得进一步研究" in topic.query:
        unknowns.append("缺少管理层质量、竞争壁垒和持续增长性的深度验证")
    else:
        unknowns.append("是否存在行业周期或个体特殊因素仍待验证")
    return _merge_unknowns(unknowns, [], limit=3)


def _keyword_cluster_specs(topic: Topic) -> list[tuple[str, list[str], list[str]]]:
    specs = [
        ("高杠杆风险", ["资产负债率", "杠杆", "短债"], ["去杠杆", "债务下降", "杠杆改善"]),
        ("现金流风险", ["现金流", "回款", "应收账款", "回收慢", "票据逾期"], ["现金流转正", "回款改善"]),
        ("治理或内控风险", ["关联交易", "资金占用", "治理", "内控"], ["治理改善", "内控完善"]),
        ("客户或业务集中风险", ["客户集中", "单一客户", "单一业务", "依赖过高", "大客户"], ["客户多元化", "业务多元化"]),
        ("合规风险", ["合规", "监管", "牌照", "许可", "经营权", "授权", "整改", "处罚", "无证经营"], ["合规通过", "牌照齐备", "资质完备"]),
        ("经营改善信号", ["订单增长", "毛利率改善", "市场份额提升", "续约率", "研发投入", "现金流转正"], ["订单下滑", "毛利率下降", "份额流失"]),
    ]
    if topic.type == "compliance":
        return [item for item in specs if item[0] in {"合规风险", "经营改善信号"}] + [item for item in specs if item[0] not in {"合规风险", "经营改善信号"}]
    return specs


def _build_keyword_clusters(topic: Topic, evidence: list[Evidence], evidence_map: dict[str, Evidence]) -> list[EvidenceCluster]:
    clusters: list[EvidenceCluster] = []
    for theme, support_keywords, counter_keywords in _keyword_cluster_specs(topic):
        support_candidates: list[str] = []
        counter_candidates: list[str] = []
        for item in evidence:
            support_hit = any(keyword in item.content for keyword in support_keywords)
            counter_hit = any(keyword in item.content for keyword in counter_keywords)

            if support_hit:
                if item.stance == "counter":
                    counter_candidates.append(item.id)
                else:
                    support_candidates.append(item.id)

            if counter_hit:
                if item.stance == "support":
                    support_candidates.append(item.id)
                else:
                    counter_candidates.append(item.id)

        support_ids = _validate_evidence_ids(support_candidates, evidence_map)
        counter_ids = _validate_evidence_ids(counter_candidates, evidence_map)
        if support_ids or counter_ids:
            clusters.append(
                EvidenceCluster(
                    theme=theme,
                    support_evidence_ids=support_ids,
                    counter_evidence_ids=[item for item in counter_ids if item not in support_ids],
                )
            )
    return clusters


def _merge_clusters(
    primary: list[EvidenceCluster],
    secondary: list[EvidenceCluster],
    evidence_map: dict[str, Evidence],
) -> list[EvidenceCluster]:
    merged_ids: dict[str, dict[str, list[str]]] = {}
    order: list[str] = []

    for cluster in primary + secondary:
        if cluster.theme not in merged_ids:
            merged_ids[cluster.theme] = {"support": [], "counter": []}
            order.append(cluster.theme)
        merged_ids[cluster.theme]["support"].extend(cluster.support_evidence_ids)
        merged_ids[cluster.theme]["counter"].extend(cluster.counter_evidence_ids)

    merged: list[EvidenceCluster] = []
    for theme in order:
        support_ids = _validate_evidence_ids(merged_ids[theme]["support"], evidence_map)
        counter_ids = _validate_evidence_ids(merged_ids[theme]["counter"], evidence_map)
        filtered_counter_ids = [item for item in counter_ids if item not in support_ids]
        if support_ids or filtered_counter_ids:
            merged.append(
                EvidenceCluster(
                    theme=theme,
                    support_evidence_ids=support_ids,
                    counter_evidence_ids=filtered_counter_ids,
                )
            )
    return merged


def _parse_llm_reasoning(
    topic: Topic,
    evidence: list[Evidence],
    questions: list[Question],
    evidence_gaps: list[EvidenceGap],
    evidence_map: dict[str, Evidence],
    variables: list[ResearchVariable] | None = None,
) -> Judgment | None:
    evidence_json = json.dumps(
        [
            {
                "id": item.id,
                "question_id": item.question_id,
                "evidence_type": item.evidence_type,
                "stance": item.stance,
                "flow_type": item.flow_type,
                "source_tier": item.source_tier,
                "evidence_score": item.evidence_score,
                "content": item.content,
            }
            for item in evidence
        ],
        ensure_ascii=False,
    )
    variables_json = json.dumps(
        [
            {
                "name": item.name,
                "category": item.category,
                "direction": item.direction,
                "evidence_ids": item.evidence_ids,
                "value_summary": item.value_summary,
            }
            for item in (variables or [])
        ],
        ensure_ascii=False,
    )
    questions_json = json.dumps(
        [{"id": item.id, "content": item.content} for item in questions],
        ensure_ascii=False,
    )
    prompt = REASON_PROMPT_TEMPLATE.format(
        topic=topic.topic,
        topic_type=topic.type,
        questions_json=questions_json,
        variables_json=variables_json,
        evidence_json=evidence_json,
    )
    try:
        raw = call_llm(prompt, temperature=0.1)
        payload = json.loads(_extract_json_object(raw))
    except Exception:
        return None

    clusters = [
        EvidenceCluster(
            theme=item["theme"],
            support_evidence_ids=_validate_evidence_ids(item.get("support_evidence_ids", []), evidence_map),
            counter_evidence_ids=_validate_evidence_ids(item.get("counter_evidence_ids", []), evidence_map),
        )
        for item in payload.get("clusters", [])
        if item.get("theme")
    ]
    conclusion_evidence_ids = _validate_evidence_ids(payload.get("conclusion_evidence_ids", []), evidence_map)
    risk = [
        RiskItem(
            text=item["text"],
            evidence_ids=_validate_evidence_ids(item.get("evidence_ids", []), evidence_map),
        )
        for item in payload.get("risk", [])
        if item.get("text") and _validate_evidence_ids(item.get("evidence_ids", []), evidence_map)
    ]
    confidence = payload.get("confidence", "low")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    unknown_raw = payload.get("unknown", [])
    unknown = [str(item).strip() for item in unknown_raw if str(item).strip()] if isinstance(unknown_raw, list) else []
    if not conclusion_evidence_ids and evidence:
        return None

    return Judgment(
        topic_id=topic.id,
        conclusion=payload.get("conclusion", "当前证据不足以下结论"),
        conclusion_evidence_ids=conclusion_evidence_ids,
        clusters=clusters,
        risk=risk,
        unknown=unknown or _select_unknowns(topic, evidence, evidence_gaps),
        evidence_gaps=evidence_gaps,
        confidence=confidence,
        confidence_basis=ConfidenceBasis(
            source_count=len({item.source_id for item in evidence}),
            source_diversity="low",
            conflict_level="none",
            evidence_gap_level="high" if any(item.importance == "high" for item in evidence_gaps) else "medium",
            effective_evidence_count=len([item for item in evidence if (item.evidence_score or item.quality_score or 0) >= 0.35]),
            has_official_source=any(item.source_tier == "official" for item in evidence),
            official_evidence_count=len([item for item in evidence if item.source_tier == "official"]),
            weak_source_only=not any(item.source_tier in {"official", "professional"} for item in evidence),
        ),
        research_actions=[],
    )


def _extract_json_object(raw: str) -> str:
    """Extract a JSON object from plain or fenced LLM output."""

    text = raw.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced_match:
        return fenced_match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _build_risk_items(
    evidence_map: dict[str, Evidence],
    clusters: list[EvidenceCluster],
) -> list[RiskItem]:
    risk_items: list[RiskItem] = []
    for cluster in clusters:
        support_ids = _validate_evidence_ids(cluster.support_evidence_ids, evidence_map)
        if support_ids and cluster.theme != "经营改善信号":
            risk_items.append(RiskItem(text=cluster.theme, evidence_ids=support_ids))
    return risk_items[:4]


def _build_conclusion(
    topic: Topic,
    evidence: list[Evidence],
    evidence_map: dict[str, Evidence],
    clusters: list[EvidenceCluster],
) -> tuple[str, list[str]]:
    theme_hits = _collect_theme_hits(evidence)
    top_themes = [theme for theme, _ in theme_hits.most_common(3)]
    positive_ids = _validate_evidence_ids(
        [evidence_id for cluster in clusters if cluster.theme == "经营改善信号" for evidence_id in cluster.support_evidence_ids],
        evidence_map,
    )
    negative_ids = _validate_evidence_ids(
        [
            evidence_id
            for cluster in clusters
            if cluster.theme != "经营改善信号"
            for evidence_id in cluster.support_evidence_ids
        ],
        evidence_map,
    )

    if "值得进一步研究" in topic.query or topic.type == "company":
        if len(positive_ids) >= 2:
            conclusion_ids = _validate_evidence_ids(positive_ids + negative_ids[:1], evidence_map)
            conclusion = (
                f"基于当前证据，{topic.topic}具备进一步研究价值，"
                "因为已经出现经营改善或基本面修复信号，但仍需同步核查治理质量与持续性。"
            )
            return conclusion, conclusion_ids
        conclusion_ids = _validate_evidence_ids(negative_ids or [item.id for item in evidence[:2]], evidence_map)
        conclusion = (
            f"基于当前证据，暂时不能对{topic.topic}形成明确的积极判断，"
            "当前更适合优先核查风险暴露、财务质量和治理情况。"
        )
        return conclusion, conclusion_ids

    if topic.type == "compliance":
        compliance_ids = _validate_evidence_ids(
            [
                evidence_id
                for cluster in clusters
                if cluster.theme == "合规风险"
                for evidence_id in cluster.support_evidence_ids
            ],
            evidence_map,
        )
        conclusion_ids = _validate_evidence_ids(compliance_ids or negative_ids or [item.id for item in evidence[:2]], evidence_map)
        conclusion = (
            f"基于当前证据，{topic.topic}存在需要重点核查的合规边界，"
            "在关键资质、合同安排和监管口径明确前，不宜下强结论。"
        )
        return conclusion, conclusion_ids

    conclusion_ids = _validate_evidence_ids(negative_ids or [item.id for item in evidence[:2]], evidence_map)
    themed_text = "、".join(top_themes[:3] or ["经营承压"])
    conclusion = (
        f"基于当前证据，{topic.topic}的初步判断是：{themed_text}是最值得优先解释的问题，"
        "这些因素往往会共同推动风险暴露。"
    )
    return conclusion, conclusion_ids


def _calculate_confidence(evidence: list[Evidence], clusters: list[EvidenceCluster]) -> str:
    if len(evidence) < 2:
        return "low"

    source_count = len({item.source_id for item in evidence})
    if source_count <= 1:
        # Single-source evidence can easily overstate certainty.
        return "low"

    grounded_ratio = len([item for item in evidence if item.grounded]) / max(len(evidence), 1)
    if grounded_ratio < 0.8:
        return "low"

    support_clusters = [cluster for cluster in clusters if cluster.support_evidence_ids]
    conflict_clusters = [cluster for cluster in support_clusters if cluster.counter_evidence_ids]
    if source_count >= 3 and support_clusters and not conflict_clusters:
        confidence = "medium"
    elif support_clusters:
        confidence = "low"
    else:
        confidence = "low"

    if conflict_clusters and confidence != "low":
        confidence = "low"

    return confidence


def _calculate_confidence_with_questions(
    evidence: list[Evidence],
    clusters: list[EvidenceCluster],
    questions: list[Question],
) -> str:
    confidence = _calculate_confidence(evidence, clusters)
    if not questions:
        return confidence

    covered_question_ids = {item.question_id for item in evidence if item.question_id}
    coverage_ratio = len(covered_question_ids) / len(questions)

    if coverage_ratio < 0.5:
        return "low"
    if coverage_ratio < 0.8 and confidence == "high":
        return "medium"
    return confidence


def _min_confidence(left: str, right: str) -> str:
    if _CONFIDENCE_RANK.get(left, 0) <= _CONFIDENCE_RANK.get(right, 0):
        return left
    return right


def _build_empty_evidence_judgment(topic: Topic, questions: list[Question]) -> Judgment:
    evidence_gaps = _build_evidence_gaps(questions, [])
    unknown = _merge_unknowns(_build_gap_unknown_texts(evidence_gaps), ["当前缺少可用于判断的证据，需要补充资料来源"], limit=3)
    confidence_basis = ConfidenceBasis(
        source_count=0,
        source_diversity="low",
        conflict_level="none",
        evidence_gap_level="high",
        effective_evidence_count=0,
        has_official_source=False,
        official_evidence_count=0,
        weak_source_only=True,
    )
    research_actions = _build_research_actions(evidence_gaps, [], confidence_basis)
    return Judgment(
        topic_id=topic.id,
        conclusion="当前证据不足以下结论",
        conclusion_evidence_ids=[],
        clusters=[],
        risk=[],
        unknown=unknown,
        evidence_gaps=evidence_gaps,
        confidence="low",
        research_confidence="low",
        signal_confidence="low",
        source_confidence="low",
        confidence_basis=confidence_basis,
        research_actions=research_actions,
        bear_theses=[
            BearThesis(
                title="证据不足是当前主要反方逻辑",
                summary="没有可验证证据时，任何积极或消极判断都只能作为待验证假设。",
                evidence_ids=[],
                transmission_path="证据缺失 -> 无法验证核心变量 -> 研究结论无法升级",
                falsify_condition="补充至少两个独立高质量来源，并覆盖高优先级研究问题。",
            )
        ],
        catalysts=[
            Catalyst(
                title="补齐官方或专业来源证据",
                catalyst_type="other",
                timeframe="next_research_round",
                evidence_ids=[],
                why_it_matters="补证结果决定该对象是否值得从初筛进入标准研究。",
            )
        ],
        positioning="信息不足，待补证",
    )


def _gap_level(evidence_gaps: list[EvidenceGap]) -> str:
    if not evidence_gaps:
        return "low"
    if any(item.importance == "high" for item in evidence_gaps):
        return "high"
    if any(item.importance == "medium" for item in evidence_gaps):
        return "medium"
    return "low"


def _build_confidence_basis(
    evidence: list[Evidence],
    clusters: list[EvidenceCluster],
    evidence_gaps: list[EvidenceGap],
    topic: Topic | None = None,
) -> ConfidenceBasis:
    source_count = len({item.source_id for item in evidence})
    if source_count <= 1:
        source_diversity = "low"
    elif source_count == 2:
        source_diversity = "medium"
    else:
        source_diversity = "high"

    conflict_clusters = [item for item in clusters if item.support_evidence_ids and item.counter_evidence_ids]
    if not conflict_clusters:
        conflict_level = "none"
    elif len(conflict_clusters) == 1:
        conflict_level = "partial"
    else:
        conflict_level = "strong"

    effective_evidence_count = len([item for item in evidence if (item.evidence_score or item.quality_score or 0) >= 0.35])
    official_evidence_count = len([item for item in evidence if item.source_tier == "official"])
    has_official_source = official_evidence_count > 0
    has_professional_or_official = any(item.source_tier in {"official", "professional"} for item in evidence)
    weak_source_only = bool(evidence) and not has_professional_or_official
    if topic is not None and (topic.type == "company" or topic.entity) and not has_official_source:
        weak_source_only = True

    return ConfidenceBasis(
        source_count=source_count,
        source_diversity=source_diversity,
        conflict_level=conflict_level,
        evidence_gap_level=_gap_level(evidence_gaps),
        effective_evidence_count=effective_evidence_count,
        has_official_source=has_official_source,
        official_evidence_count=official_evidence_count,
        weak_source_only=weak_source_only,
    )


def _apply_confidence_basis(base_confidence: str, confidence_basis: ConfidenceBasis) -> str:
    confidence = base_confidence
    if confidence_basis.source_diversity == "low":
        confidence = _min_confidence(confidence, "low")
    if confidence_basis.effective_evidence_count < 3:
        confidence = _min_confidence(confidence, "low")
    if confidence_basis.weak_source_only:
        confidence = _min_confidence(confidence, "low")
    if confidence_basis.conflict_level == "strong":
        confidence = _min_confidence(confidence, "low")
    elif confidence_basis.conflict_level == "partial":
        confidence = _min_confidence(confidence, "medium")
    if confidence_basis.evidence_gap_level == "high":
        confidence = _min_confidence(confidence, "medium")
    elif confidence_basis.evidence_gap_level == "medium":
        confidence = _min_confidence(confidence, "medium")
    return confidence


def _calculate_confidence_layers(
    confidence_basis: ConfidenceBasis,
    evidence: list[Evidence],
    clusters: list[EvidenceCluster],
) -> tuple[str, str, str]:
    if confidence_basis.source_diversity == "high" and confidence_basis.has_official_source:
        source_confidence = "high"
    elif confidence_basis.source_diversity in {"medium", "high"} and not confidence_basis.weak_source_only:
        source_confidence = "medium"
    else:
        source_confidence = "low"

    if confidence_basis.evidence_gap_level == "low" and confidence_basis.effective_evidence_count >= 6:
        research_confidence = "high"
    elif confidence_basis.evidence_gap_level != "high" and confidence_basis.effective_evidence_count >= 3:
        research_confidence = "medium"
    else:
        research_confidence = "low"

    support_clusters = [cluster for cluster in clusters if cluster.support_evidence_ids]
    if (
        len(support_clusters) >= 3
        and confidence_basis.conflict_level == "none"
        and confidence_basis.effective_evidence_count >= 5
    ):
        signal_confidence = "high"
    elif support_clusters and confidence_basis.conflict_level != "strong" and len(evidence) >= 3:
        signal_confidence = "medium"
    else:
        signal_confidence = "low"
    return research_confidence, signal_confidence, source_confidence


def _build_bear_theses(
    topic: Topic,
    judgment: Judgment,
    evidence_map: dict[str, Evidence],
    pressure_tests: list[PressureTest],
) -> list[BearThesis]:
    theses: list[BearThesis] = []
    for risk in judgment.risk[:2]:
        ids = _validate_evidence_ids(risk.evidence_ids, evidence_map)
        if not ids:
            continue
        theses.append(
            BearThesis(
                title=f"反方逻辑：{risk.text}",
                summary=f"如果{risk.text}继续被更多来源验证，{topic.topic}的研究优先级应被下调或至少延后。",
                evidence_ids=ids,
                transmission_path=f"{risk.text} -> 核心变量恶化 -> 研究结论降级",
                falsify_condition="后续官方披露或专业来源显示该风险已缓解，且关键经营/财务变量同步改善。",
            )
        )

    for test in pressure_tests:
        if len(theses) >= 3:
            break
        ids = _validate_evidence_ids(test.fragile_evidence_ids + test.counter_evidence_ids, evidence_map)
        if test.attack_type == "evidence_gap":
            ids = []
        if test.attack_type == "logic_gap":
            title = "反方逻辑：结论推导存在跳跃"
        elif test.attack_type == "weak_source":
            title = "反方逻辑：结论依赖弱来源"
        elif test.attack_type == "evidence_gap":
            title = "反方逻辑：关键证据缺口未覆盖"
        else:
            title = f"反方逻辑：{test.weakness[:18]}"
        theses.append(
            BearThesis(
                title=title,
                summary=test.weakness,
                evidence_ids=ids,
                transmission_path=test.counter_conclusion,
                falsify_condition="补齐对应高质量证据，并证明该压力测试不再成立。",
            )
        )

    if not theses and judgment.conclusion_evidence_ids:
        ids = _validate_evidence_ids(judgment.conclusion_evidence_ids[:2], evidence_map)
        theses.append(
            BearThesis(
                title="反方逻辑：正向证据仍需交叉验证",
                summary="当前结论虽有证据支撑，但若这些证据不能被官方或专业来源交叉验证，研究强度不能提升。",
                evidence_ids=ids,
                transmission_path="证据未交叉验证 -> 结论稳健性不足 -> 保持观察或补证",
                falsify_condition="出现多来源一致的官方披露、结构化数据或同行参照。",
            )
        )
    return theses[:3]


def _period_scope_notes(evidence: list[Evidence]) -> list[str]:
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for item in evidence:
        if not item.metric_name or not item.period:
            continue
        key = (
            item.metric_name.strip().lower(),
            (item.segment or "group").strip().lower(),
            (item.comparison_type or "reported").strip().lower(),
        )
        grouped.setdefault(key, set()).add(str(item.period).strip())

    notes: list[str] = []
    for (metric_name, segment, comparison_type), periods in grouped.items():
        if len(periods) <= 1:
            continue
        ordered_periods = ", ".join(sorted(periods))
        notes.append(
            f"同一指标 {metric_name}（scope={segment}, basis={comparison_type}）存在不同期间数据：{ordered_periods}；"
            "不能直接判定为趋势冲突，需先做期间/口径归一。"
        )
    return notes[:3]


def _is_high_quality_conclusion_evidence(item: Evidence) -> bool:
    return (
        item.source_tier in {"official", "professional"}
        and item.evidence_type == "data"
        and not item.is_noise
        and not item.is_truncated
        and (item.evidence_score or item.quality_score or 0) >= 0.35
    )


def _build_verified_facts(conclusion_ids: list[str], evidence_map: dict[str, Evidence]) -> list[str]:
    facts: list[str] = []
    for evidence_id in conclusion_ids:
        item = evidence_map.get(evidence_id)
        if item is None or not _is_high_quality_conclusion_evidence(item):
            continue
        label = item.metric_name or "evidence"
        period = f"（{item.period}）" if item.period else ""
        facts.append(f"{label}{period}: {item.content}")
        if len(facts) >= 5:
            break
    return facts


def _has_uncovered_core_question(evidence_gaps: list[EvidenceGap]) -> bool:
    return any(gap.importance in {"high", "medium"} for gap in evidence_gaps)


def _sanitize_strong_conclusion(conclusion: str, evidence_gaps: list[EvidenceGap]) -> tuple[str, list[str]]:
    if not _has_uncovered_core_question(evidence_gaps):
        return conclusion, []
    matched = [token for token in _STRONG_JUDGMENT_TOKENS if token in conclusion]
    if not matched:
        return conclusion, []
    pending = [
        "强判断已降级："
        + "、".join(dict.fromkeys(matched))
        + " 只能进入待验证前提，不能进入一句话主结论。"
    ]
    downgraded = "当前证据只能支持初筛观察；估值、现金流拐点、费用率和长期壁垒等仍属于待验证前提。"
    return downgraded, pending


def _build_judgment_layers(
    conclusion: str,
    conclusion_ids: list[str],
    evidence_map: dict[str, Evidence],
    evidence_gaps: list[EvidenceGap],
) -> tuple[str, list[str], list[str], list[str]]:
    conclusion, downgrade_notes = _sanitize_strong_conclusion(conclusion, evidence_gaps)
    verified_facts = _build_verified_facts(conclusion_ids, evidence_map)
    pending_assumptions = downgrade_notes + _period_scope_notes(list(evidence_map.values()))
    pending_assumptions.extend(gap.text for gap in evidence_gaps[:3])
    probable_inferences = []
    if conclusion_ids and not downgrade_notes:
        probable_inferences.append(conclusion)
    return (
        conclusion,
        verified_facts[:5],
        probable_inferences[:3],
        list(dict.fromkeys(pending_assumptions))[:6],
    )


def _build_catalysts(topic: Topic, evidence: list[Evidence], evidence_map: dict[str, Evidence]) -> list[Catalyst]:
    object_type = getattr(topic, "research_object_type", "unknown")
    candidates: list[Catalyst] = []
    for item in evidence:
        text = item.content
        if any(token in text for token in ["财报", "季报", "年报", "earnings", "业绩", "指引"]):
            candidates.append(
                Catalyst(
                    title="财报或业绩披露",
                    catalyst_type="earnings",
                    timeframe="next_1_2_quarters",
                    evidence_ids=[item.id],
                    why_it_matters="财报能验证收入、利润率、现金流和管理层指引是否支撑当前判断。",
                )
            )
        elif any(token in text for token in ["产品", "发布", "订单", "客户", "技术"]):
            candidates.append(
                Catalyst(
                    title="产品、订单或客户进展",
                    catalyst_type="product",
                    timeframe="next_6_12_months",
                    evidence_ids=[item.id],
                    why_it_matters="产品和订单变化能验证商业模式、增长质量和竞争位置。",
                )
            )
        elif any(token in text for token in ["政策", "监管", "许可", "处罚", "合规"]):
            candidates.append(
                Catalyst(
                    title="政策或监管变化",
                    catalyst_type="policy",
                    timeframe="next_6_12_months",
                    evidence_ids=[item.id],
                    why_it_matters="政策和监管口径会改变合规边界、行业空间或风险暴露。",
                )
            )
        elif any(token in text for token in ["债", "评级", "再融资", "到期"]):
            candidates.append(
                Catalyst(
                    title="债务到期、再融资或评级变化",
                    catalyst_type="rating" if "评级" in text else "refinancing",
                    timeframe="next_6_12_months",
                    evidence_ids=[item.id],
                    why_it_matters="信用主体的再融资和评级变化会直接影响偿债风险判断。",
                )
            )
        if len(candidates) >= 3:
            break

    if candidates:
        deduped: list[Catalyst] = []
        seen: set[str] = set()
        for item in candidates:
            key = f"{item.title}:{item.catalyst_type}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:3]

    default_title = {
        "listed_company": "下一次财报、指引或资本动作",
        "private_company": "融资、产品和关键客户进展",
        "industry_theme": "政策、价格或技术拐点",
        "macro_theme": "官方数据和政策会议",
        "credit_issuer": "债务到期、再融资和评级变化",
        "concept_theme": "政策和资金面催化",
        "fund_etf": "指数调仓、持仓变化和资金流",
        "commodity": "库存、供需和价格拐点",
    }.get(object_type, "下一轮关键证据更新")
    default_type = "rating" if object_type == "credit_issuer" else "policy" if object_type in {"industry_theme", "macro_theme"} else "other"
    return [
        Catalyst(
            title=default_title,
            catalyst_type=default_type,
            timeframe="next_6_12_months",
            evidence_ids=[],
            why_it_matters="该触发因素决定当前研究线索是否能从初筛升级为标准研究。",
        )
    ]


def _build_positioning(topic: Topic, confidence: str, confidence_basis: ConfidenceBasis, pressure_tests: list[PressureTest]) -> str:
    object_type = getattr(topic, "research_object_type", "unknown")
    has_high_gap = confidence_basis.evidence_gap_level == "high"
    has_high_pressure = any(
        test.severity == "high" and test.attack_type != "evidence_gap"
        for test in pressure_tests
    )
    if has_high_pressure and confidence == "low":
        return "风险过高，暂缓研究"
    if has_high_gap or confidence_basis.effective_evidence_count < 3:
        return "信息不足，待补证"
    if object_type in {"industry_theme", "macro_theme", "event"}:
        return "值得建立跟踪" if confidence in {"medium", "high"} else "等待关键触发点"
    if object_type in {"concept_theme", "fund_etf", "commodity"}:
        return "等待关键触发点" if confidence == "low" else "值得建立跟踪"
    if confidence == "medium":
        return "值得进入标准研究"
    if confidence == "high":
        return "值得深挖"
    return "等待关键触发点"


def _validate_judgment(
    topic: Topic,
    judgment: Judgment,
    evidence_map: dict[str, Evidence],
    confidence_basis: ConfidenceBasis,
) -> Judgment:
    """Ensure all judgment references point to real evidence ids."""

    conclusion_ids = _validate_evidence_ids(judgment.conclusion_evidence_ids, evidence_map)
    clusters = [
        EvidenceCluster(
            theme=cluster.theme,
            support_evidence_ids=_validate_evidence_ids(cluster.support_evidence_ids, evidence_map),
            counter_evidence_ids=_validate_evidence_ids(cluster.counter_evidence_ids, evidence_map),
        )
        for cluster in judgment.clusters
    ]
    clusters = [cluster for cluster in clusters if cluster.support_evidence_ids or cluster.counter_evidence_ids]

    risk = [
        RiskItem(text=item.text, evidence_ids=_validate_evidence_ids(item.evidence_ids, evidence_map))
        for item in judgment.risk
    ]
    risk = [item for item in risk if item.evidence_ids]

    conclusion = judgment.conclusion
    pressure_tests = _build_pressure_tests(judgment, evidence_map, judgment.evidence_gaps)
    confidence = judgment.confidence
    if not conclusion_ids:
        conclusion = "当前证据不足以支撑明确结论"
        confidence = "low"

    confidence = _apply_confidence_basis(confidence, confidence_basis)
    high_impact_attacks = {"fragile_evidence", "weak_source"}
    medium_impact_attacks = {"ignored_counter_evidence", "evidence_gap", "logic_gap"}
    if any(item.severity == "high" and item.attack_type in high_impact_attacks for item in pressure_tests):
        confidence = _min_confidence(confidence, "low")
    elif any(
        item.attack_type in medium_impact_attacks and item.severity in {"medium", "high"}
        for item in pressure_tests
    ):
        confidence = _min_confidence(confidence, "medium")
    if confidence == "high":
        confidence = "medium"
    research_confidence, signal_confidence, source_confidence = _calculate_confidence_layers(
        confidence_basis,
        list(evidence_map.values()),
        clusters,
    )
    bear_theses = _build_bear_theses(topic, judgment, evidence_map, pressure_tests)
    catalysts = _build_catalysts(topic, list(evidence_map.values()), evidence_map)
    positioning = _build_positioning(topic, confidence, confidence_basis, pressure_tests)
    conclusion, verified_facts, probable_inferences, pending_assumptions = _build_judgment_layers(
        conclusion,
        conclusion_ids,
        evidence_map,
        judgment.evidence_gaps,
    )

    return judgment.model_copy(
        update={
            "conclusion": conclusion,
            "conclusion_evidence_ids": conclusion_ids,
            "verified_facts": verified_facts,
            "probable_inferences": probable_inferences,
            "pending_assumptions": pending_assumptions,
            "clusters": clusters,
            "risk": risk,
            "pressure_tests": pressure_tests,
            "confidence": confidence,
            "research_confidence": research_confidence,
            "signal_confidence": signal_confidence,
            "source_confidence": source_confidence,
            "confidence_basis": confidence_basis,
            "bear_theses": bear_theses,
            "catalysts": catalysts,
            "positioning": positioning,
        }
    )


def _build_pressure_tests(
    judgment: Judgment,
    evidence_map: dict[str, Evidence],
    evidence_gaps: list[EvidenceGap],
) -> list[PressureTest]:
    """Attack the judgment directly instead of asking another role to role-play."""

    tests: list[PressureTest] = []
    conclusion_ids = _validate_evidence_ids(judgment.conclusion_evidence_ids, evidence_map)
    fragile_ids = [
        evidence_id
        for evidence_id in conclusion_ids
        if (
            (evidence_map[evidence_id].evidence_score or evidence_map[evidence_id].quality_score or 0) < 0.45
            or evidence_map[evidence_id].source_tier == "content"
        )
    ]
    if fragile_ids:
        tests.append(
            PressureTest(
                test_id=f"pt{len(tests) + 1}",
                attack_type="fragile_evidence",
                target="conclusion",
                fragile_evidence_ids=fragile_ids[:5],
                weakness="部分结论证据来自低分证据或 content 来源，如果这些证据不可采，结论支撑会明显变弱。",
                counter_conclusion="仅凭当前低质量证据，最多只能形成待核查线索，不能形成强判断。",
                severity="high" if len(fragile_ids) == len(conclusion_ids) else "medium",
            )
        )

    cluster_counter_ids = _validate_evidence_ids(
        [evidence_id for cluster in judgment.clusters for evidence_id in cluster.counter_evidence_ids],
        evidence_map,
    )
    ignored_counter_ids = [item for item in cluster_counter_ids if item not in conclusion_ids]
    if ignored_counter_ids:
        tests.append(
            PressureTest(
                test_id=f"pt{len(tests) + 1}",
                attack_type="ignored_counter_evidence",
                target="conclusion",
                counter_evidence_ids=ignored_counter_ids[:5],
                weakness="当前结论没有充分吸收已识别反证，可能高估单一方向证据。",
                counter_conclusion="如果只看反证，结论应降级为存在冲突、需要继续核查。",
                severity="medium",
            )
        )

    high_gaps = [gap for gap in evidence_gaps if gap.importance == "high"]
    if high_gaps:
        tests.append(
            PressureTest(
                test_id=f"pt{len(tests) + 1}",
                attack_type="evidence_gap",
                target="research_frame",
                weakness="高优先级研究问题尚未被证据覆盖，当前判断存在结构性缺口。",
                counter_conclusion="在关键问题未覆盖前，判断只能作为初筛结果，不能作为深度研究结论。",
                severity="high",
            )
        )

    if conclusion_ids and all(evidence_map[evidence_id].source_tier == "content" for evidence_id in conclusion_ids):
        tests.append(
            PressureTest(
                test_id=f"pt{len(tests) + 1}",
                attack_type="weak_source",
                target="source_quality",
                fragile_evidence_ids=conclusion_ids[:5],
                weakness="结论证据全部来自 content 来源，缺少官方披露或专业来源交叉验证。",
                counter_conclusion="当前更适合进入补证流程，而不是提升研究置信度。",
                severity="high",
            )
        )

    logic_gap_test = _build_logic_gap_pressure_test(judgment, conclusion_ids, evidence_map, len(tests) + 1)
    if logic_gap_test is not None:
        tests.append(logic_gap_test)

    return tests[:4]


def _build_logic_gap_pressure_test(
    judgment: Judgment,
    conclusion_ids: list[str],
    evidence_map: dict[str, Evidence],
    index: int,
) -> PressureTest | None:
    if not conclusion_ids:
        return None

    evidence_json = json.dumps(
        [
            {
                "id": evidence_id,
                "source_tier": evidence_map[evidence_id].source_tier,
                "evidence_score": evidence_map[evidence_id].evidence_score,
                "content": evidence_map[evidence_id].content,
            }
            for evidence_id in conclusion_ids
            if evidence_id in evidence_map
        ],
        ensure_ascii=False,
    )
    prompt = LOGIC_GAP_PROMPT_TEMPLATE.format(
        conclusion=judgment.conclusion,
        evidence_json=evidence_json,
    )
    try:
        raw = call_llm(prompt, temperature=0.0)
        payload = json.loads(_extract_json_object(raw))
    except Exception:
        return None

    if not payload.get("has_logic_gap"):
        return None

    severity = str(payload.get("severity", "medium")).lower()
    if severity not in {"low", "medium", "high"}:
        severity = "medium"

    return PressureTest(
        test_id=f"pt{index}",
        attack_type="logic_gap",
        target="reasoning_chain",
        fragile_evidence_ids=conclusion_ids[:5],
        weakness=str(payload.get("weakness", "结论与证据之间存在未说明的推理前提。")).strip(),
        counter_conclusion=str(payload.get("counter_conclusion", "结论应降级为待验证判断。")).strip(),
        severity=severity,
    )


def _build_research_actions(
    evidence_gaps: list[EvidenceGap],
    risk: list[RiskItem],
    confidence_basis: ConfidenceBasis,
) -> list[ResearchAction]:
    def _priority(importance: str) -> str:
        return "high" if importance == "high" else "medium" if importance == "medium" else "low"

    def _required_data(text: str) -> list[str]:
        data: list[str] = []
        if any(token in text for token in ["财务", "现金流", "利润", "收入", "财报"]):
            data.extend(["营业收入", "同比增速", "净利润", "毛利率", "经营现金流", "资本开支", "自由现金流"])
        if any(token in text for token in ["行业", "竞争", "同行", "份额"]):
            data.extend(["市场份额", "同行对比", "同行增速", "毛利率对比", "估值倍数"])
        if any(token in text for token in ["合规", "监管", "治理", "处罚"]):
            data.extend(["监管处罚记录", "公告披露", "治理与内控信息"])
        return list(dict.fromkeys(data or ["官方披露", "关键经营数据", "专业来源交叉验证"]))

    def _query_templates(text: str) -> list[str]:
        if any(token in text for token in ["财务", "现金流", "利润", "收入", "财报"]):
            return [
                "{entity} annual report operating cash flow capex free cash flow",
                "{entity} 年报 营业收入 净利润 毛利率 资本开支 自由现金流",
                "{entity} investor relations revenue gross margin net income cash flow capex",
            ]
        if any(token in text for token in ["合规", "监管", "治理", "处罚"]):
            return [
                "{entity} 监管 处罚 合规 风险",
                "{entity} 公司治理 内控 关联交易",
                "{entity} regulatory filing governance risk",
            ]
        return [
            "{entity} 官方公告 财报 关键数据",
            "{entity} market share peer comparison gross margin valuation multiple",
            "{entity} 行业竞争 市场份额 同行排名",
        ]

    actions: list[ResearchAction] = []

    sorted_gaps = sorted(
        evidence_gaps,
        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(item.importance, 3),
    )
    for gap in sorted_gaps:
        objective = (
            gap.text.replace("子问题证据不足：", "")
            .replace("子问题仅部分覆盖：", "")
            .strip()
            or "补齐关键证据缺口"
        )
        query_templates = _query_templates(objective)
        source_targets = ["official filings", "investor relations", "recognized data providers"]
        actions.append(
            ResearchAction(
                id=f"a{len(actions) + 1}",
                priority=_priority(gap.importance),
                question=objective,
                objective=objective,
                reason=f"该缺口重要性为{gap.importance}，直接影响判断确定性",
                required_data=_required_data(objective),
                search_query=query_templates[0],
                query_templates=query_templates,
                target_sources=source_targets,
                source_targets=source_targets,
                question_id=gap.question_id,
            )
        )
        if len(actions) >= 3:
            return actions

    if risk:
        for item in risk[:2]:
            query_templates = _query_templates(item.text)
            source_targets = ["official filings", "professional finance media", "recognized data providers"]
            actions.append(
                ResearchAction(
                    id=f"a{len(actions) + 1}",
                    priority="medium",
                    question=f"如何独立验证风险项：{item.text}",
                    objective=f"专项核查：{item.text}",
                    reason="该风险已有证据支持，建议补充更多独立来源交叉验证",
                    required_data=_required_data(item.text),
                    search_query=query_templates[0],
                    query_templates=query_templates,
                    target_sources=source_targets,
                    source_targets=source_targets,
                )
            )
            if len(actions) >= 3:
                return actions

    if not actions:
        query_templates = [
            "{entity} annual report operating cash flow capex free cash flow",
            "{entity} investor relations annual report quarterly results revenue margin",
            "{entity} market share peer comparison valuation multiple",
        ]
        source_targets = ["official filings", "investor relations", "recognized data providers"]
        actions.append(
            ResearchAction(
                id="a1",
                priority="medium" if confidence_basis.evidence_gap_level != "low" else "low",
                question="如何补齐官方来源、核心财务指标和同行参照",
                objective="扩展来源并补充关键经营与财务数据",
                reason=f"当前来源独立性为{confidence_basis.source_diversity}，证据缺口等级为{confidence_basis.evidence_gap_level}",
                required_data=["官方财报", "营业收入", "净利润", "毛利率", "经营现金流", "资本开支", "同行或行业参照"],
                search_query=query_templates[0],
                query_templates=query_templates,
                target_sources=source_targets,
                source_targets=source_targets,
            )
        )

    return actions


def reason_and_generate(
    topic: Topic,
    evidence: list[Evidence],
    questions: list[Question],
    variables: list[ResearchVariable] | None = None,
) -> Judgment:
    """Generate a bounded judgment based on extracted evidence."""

    if not evidence:
        return _build_empty_evidence_judgment(topic, questions)

    evidence_map = {item.id: item for item in evidence}
    evidence_gaps = _build_evidence_gaps(questions, evidence)
    keyword_clusters = _build_keyword_clusters(topic, evidence, evidence_map)
    llm_judgment = _parse_llm_reasoning(topic, evidence, questions, evidence_gaps, evidence_map, variables)

    if llm_judgment is not None:
        merged_clusters = _merge_clusters(llm_judgment.clusters, keyword_clusters, evidence_map)
        conclusion_evidence_ids = _validate_evidence_ids(llm_judgment.conclusion_evidence_ids, evidence_map)
        if not conclusion_evidence_ids:
            conclusion_evidence_ids = _validate_evidence_ids([item.id for item in evidence[:2]], evidence_map)

        risk = llm_judgment.risk or _build_risk_items(evidence_map, merged_clusters)
        if not risk and evidence:
            fallback_ids = _validate_evidence_ids([item.id for item in evidence[:2]], evidence_map)
            if fallback_ids:
                fallback_text = "合规风险待核实" if topic.type == "compliance" else "风险信号仍需继续核实"
                risk = [RiskItem(text=fallback_text, evidence_ids=fallback_ids)]

        unknown = _merge_unknowns(llm_judgment.unknown, _select_unknowns(topic, evidence, evidence_gaps), limit=3)
        deterministic_confidence = _calculate_confidence_with_questions(evidence, merged_clusters, questions)
        confidence_basis = _build_confidence_basis(evidence, merged_clusters, evidence_gaps, topic)
        confidence = _apply_confidence_basis(deterministic_confidence, confidence_basis)
        research_actions = _build_research_actions(evidence_gaps, risk, confidence_basis)

        judgment = Judgment(
            topic_id=topic.id,
            conclusion=llm_judgment.conclusion,
            conclusion_evidence_ids=conclusion_evidence_ids,
            clusters=merged_clusters,
            risk=risk,
            unknown=unknown,
            evidence_gaps=evidence_gaps,
            confidence=confidence,
            confidence_basis=confidence_basis,
            research_actions=research_actions,
        )
        return _validate_judgment(topic, judgment, evidence_map, confidence_basis)

    conclusion, conclusion_evidence_ids = _build_conclusion(topic, evidence, evidence_map, keyword_clusters)
    validated_conclusion_ids = _validate_evidence_ids(conclusion_evidence_ids, evidence_map)
    if not validated_conclusion_ids:
        fallback_ids = _validate_evidence_ids([item.id for item in evidence[:2]], evidence_map)
        validated_conclusion_ids = fallback_ids

    risk = _build_risk_items(evidence_map, keyword_clusters)
    if not risk and evidence:
        fallback_ids = _validate_evidence_ids([item.id for item in evidence[:2]], evidence_map)
        if fallback_ids:
            fallback_text = "合规风险待核实" if topic.type == "compliance" else "风险信号仍需继续核实"
            risk = [RiskItem(text=fallback_text, evidence_ids=fallback_ids)]
    unknown = _select_unknowns(topic, evidence, evidence_gaps)
    confidence_basis = _build_confidence_basis(evidence, keyword_clusters, evidence_gaps, topic)
    confidence = _apply_confidence_basis(
        _calculate_confidence_with_questions(evidence, keyword_clusters, questions),
        confidence_basis,
    )
    research_actions = _build_research_actions(evidence_gaps, risk, confidence_basis)
    judgment = Judgment(
        topic_id=topic.id,
        conclusion=conclusion,
        conclusion_evidence_ids=validated_conclusion_ids,
        clusters=keyword_clusters,
        risk=risk,
        unknown=unknown,
        evidence_gaps=evidence_gaps,
        confidence=confidence,
        confidence_basis=confidence_basis,
        research_actions=research_actions,
    )
    return _validate_judgment(topic, judgment, evidence_map, confidence_basis)
