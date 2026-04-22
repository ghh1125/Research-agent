from __future__ import annotations

from hashlib import md5

from app.models.evidence import Evidence
from app.models.judgment import Judgment
from app.models.question import Question
from app.models.report import ReportSection, ResearchReport
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.models.topic import Topic
from app.models.variable import ResearchVariable

FRAMEWORK_LABELS = {
    "financial": "财务质量",
    "credit": "偿债与现金流",
    "valuation": "估值锚点",
    "business_model": "商业模式",
    "industry": "行业竞争",
    "moat": "竞争壁垒",
    "risk": "风险信号",
    "governance": "治理合规",
    "compliance": "合规风险",
    "adversarial": "反方检验",
    "catalyst": "催化剂",
    "gap": "证据缺口",
    "general": "综合问题",
}

CATEGORY_LABELS = {
    "financial": "财务",
    "operation": "经营",
    "industry": "行业",
    "governance": "治理",
    "valuation": "估值",
    "risk": "风险",
}

DIRECTION_LABELS = {
    "improving": "改善",
    "deteriorating": "恶化",
    "stable": "稳定",
    "mixed": "信号分化",
    "unknown": "方向不明",
}

CONFIDENCE_LABELS = {
    "high": "高置信度",
    "medium": "中等置信度",
    "low": "低置信度，结论仅供参考",
}

DECISION_TARGET_LABELS = {
    "research_priority": "研究优先级",
    "deep_research_entry": "深度研究入口",
    "watchlist_entry": "观察清单",
    "research_action": "研究动作",
    "theme_tracking": "主题跟踪",
    "credit_review": "信用复核",
}

DECISION_LABELS = {
    "deep_dive_candidate": "建议进入深度研究",
    "watchlist": "列入观察清单",
    "deprioritize": "暂缓投入研究",
    "establish_tracking": "建立跟踪",
    "monitor_for_trigger": "等待触发信号",
    "enter_credit_review": "进入信用复核",
    "high_risk_watch": "高风险观察",
    "thematic_watch": "主题观察",
}

PRESSURE_LABELS = {
    "fragile_evidence": "结论依赖的证据仍偏脆弱",
    "ignored_counter_evidence": "反证尚未被充分吸收",
    "evidence_gap": "关键问题缺乏证据覆盖",
    "weak_source": "来源质量不足",
    "logic_gap": "逻辑推断存在跳跃",
}

SEVERITY_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}

CONFLICT_LABELS = {
    "none": "未见明显冲突",
    "partial": "存在部分冲突",
    "strong": "存在强冲突",
}

SOURCE_ORIGIN_LABELS = {
    "official_disclosure": "官方披露",
    "company_ir": "公司投资者关系",
    "regulatory": "监管来源",
    "professional_media": "专业数据或财经来源",
    "research_media": "研究类来源",
    "aggregator": "聚合转载",
    "community": "社区讨论",
    "self_media": "自媒体",
    "unknown": "未知来源",
}

TIER_LABELS = {
    "official": "官方来源",
    "professional": "专业来源",
    "content": "普通内容来源",
}

OBJECT_TYPE_LABELS = {
    "listed_company": "上市公司",
    "private_company": "非上市公司",
    "industry_theme": "行业主题",
    "credit_issuer": "信用主体",
    "macro_theme": "宏观主题",
    "event": "事件",
    "concept_theme": "概念主题",
    "fund_etf": "基金或 ETF",
    "commodity": "大宗商品",
    "unknown": "未识别",
}

LISTING_STATUS_LABELS = {
    "listed": "已上市",
    "private": "未上市公司",
    "unlisted": "未上市",
    "not_applicable": "不适用",
    "concept": "概念主题",
    "asset": "资产",
    "unknown": "未知",
}

MARKET_TYPE_LABELS = {
    "A_share": "A 股",
    "HK": "港股",
    "US": "美股",
    "bond": "债券",
    "private": "非上市",
    "thematic": "主题",
    "macro": "宏观",
    "commodity": "商品",
    "fund": "基金",
    "other": "其他",
}

ACTION_STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "done": "已完成",
    "skipped": "已跳过",
}

PRIORITY_LABELS = {
    "high": "高优先级",
    "medium": "中优先级",
    "low": "低优先级",
}


def _label(mapping: dict[str, str], value: str | None) -> str:
    if value is None:
        return "无"
    return mapping.get(value, value)


def _humanize_text(text: str | None) -> str:
    if not text:
        return "无"
    replacements = {
        "deep_dive_candidate": "建议进入深度研究",
        "watchlist": "观察清单",
        "deprioritize": "暂缓投入研究",
        "watchlist_entry": "观察清单",
        "research_priority": "研究优先级",
        "deep_research_entry": "深度研究入口",
        "peer_context=covered": "同行参照已覆盖",
        "peer_context=needs_research": "同行参照仍需补充",
        "confidence=low": "低置信度",
        "confidence=medium": "中等置信度",
        "confidence=high": "高置信度",
        "weak_source_only=True": "当前存在弱来源占比较高的问题",
        "weak_source_only=False": "来源质量未触发弱来源单一警告",
        "quick_screen": "快速初筛",
        "standard_research": "标准研究",
        "deep_dive": "深度研究",
        "needs_research": "仍需补充研究",
        "covered": "已覆盖",
        "not_applicable": "不适用",
        "pending_review": "待人工复核",
        "approved": "已复核通过",
        "rejected": "已驳回",
        "overridden": "已人工覆盖",
    }
    output = str(text)
    for raw, label in replacements.items():
        output = output.replace(raw, label)
    return output


def _build_background_section(topic: Topic) -> ReportSection:
    entity_text = topic.entity or "未显式指定"
    body = (
        f"用户问题：{topic.query}\n"
        f"结构化主题：{topic.topic}\n"
        f"研究目标：{topic.goal}\n"
        f"研究对象：{entity_text}\n"
        f"对象类型：{_label(OBJECT_TYPE_LABELS, getattr(topic, 'research_object_type', 'unknown'))}\n"
        f"上市状态：{_label(LISTING_STATUS_LABELS, topic.listing_status)}\n"
        f"市场类型：{_label(MARKET_TYPE_LABELS, getattr(topic, 'market_type', 'other'))}\n"
        f"边界说明：{topic.listing_note or '无'}"
    )
    return ReportSection(
        title="研究问题",
        body=body,
        evidence_ids=[],
        section_type="background",
    )


def _build_framework_section(questions: list[Question]) -> ReportSection:
    coverage_label = {
        "covered": "已覆盖",
        "partial": "部分覆盖",
        "uncovered": "待补证",
    }
    lines = [
        f"P{item.priority} - {_label(FRAMEWORK_LABELS, item.framework_type)} - {coverage_label.get(item.coverage_level, '待补证')} - {item.content}"
        for item in questions
    ]
    body = "\n".join(lines) if lines else "暂无可执行的研究子问题。"
    return ReportSection(
        title="研究框架",
        body=body,
        evidence_ids=[],
        section_type="framework",
    )


def _build_source_governance_section(sources: list[Source], evidence: list[Evidence]) -> ReportSection:
    groups = {
        "官方来源": [item for item in sources if item.tier.value == "official"],
        "专业来源": [item for item in sources if item.tier.value == "professional"],
        "弱来源": [item for item in sources if item.tier.value == "content"],
    }
    evidence_by_source = {item.source_id for item in evidence}
    lines: list[str] = []
    for label, items in groups.items():
        lines.append(f"{label}（{len(items)}）")
        if not items:
            lines.append("- 无")
            continue
        for source in items[:8]:
            pdf_flag = "，官方PDF" if source.is_official_pdf else ""
            parse_flag = f"，PDF={source.pdf_parse_status}" if source.is_pdf else ""
            evidence_flag = "，已抽取证据" if source.id in evidence_by_source else "，未形成有效证据"
            lines.append(f"- {source.title}（来源类型={_label(SOURCE_ORIGIN_LABELS, source.source_origin_type)}{pdf_flag}{parse_flag}{evidence_flag}）")
    official_pdfs = [item for item in sources if item.is_official_pdf]
    insufficient_official_pdfs = [item for item in official_pdfs if item.id not in evidence_by_source]
    if insufficient_official_pdfs:
        lines.append("")
        lines.append("已获取官方年报/公告 PDF，但核心财务页抽取仍不足，建议继续结构化解析。")
    return ReportSection(
        title="来源结构",
        body="\n".join(lines),
        evidence_ids=[],
        section_type="source",
    )


def _build_role_section(roles: list[ResearchRoleOutput]) -> ReportSection:
    lines = [
        (
            f"- {role.role_name}（{role.cognitive_bias}）：{role.objective}\n"
            f"  角色定义：{role.role_description}\n"
            f"  操作规则：{'；'.join(role.operating_rules)}\n"
            f"  严禁行为：{'；'.join(role.forbidden_actions)}\n"
            f"  框架：{'、'.join(role.framework_types) if role.framework_types else '无'}\n"
            f"  压力测试：{'、'.join(role.pressure_test_ids) if role.pressure_test_ids else '无'}\n"
            f"  输出：{role.output_summary}\n"
            f"  证据：{'、'.join(role.evidence_ids) if role.evidence_ids else '无'}"
        )
        for role in roles
    ]
    evidence_ids = [evidence_id for role in roles for evidence_id in role.evidence_ids]
    return ReportSection(
        title="多角色视角",
        body="\n".join(lines) if lines else "当前尚未形成多角色视角输出。",
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="role",
    )


def _build_variable_section(variables: list[ResearchVariable]) -> ReportSection:
    lines = [
        (
            f"- [{_label(CATEGORY_LABELS, item.category)}] {item.name}: {_label(DIRECTION_LABELS, item.direction)}。{item.value_summary}"
            f"{'（方向说明：' + '；'.join(item.direction_notes) + '）' if item.direction_notes else ''}"
            f"（证据：{'、'.join(item.evidence_ids)}）"
        )
        for item in variables
    ]
    evidence_ids = [evidence_id for item in variables for evidence_id in item.evidence_ids]
    return ReportSection(
        title="关键变量",
        body="\n".join(lines) if lines else "当前证据尚不足以归一化出稳定投研变量。",
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="variable",
    )


def _build_finding_section(judgment: Judgment) -> ReportSection:
    lines: list[str] = []
    evidence_ids: list[str] = []
    for cluster in judgment.clusters:
        support_text = "、".join(cluster.support_evidence_ids) if cluster.support_evidence_ids else "无"
        counter_text = "、".join(cluster.counter_evidence_ids) if cluster.counter_evidence_ids else "无"
        lines.append(f"{cluster.theme}：支持证据={support_text}；反向证据={counter_text}")
        evidence_ids.extend(cluster.support_evidence_ids)
        evidence_ids.extend(cluster.counter_evidence_ids)

    body = "\n".join(lines[:8]) if lines else "当前尚未形成稳定主题发现。"
    return ReportSection(
        title="核心发现",
        body=body,
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="finding",
    )


def _build_risk_section(judgment: Judgment) -> ReportSection:
    lines = [f"- {item.text}（证据：{'、'.join(item.evidence_ids)}）" for item in judgment.risk]
    body = "\n".join(lines) if lines else "当前未识别到有证据支撑的主要风险。"
    evidence_ids = [evidence_id for item in judgment.risk for evidence_id in item.evidence_ids]
    return ReportSection(
        title="主要风险",
        body=body,
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="risk",
    )


def _build_bear_thesis_section(judgment: Judgment) -> ReportSection:
    lines = [
        (
            f"- {item.title}\n"
            f"  摘要：{item.summary}\n"
            f"  传导路径：{item.transmission_path or '待验证'}\n"
            f"  证伪条件：{item.falsify_condition or '待补充'}\n"
            f"  证据：{'、'.join(item.evidence_ids) if item.evidence_ids else '无'}"
        )
        for item in judgment.bear_theses
    ]
    evidence_ids = [evidence_id for item in judgment.bear_theses for evidence_id in item.evidence_ids]
    return ReportSection(
        title="反方逻辑",
        body="\n".join(lines) if lines else "当前尚未形成明确 bear thesis，但这不等于不存在下行风险。",
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="risk",
    )


def _build_catalyst_section(judgment: Judgment) -> ReportSection:
    lines = [
        (
            f"- {item.title}（{item.catalyst_type}，{item.timeframe}）\n"
            f"  为什么重要：{item.why_it_matters}\n"
            f"  证据：{'、'.join(item.evidence_ids) if item.evidence_ids else '待补证'}"
        )
        for item in judgment.catalysts
    ]
    evidence_ids = [evidence_id for item in judgment.catalysts for evidence_id in item.evidence_ids]
    return ReportSection(
        title="催化剂与触发点",
        body="\n".join(lines) if lines else "当前尚未识别到明确催化剂，建议继续跟踪官方披露和关键变量。",
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="action",
    )


def _build_pressure_section(judgment: Judgment) -> ReportSection:
    lines = [
        (
            f"- [{_label(SEVERITY_LABELS, item.severity)}] {_label(PRESSURE_LABELS, item.attack_type)}：{item.target}\n"
            f"  脆弱点：{item.weakness}\n"
            f"  反向结论：{item.counter_conclusion}\n"
            f"  脆弱证据：{'、'.join(item.fragile_evidence_ids) or '无'}；反证：{'、'.join(item.counter_evidence_ids) or '无'}"
        )
        for item in judgment.pressure_tests
    ]
    evidence_ids = [
        evidence_id
        for item in judgment.pressure_tests
        for evidence_id in item.fragile_evidence_ids + item.counter_evidence_ids
    ]
    return ReportSection(
        title="结论压力测试",
        body="\n".join(lines) if lines else "当前未识别到显式结论脆弱点，但仍需人工复核证据质量。",
        evidence_ids=list(dict.fromkeys(evidence_ids))[:12],
        section_type="pressure",
    )


def _build_gap_section(judgment: Judgment) -> ReportSection:
    gap_lines = [f"- [{_label(SEVERITY_LABELS, item.importance)}] {item.text}" for item in judgment.evidence_gaps]
    unknown_lines = [f"- {item}" for item in judgment.unknown]
    lines = ["证据缺口："] + (gap_lines or ["- 暂无显式缺口"]) + ["", "当前不确定性："] + unknown_lines
    return ReportSection(
        title="不确定性与证据缺口",
        body="\n".join(lines),
        evidence_ids=[],
        section_type="gap",
    )


def _build_judgment_section(judgment: Judgment) -> ReportSection:
    basis = judgment.confidence_basis
    body = (
        f"结论：{judgment.conclusion}\n"
        f"结论证据：{'、'.join(judgment.conclusion_evidence_ids) or '无'}\n"
        f"置信度：{_label(CONFIDENCE_LABELS, judgment.confidence)}\n"
        f"研究充分度：{_label(CONFIDENCE_LABELS, judgment.research_confidence)}；方向信号把握度：{_label(CONFIDENCE_LABELS, judgment.signal_confidence)}；来源可信度：{_label(CONFIDENCE_LABELS, judgment.source_confidence)}\n"
        f"研究定位：{judgment.positioning or '待定'}\n"
        f"置信度依据：来源数={basis.source_count}，来源独立性={_label(SEVERITY_LABELS, basis.source_diversity)}，"
        f"冲突程度={_label(CONFLICT_LABELS, basis.conflict_level)}，缺口等级={_label(SEVERITY_LABELS, basis.evidence_gap_level)}，"
        f"有效证据数={basis.effective_evidence_count}，官方证据={basis.official_evidence_count}，"
        f"是否仅依赖弱来源={'是' if basis.weak_source_only else '否'}"
    )
    return ReportSection(
        title="初步判断",
        body=body,
        evidence_ids=judgment.conclusion_evidence_ids,
        section_type="judgment",
    )


def _build_investment_section(judgment: Judgment) -> ReportSection:
    if judgment.investment_decision is None or judgment.research_scope is None or judgment.peer_context is None:
        return ReportSection(
            title="投资层判断",
            body="当前尚未生成投资层判断。",
            evidence_ids=[],
            section_type="investment",
        )

    decision = judgment.investment_decision
    scope = judgment.research_scope
    peer = judgment.peer_context
    peer_table_lines = []
    if peer.comparison_rows:
        if any("symbol" in row for row in peer.comparison_rows):
            peer_table_lines.append("| 公司 | 分组 | 营收增速 | 毛利率 | PE | EV/EBITDA | CAPEX强度 | 市占率 | 海外布局 |")
            peer_table_lines.append("|---|---|---:|---:|---:|---:|---:|---|---|")
            for row in peer.comparison_rows[:6]:
                peer_table_lines.append(
                    "| {name} | {group} | {growth} | {margin} | {pe} | {ev_ebitda} | {capex} | {share} | {overseas} |".format(
                        name=row.get("peer_name") or row.get("symbol") or row.get("ticker") or "",
                        group=row.get("peer_group", ""),
                        growth=row.get("revenue_growth", row.get("revenueGrowth", "")),
                        margin=row.get("gross_margin", row.get("grossMargins", row.get("profitMargins", ""))),
                        pe=row.get("valuation_pe", row.get("trailingPE", "")),
                        ev_ebitda=row.get("valuation_ev_ebitda", row.get("enterpriseToEbitda", "")),
                        capex=row.get("capex_intensity", ""),
                        share=row.get("market_share", ""),
                        overseas=row.get("overseas_exposure", ""),
                    )
                )
            positioning = next((row.get("positioning") for row in peer.comparison_rows if row.get("positioning")), None)
            if positioning:
                peer_table_lines.append("")
                peer_table_lines.append(f"同行定位信号：{', '.join(positioning.get('signals', [])) or '暂无'}")
        else:
            peer_table_lines.append("| Peer Group | Peer | Benchmark Dimensions | Status |")
            peer_table_lines.append("|---|---|---|---|")
            for row in peer.comparison_rows[:8]:
                dimensions = row.get("benchmark_dimensions", [])
                peer_table_lines.append(
                    "| {peer_group} | {peer} | {dimensions} | {status} |".format(
                        peer_group=row.get("peer_group", ""),
                        peer=row.get("peer", ""),
                        dimensions=", ".join(dimensions) if isinstance(dimensions, list) else dimensions,
                        status=_humanize_text(row.get("status", "")),
                    )
                )
    trend_lines = [
        f"- {signal.metric}: {_label(DIRECTION_LABELS, signal.direction)}（证据：{'、'.join(signal.evidence_ids)}）"
        for signal in judgment.trend_signals
    ]
    body = (
        f"研究深度建议：{_humanize_text(scope.depth_recommendation)}，预计耗时：{scope.estimated_hours}，紧急度：{_label(SEVERITY_LABELS, scope.urgency)}\n"
        f"原因：{scope.reason}\n\n"
        f"决策对象：{_label(DECISION_TARGET_LABELS, decision.decision_target)}\n"
        f"研究流程建议：{_label(DECISION_LABELS, decision.decision)}\n"
        f"研究定位：{decision.positioning or judgment.positioning or '待定'}\n"
        f"决策理由：{decision.rationale}\n"
        f"推荐理由：{decision.research_recommendation_reason or '无'}\n"
        f"下一步最佳路径：{decision.next_best_research_path or '无'}\n"
        f"决策依据：{'；'.join(_humanize_text(item) for item in decision.decision_basis) if decision.decision_basis else '无'}\n"
        f"复盘触发条件：{decision.trigger_to_revisit}\n"
        f"边界说明：{decision.caveat}\n"
        f"人工复核状态：{_humanize_text(judgment.reviewer_status)}"
        f"{'，复核意见：' + judgment.reviewer_comment if judgment.reviewer_comment else ''}\n\n"
        f"同行参照：{_humanize_text(peer.status)}。{_humanize_text(peer.note)}\n"
        + (("\n".join(peer_table_lines) + "\n") if peer_table_lines else "")
        +
        f"趋势信号：\n" + ("\n".join(trend_lines) if trend_lines else "- 当前未形成明确趋势信号")
    )
    evidence_ids = list(dict.fromkeys(decision.evidence_ids + peer.evidence_ids + [
        evidence_id for signal in judgment.trend_signals for evidence_id in signal.evidence_ids
    ]))
    return ReportSection(
        title="投资层判断",
        body=body,
        evidence_ids=evidence_ids[:12],
        section_type="investment",
    )


def _build_action_section(judgment: Judgment) -> ReportSection:
    lines = [
        (
            f"- [{_label(PRIORITY_LABELS, item.priority)}] {item.objective}\n"
            f"  问题：{item.question or item.objective}\n"
            f"  原因：{item.reason}\n"
            f"  所需数据：{'、'.join(item.required_data)}\n"
            f"  首选查询：{item.search_query or (item.query_templates[0] if item.query_templates else '无')}\n"
            f"  检索模板：{'；'.join(item.query_templates)}\n"
            f"  目标来源：{'、'.join(item.target_sources or item.source_targets)}\n"
            f"  状态：{_label(ACTION_STATUS_LABELS, item.status)}"
        )
        for item in judgment.research_actions
    ]
    body = "\n".join(lines) if lines else "暂无下一步研究建议。"
    return ReportSection(
        title="下一步研究建议",
        body=body,
        evidence_ids=[],
        section_type="action",
    )


def _format_evidence_reference(evidence_id: str, evidence_map: dict[str, Evidence], source_map: dict[str, Source]) -> str:
    evidence = evidence_map.get(evidence_id)
    if evidence is None:
        return f"[{evidence_id}] 证据不存在"
    source = source_map.get(evidence.source_id)
    if source is None:
        return f"[{evidence_id}] 原文片段：「{evidence.content}」"
    date_text = source.published_at or "未知日期"
    url_text = f"\n    URL：{source.url}" if source.url else ""
    return (
        f"[{evidence_id}] 来源：{source.title}（{_label(TIER_LABELS, source.tier.value)}，{_label(SOURCE_ORIGIN_LABELS, source.source_origin_type)}，来源分={source.source_score}，{date_text}，{source.flow_type}流）\n"
        f"    证据分：{evidence.evidence_score}；原文片段：「{evidence.content}」"
        f"{url_text}"
    )


def _render_markdown(sections: list[ReportSection], evidence: list[Evidence], sources: list[Source]) -> str:
    evidence_map = {item.id: item for item in evidence}
    source_map = {item.id: item for item in sources}
    parts: list[str] = ["# 投研初步研究报告"]
    for section in sections:
        parts.append(f"\n## {section.title}\n")
        parts.append(section.body)
        if section.evidence_ids:
            parts.append("\n\n证据引用：")
            for evidence_id in section.evidence_ids:
                parts.append(_format_evidence_reference(evidence_id, evidence_map, source_map))
    return "\n".join(parts).strip()


def generate_report(
    topic: Topic,
    questions: list[Question],
    sources: list[Source],
    evidence: list[Evidence],
    variables: list[ResearchVariable],
    roles: list[ResearchRoleOutput],
    judgment: Judgment,
) -> ResearchReport:
    """Render a user-facing report from structured research artifacts."""

    report_seed = f"{topic.id}:{len(questions)}:{len(sources)}:{len(evidence)}"
    report_id = f"report_{md5(report_seed.encode('utf-8')).hexdigest()[:8]}"

    sections = [
        _build_background_section(topic),
        _build_framework_section(questions),
        _build_source_governance_section(sources, evidence),
        _build_role_section(roles),
        _build_variable_section(variables),
        _build_finding_section(judgment),
        _build_risk_section(judgment),
        _build_bear_thesis_section(judgment),
        _build_pressure_section(judgment),
        _build_catalyst_section(judgment),
        _build_gap_section(judgment),
        _build_judgment_section(judgment),
        _build_investment_section(judgment),
        _build_action_section(judgment),
    ]

    return ResearchReport(
        id=report_id,
        topic=topic,
        questions=questions,
        sources=sources,
        evidence=evidence,
        variables=variables,
        roles=roles,
        judgment=judgment,
        report_sections=sections,
        markdown=_render_markdown(sections, evidence, sources),
    )
