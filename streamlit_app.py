from __future__ import annotations

from collections import defaultdict
from html import escape

import streamlit as st

from app.agent.pipeline import research_pipeline
from app.config import get_settings
from app.models.evidence import Evidence
from app.models.question import Question
from app.models.role import ResearchRoleOutput
from app.models.source import Source
from app.services.search_service import get_search_provider_status


st.set_page_config(
    page_title="Research Agent 投研流程 Demo",
    page_icon="📊",
    layout="wide",
)


FLOW_LABELS = {
    "fact": "事实流",
    "risk": "风险流",
    "counter": "反证流",
}

FLOW_HELP = {
    "fact": "资料员视角：尽量中性地找公开事实和数据。",
    "risk": "风控官视角：主动寻找负面信号、红旗和一票否决项。",
    "counter": "反方分析师视角：主动寻找改善、反转和风险缓解证据。",
}

VARIABLE_DISPLAY_NAMES = {
    "收入增长": "收入增长动能",
    "盈利能力": "利润率与盈利质量",
    "现金流质量": "现金流质量",
    "负债压力": "资产负债压力",
    "行业竞争": "行业竞争位置",
    "治理合规": "治理与合规风险",
    "经营韧性": "经营韧性与业务质量",
    "估值锚点": "估值参照",
}

DIRECTION_LABELS = {
    "improving": "改善",
    "deteriorating": "恶化",
    "stable": "稳定",
    "mixed": "信号分化",
    "unknown": "方向不明",
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

DECISION_TARGET_LABELS = {
    "research_priority": "研究优先级",
    "deep_research_entry": "深度研究入口",
    "watchlist_entry": "观察清单",
    "research_action": "研究动作",
    "theme_tracking": "主题跟踪",
    "credit_review": "信用复核",
}

CONFIDENCE_LABELS = {
    "high": "高置信度",
    "medium": "中等置信度",
    "low": "低置信度，结论仅供参考",
}

COVERAGE_LABELS = {
    "covered": "已覆盖",
    "partial": "部分覆盖",
    "uncovered": "未覆盖",
}

PRESSURE_LABELS = {
    "fragile_evidence": "结论依赖低质量证据",
    "ignored_counter_evidence": "反证未被充分吸收",
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

TIER_LABELS = {
    "official": "官方来源",
    "professional": "专业来源",
    "content": "普通内容来源",
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

PDF_STATUS_LABELS = {
    "not_pdf": "非 PDF",
    "not_attempted": "未解析",
    "parsed": "已解析",
    "failed": "解析失败",
}


def _label(mapping: dict[str, str], value: object) -> str:
    return mapping.get(str(value), str(value))


def _humanize_text(text: object) -> str:
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
    }
    output = str(text)
    for raw, label in replacements.items():
        output = output.replace(raw, label)
    return output


def _install_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #17212b;
            --muted: #697586;
            --line: #d9e2ec;
            --paper: #ffffff;
            --soft: #f5f8fb;
            --blue: #175cd3;
            --teal: #0e9384;
            --amber: #b54708;
            --red: #c01048;
        }
        .stApp {
            background:
                radial-gradient(circle at 8% 4%, rgba(23, 92, 211, 0.08), transparent 30%),
                radial-gradient(circle at 88% 2%, rgba(14, 147, 132, 0.10), transparent 28%),
                linear-gradient(180deg, #f7fafc 0%, #eef3f8 100%);
        }
        .block-container { padding-top: 1.4rem; max-width: 1280px; }
        h1, h2, h3, h4 { color: var(--ink); letter-spacing: -0.02em; }
        .small-muted { color: var(--muted); font-size: 0.88rem; }
        .hero {
            border: 1px solid rgba(23, 92, 211, 0.16);
            border-radius: 24px;
            padding: 1.35rem 1.45rem;
            background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(232,242,255,0.94));
            box-shadow: 0 18px 42px rgba(16, 24, 40, 0.08);
            margin-bottom: 1rem;
        }
        .hero-kicker {
            color: var(--blue);
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }
        .hero-title {
            font-size: 2.05rem;
            font-weight: 850;
            line-height: 1.12;
            margin: 0;
            color: var(--ink);
        }
        .hero-subtitle {
            color: var(--muted);
            font-size: 0.98rem;
            margin-top: 0.55rem;
            max-width: 820px;
        }
        .module {
            border: 1px solid rgba(25, 33, 43, 0.08);
            border-radius: 22px;
            padding: 1.05rem 1.1rem;
            background: rgba(255, 255, 255, 0.92);
            box-shadow: 0 10px 30px rgba(16, 24, 40, 0.05);
            margin: 1.05rem 0 0.8rem 0;
        }
        .module-head {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            margin-bottom: 0.8rem;
        }
        .module-index {
            min-width: 2.35rem;
            height: 2.35rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 13px;
            color: #fff;
            font-weight: 800;
            background: linear-gradient(135deg, #175cd3, #0e9384);
            box-shadow: 0 8px 18px rgba(23, 92, 211, 0.22);
        }
        .module-title {
            font-size: 1.2rem;
            font-weight: 820;
            color: var(--ink);
            margin: 0;
        }
        .module-caption {
            color: var(--muted);
            margin-top: 0.12rem;
            font-size: 0.92rem;
        }
        .card {
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 1rem 1.05rem;
            background: var(--paper);
            box-shadow: 0 5px 18px rgba(16, 24, 40, 0.045);
            margin-bottom: 0.8rem;
        }
        .card h4 {
            font-size: 1rem;
            margin: 0.35rem 0 0.48rem 0;
        }
        .card-body {
            white-space: pre-wrap;
            color: #26313d;
            line-height: 1.58;
            font-size: 0.93rem;
        }
        .metric-card {
            border: 1px solid rgba(25, 33, 43, 0.08);
            border-radius: 18px;
            background: linear-gradient(180deg, #ffffff, #f8fbfe);
            padding: 0.85rem 0.95rem;
            min-height: 6.2rem;
            box-shadow: 0 4px 14px rgba(16, 24, 40, 0.04);
            margin-bottom: 0.7rem;
        }
        .metric-label {
            color: var(--muted);
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.02em;
        }
        .metric-value {
            color: var(--ink);
            font-size: 1.25rem;
            font-weight: 850;
            line-height: 1.25;
            margin-top: 0.35rem;
            word-break: break-word;
        }
        .metric-hint {
            color: var(--muted);
            font-size: 0.78rem;
            margin-top: 0.3rem;
        }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 0.2rem 0.58rem;
            font-size: 0.78rem;
            font-weight: 760;
            background: #eef4ff;
            color: var(--blue);
            margin-right: 0.35rem;
            margin-bottom: 0.25rem;
        }
        .badge-risk { background: #fff1f3; color: #c01048; }
        .badge-counter { background: #ecfdf3; color: #027a48; }
        .badge-fact { background: #eff8ff; color: #175cd3; }
        .badge-low { background: #fff1f3; color: #c01048; }
        .badge-medium { background: #fffaeb; color: #b54708; }
        .badge-high { background: #ecfdf3; color: #027a48; }
        .evidence-quote {
            border-left: 4px solid #175cd3;
            padding-left: 0.8rem;
            color: #26313d;
            background: #f8fbff;
            border-radius: 0 12px 12px 0;
            padding-top: 0.55rem;
            padding-bottom: 0.55rem;
        }
        div[data-testid="stTabs"] button {
            border-radius: 999px;
            padding-left: 0.7rem;
            padding-right: 0.7rem;
        }
        .stDataFrame {
            border-radius: 16px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(text: str, kind: str = "fact") -> str:
    return f'<span class="badge badge-{kind}">{escape(str(text))}</span>'


def _card(title: str, body: str, badges: list[str] | None = None) -> None:
    badge_html = " ".join(badges or [])
    title_html = escape(str(title))
    body_html = escape(str(body))
    st.markdown(
        f"""
        <div class="card">
            <div>{badge_html}</div>
            <h4>{title_html}</h4>
            <div class="card-body">{body_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: object, hint: str | None = None) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{escape(str(label))}</div>
            <div class="metric-value">{escape(str(value))}</div>
            <div class="metric-hint">{escape(hint or "")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_search_api_status() -> None:
    settings = get_settings()
    rows = get_search_provider_status(settings)
    enabled_rows = [row for row in rows if row["enabled"]]
    st.subheader("搜索 API 状态")
    st.caption("只展示 key 是否已配置，不展示真实密钥；Google Custom Search 需要同时配置 API key 和 CX。")
    st.write(f"SEARCH_PROVIDER：`{settings.search_provider}`")
    st.write(f"已启用：{len(enabled_rows)} / {len(rows)}")
    st.dataframe(
        [
            {
                "Provider": row["provider"],
                "状态": "启用" if row["enabled"] else "未启用",
                "用途": row["purpose"],
                "单次上限": row["max_results"],
                "配置项": row["required_env"],
                "说明": row["note"],
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
    if settings.supplemental_search_enabled:
        st.caption("垂直补充源：SEC EDGAR、Yahoo Finance/yfinance、公司 IR 官网直连已启用；这些来源不一定需要搜索 API key。")
    else:
        st.caption("垂直补充源已关闭。")


def _financial_status_hint(snapshot) -> str:
    if snapshot.status == "FALLBACK_USED" and snapshot.provider == "tavily_search_fallback":
        return "结构化 provider 失败，已用搜索兜底"
    if snapshot.status == "FALLBACK_USED":
        return "已使用备用结构化 provider"
    if snapshot.status == "ALL_PROVIDERS_FAILED":
        return "所有结构化 provider 和兜底源均失败"
    if snapshot.status == "SUCCESS":
        return "结构化 provider 成功"
    return "查看 provider attempts 获取原因"


def _display_variable_name(variable) -> str:
    readable = VARIABLE_DISPLAY_NAMES.get(variable.name, variable.name)
    direction = DIRECTION_LABELS.get(variable.direction, variable.direction)
    return f"{readable}：{direction}"


def _evidence_map(evidence: list[Evidence]) -> dict[str, Evidence]:
    return {item.id: item for item in evidence}


def _source_map(sources: list[Source]) -> dict[str, Source]:
    return {item.id: item for item in sources}


def _render_step_title(index: int, title: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="module">
            <div class="module-head">
                <div class="module-index">{index:02d}</div>
                <div>
                    <div class="module-title">{escape(title)}</div>
                    <div class="module-caption">{escape(caption)}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Research Workflow Engine</div>
            <h1 class="hero-title">投研初筛工作台</h1>
            <div class="hero-subtitle">
                从模糊问题出发，系统按研究流程完成定义、拆解、检索、证据提取、变量归纳、判断、补证、团队复核和报告输出。
                重点不是生成漂亮文字，而是把判断绑定到来源和证据。本工具用于研究初筛，不构成荐股或交易建议。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_topic(topic) -> None:
    cols = st.columns(6)
    with cols[0]:
        _metric_card("研究对象", topic.entity or "未识别", "用于检索和金融数据解析")
    with cols[1]:
        _metric_card("研究主题", topic.topic, "不是复制用户原始问题")
    with cols[2]:
        _metric_card("对象类型", getattr(topic, "research_object_type", "unknown"), "全局路由字段")
    with cols[3]:
        _metric_card("上市状态", getattr(topic, "listing_status", "unknown"), "listed/private/concept")
    with cols[4]:
        _metric_card("市场类型", getattr(topic, "market_type", "other"), "A/HK/US/bond/theme")
    with cols[5]:
        _metric_card("Topic ID", topic.id, "全链路追踪标识")
    _card("研究目标", topic.goal, [_badge("topic", "fact")])
    if getattr(topic, "listing_note", None):
        _card("上市状态说明", topic.listing_note, [_badge("listing", "medium")])
    if topic.hypothesis:
        _card("用户隐含假设", topic.hypothesis, [_badge("hypothesis", "medium")])


def render_confidence_guidance() -> None:
    _card(
        "使用边界",
        (
            "当前系统适合做投研初筛和证据线索整理。"
            "confidence=low 时，结论仅供参考，需要人工补充官方来源；"
            "confidence=medium 时，研究框架和风险识别可参考，但关键数据仍需核实；"
            "high 置信度需人工确认后才生效。"
        ),
        [_badge("内部初筛", "fact"), _badge("非投资建议", "risk")],
    )


def render_executive_summary(summary) -> None:
    if summary is None:
        return
    confidence_kind = "low" if summary.confidence == "low" else "medium" if summary.confidence == "medium" else "high"
    st.markdown("### 执行摘要")
    cols = st.columns(4)
    with cols[0]:
        _metric_card("Confidence", _label(CONFIDENCE_LABELS, summary.confidence), "规则层计算，不是模型自评")
    with cols[1]:
        _metric_card("建议继续投入", f"{summary.research_time_minutes} 分钟", "初筛后的研究投入估算")
    with cols[2]:
        _metric_card("Top Risk", summary.top_risk[:26] + ("..." if len(summary.top_risk) > 26 else ""), "优先关注事项")
    with cols[3]:
        _metric_card("Next Action", summary.next_action[:26] + ("..." if len(summary.next_action) > 26 else ""), "下一步动作")
    _card("一句话结论", summary.one_line_conclusion, [_badge(f"confidence={summary.confidence}", confidence_kind)])


def render_financial_snapshot(snapshot) -> None:
    if snapshot is None:
        return
    cols = st.columns(4)
    with cols[0]:
        _metric_card("金融数据状态", snapshot.status, _financial_status_hint(snapshot))
    with cols[1]:
        _metric_card("Provider", snapshot.provider, "真实数据来源")
    with cols[2]:
        _metric_card("Symbol", snapshot.symbol or "未解析", "证券代码")
    with cols[3]:
        _metric_card("Peers", len(snapshot.peer_symbols), "候选同行数量")

    metric_lines = [
        f"- {metric.name}: {metric.value}{metric.unit or ''}（{metric.period or 'latest'}，{metric.source}）"
        for metric in snapshot.metrics
    ]
    peer_line = f"\n\n同行代码：{', '.join(snapshot.peer_symbols)}" if snapshot.peer_symbols else ""
    note = f"\n\n说明：{snapshot.note}" if snapshot.note else ""
    tabs = st.tabs(["关键指标", "同行对比", "数据说明"])
    with tabs[0]:
        _card(
            "结构化金融数据快照",
            "\n".join(metric_lines[:24]) if metric_lines else "未获得可用结构化指标。",
            [_badge(snapshot.status, "counter" if snapshot.status == "ok" else "medium")],
        )
    with tabs[1]:
        if snapshot.peer_comparison:
            st.dataframe(snapshot.peer_comparison, use_container_width=True, hide_index=True)
        else:
            st.info("当前未形成同行对比表。")
    with tabs[2]:
        if getattr(snapshot, "provider_attempts", None):
            attempts = [
                {
                    "provider": attempt.provider,
                    "symbol": attempt.symbol,
                    "market": attempt.market,
                    "status": attempt.status,
                    "retryable": attempt.retryable,
                    "next_provider": attempt.next_provider,
                    "latency_ms": attempt.latency_ms,
                    "message": attempt.message[:180] + ("..." if len(attempt.message) > 180 else ""),
                }
                for attempt in snapshot.provider_attempts
            ]
            st.dataframe(attempts, use_container_width=True, hide_index=True)
        _card("数据边界", (peer_line.strip() + note) if (peer_line or note) else "无补充说明。", [_badge("data boundary", "medium")])


def render_questions(questions: list[Question]) -> None:
    if not questions:
        st.info("暂无研究问题。")
        return
    cols = st.columns(2)
    for index, question in enumerate(questions):
        status = COVERAGE_LABELS.get(question.coverage_level, "待补证")
        with cols[index % 2]:
            _card(
                f"{question.id}｜{question.framework_type}",
                question.content,
                [
                    _badge(f"P{question.priority}", "medium"),
                    _badge(status, "counter" if question.covered else "risk"),
                ],
            )


def render_sources(sources: list[Source]) -> None:
    grouped: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        grouped[source.flow_type].append(source)

    summary_cols = st.columns(4)
    with summary_cols[0]:
        _metric_card("来源总数", len(sources), "进入证据抽取前的材料池")
    with summary_cols[1]:
        _metric_card("官方/专业", len([s for s in sources if s.tier.value in {"official", "professional"}]), "高可信来源")
    with summary_cols[2]:
        _metric_card("PDF 解析", len([s for s in sources if s.pdf_parse_status == "parsed"]), "已解析 PDF")
    with summary_cols[3]:
        _metric_card("结构化数据", len([s for s in sources if s.provider in {"yfinance", "tavily_search_fallback"}]), "金融快照来源")

    tabs = st.tabs([f"{FLOW_LABELS[key]} ({len(grouped[key])})" for key in ["fact", "risk", "counter"]])
    for tab, flow_type in zip(tabs, ["fact", "risk", "counter"]):
        with tab:
            st.caption(FLOW_HELP[flow_type])
            if not grouped[flow_type]:
                st.info("这一条流暂时没有检索到可用来源。")
                continue
            overview = [
                {
                    "id": source.id,
                    "标题": source.title[:42],
                    "来源层级": _label(TIER_LABELS, source.tier.value),
                    "来源分": source.source_score,
                    "来源类型": _label(SOURCE_ORIGIN_LABELS, source.source_origin_type),
                    "Provider": source.provider,
                    "PDF 状态": _label(PDF_STATUS_LABELS, source.pdf_parse_status),
                }
                for source in grouped[flow_type]
            ]
            st.dataframe(overview, use_container_width=True, hide_index=True)
            for source in grouped[flow_type]:
                with st.expander(f"{source.id}｜{source.title}", expanded=False):
                    badges = [
                        _badge(FLOW_LABELS[source.flow_type], source.flow_type),
                        _badge(_label(TIER_LABELS, source.tier.value), "medium"),
                        _badge(source.provider, "fact"),
                    ]
                    body = (
                        f"检索词：{source.search_query or '未知'}\n"
                        f"来源分：{source.source_score}｜包含研究对象：{'是' if source.contains_entity else '否'}｜近期来源：{'是' if source.is_recent else '否'}\n"
                        f"来源类型：{_label(SOURCE_ORIGIN_LABELS, source.source_origin_type)}｜来源层级：{_label(TIER_LABELS, source.tier.value)}\n"
                        f"PDF：{'是' if source.is_pdf else '否'}｜解析状态：{_label(PDF_STATUS_LABELS, source.pdf_parse_status)}｜表格数：{len(source.parsed_tables)}\n"
                        f"URL：{source.url or '无'}\n\n"
                        f"{source.content[:900]}{'...' if len(source.content) > 900 else ''}"
                    )
                    _card("来源详情", body, badges)


def render_evidence(evidence: list[Evidence], sources: list[Source]) -> None:
    source_by_id = _source_map(sources)
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.flow_type].append(item)

    metric_cols = st.columns(4)
    with metric_cols[0]:
        _metric_card("证据总数", len(evidence), "通过去噪和锚定校验")
    with metric_cols[1]:
        _metric_card("支持证据", len([e for e in evidence if e.stance == "support"]), "支撑风险或结论")
    with metric_cols[2]:
        _metric_card("反证", len([e for e in evidence if e.stance == "counter"]), "反向或缓解信号")
    with metric_cols[3]:
        avg_score = round(sum((e.evidence_score or 0) for e in evidence) / max(len(evidence), 1), 3)
        _metric_card("平均证据分", avg_score, "来源、相关性、清晰度、时效性")

    tabs = st.tabs([f"{FLOW_LABELS[key]}证据 ({len(grouped[key])})" for key in ["fact", "risk", "counter"]])
    for tab, flow_type in zip(tabs, ["fact", "risk", "counter"]):
        with tab:
            if not grouped[flow_type]:
                st.info("暂无该流证据。")
                continue
            overview = [
                {
                    "id": item.id,
                    "type": item.evidence_type,
                    "stance": item.stance,
                    "score": item.evidence_score,
                    "source": item.source_id,
                    "question": item.question_id,
                }
                for item in grouped[flow_type]
            ]
            st.dataframe(overview, use_container_width=True, hide_index=True)
            for item in grouped[flow_type]:
                source = source_by_id.get(item.source_id)
                source_title = source.title if source else "未知来源"
                badges = [
                    _badge(item.flow_type, item.flow_type),
                    _badge(item.evidence_type, "medium"),
                    _badge(item.stance, "counter" if item.stance == "counter" else "risk" if item.stance == "support" else "fact"),
                    _badge("grounded" if item.grounded else "ungrounded", "counter" if item.grounded else "risk"),
                ]
                body = (
                    f"{item.content}\n\n"
                    f"Evidence Score：{item.evidence_score}｜source_tier={item.source_tier}｜"
                    f"relevance={item.relevance_score}｜clarity={item.clarity_score}\n"
                    f"来源：{source_title}\nsource_id={item.source_id}｜question_id={item.question_id}"
                )
                with st.expander(f"{item.id}｜{item.evidence_type}｜{item.stance}", expanded=False):
                    _card("证据片段", body, badges)


def render_variables(variables) -> None:
    if not variables:
        st.info("当前证据还不足以形成稳定投研变量。")
        return
    cols = st.columns(2)
    for index, variable in enumerate(variables):
        with cols[index % 2]:
            direction_kind = "counter" if variable.direction == "improving" else "risk" if variable.direction == "deteriorating" else "medium"
            _card(
                _display_variable_name(variable),
                f"{variable.value_summary}\n\n方向说明：{'; '.join(variable.direction_notes) if variable.direction_notes else '无'}\n\n证据：{', '.join(variable.evidence_ids)}",
                [_badge(variable.category, "fact"), _badge(DIRECTION_LABELS.get(variable.direction, variable.direction), direction_kind)],
            )


def render_roles(roles: list[ResearchRoleOutput]) -> None:
    if not roles:
        st.info("暂无角色输出。")
        return

    role_overview = [
        {
            "角色": role.role_name,
            "偏置": role.cognitive_bias,
            "证据数": len(role.evidence_ids),
            "变量数": len(role.variable_names),
            "压力测试数": len(role.pressure_test_ids),
        }
        for role in roles
    ]
    st.dataframe(role_overview, use_container_width=True, hide_index=True)

    tabs = st.tabs([role.role_name for role in roles])
    for tab, role in zip(tabs, roles):
        with tab:
            _card(
                role.role_name,
                f"{role.role_description}\n\n目标：{role.objective}",
                [_badge(role.cognitive_bias, "medium")],
            )
            cols = st.columns([1, 1])
            with cols[0]:
                st.markdown("**职责目标**")
                st.write(role.objective)
                st.markdown("**操作规则**")
                for rule in role.operating_rules:
                    st.write(f"- {rule}")
                st.markdown("**严禁行为**")
                for action in role.forbidden_actions:
                    st.write(f"- {action}")
            with cols[1]:
                st.markdown("**角色输出**")
                st.write(role.output_summary)
                st.markdown("**引用证据**")
                st.write(", ".join(role.evidence_ids) if role.evidence_ids else "无")
                st.markdown("**框架分叉**")
                st.write(", ".join(role.framework_types) if role.framework_types else "无")
                st.markdown("**关联压力测试**")
                st.write(", ".join(role.pressure_test_ids) if role.pressure_test_ids else "无")
                st.markdown("**相关变量**")
                st.write(", ".join(role.variable_names) if role.variable_names else "无")
            with st.expander("查看这个角色的完整 Prompt"):
                st.code(role.role_prompt, language="text")


def render_judgment(judgment, evidence: list[Evidence]) -> None:
    valid_ids = set(_evidence_map(evidence))
    confidence_kind = "low" if judgment.confidence == "low" else "medium" if judgment.confidence == "medium" else "high"
    _card(
        "初步结论",
        f"{judgment.conclusion}\n\n结论证据：{', '.join(judgment.conclusion_evidence_ids) or '无'}",
        [_badge(f"confidence={judgment.confidence}", confidence_kind)],
    )

    tabs = st.tabs(["证据分组", "主要风险", "反方逻辑", "催化剂", "不确定性", "置信度", "压力测试"])
    with tabs[0]:
        for cluster in judgment.clusters:
            _card(
                cluster.theme,
                f"支持证据：{', '.join(cluster.support_evidence_ids) or '无'}\n反证：{', '.join(cluster.counter_evidence_ids) or '无'}",
                [_badge("cluster", "fact")],
            )
    with tabs[1]:
        if not judgment.risk:
            st.info("当前没有形成有证据支撑的风险项。")
        for risk in judgment.risk:
            id_status = "全部有效" if set(risk.evidence_ids).issubset(valid_ids) else "存在无效引用"
            _card(risk.text, f"证据：{', '.join(risk.evidence_ids)}\n引用校验：{id_status}", [_badge("risk", "risk")])
    with tabs[2]:
        if not judgment.bear_theses:
            st.info("当前尚未形成明确反方 thesis。")
        for item in judgment.bear_theses:
            _card(
                item.title,
                (
                    f"摘要：{item.summary}\n"
                    f"传导路径：{item.transmission_path or '待验证'}\n"
                    f"证伪条件：{item.falsify_condition or '待补充'}\n"
                    f"证据：{', '.join(item.evidence_ids) if item.evidence_ids else '无'}"
                ),
                [_badge("bear thesis", "risk")],
            )
    with tabs[3]:
        if not judgment.catalysts:
            st.info("当前尚未识别明确催化剂。")
        for item in judgment.catalysts:
            _card(
                f"{item.title}｜{item.catalyst_type}",
                f"时间窗口：{item.timeframe}\n为什么重要：{item.why_it_matters}\n证据：{', '.join(item.evidence_ids) if item.evidence_ids else '待补证'}",
                [_badge("catalyst", "medium")],
            )
    with tabs[4]:
        gap_cols = st.columns(2)
        with gap_cols[0]:
            st.markdown("**不确定性**")
            if not judgment.unknown:
                st.info("暂无显式不确定性。")
            for unknown in judgment.unknown:
                st.write(f"- {unknown}")
        with gap_cols[1]:
            st.markdown("**证据缺口**")
            if not judgment.evidence_gaps:
                st.info("暂无显式证据缺口。")
            for gap in judgment.evidence_gaps:
                st.write(f"- [{_label(SEVERITY_LABELS, gap.importance)}] {gap.text}")
    with tabs[5]:
        basis = judgment.confidence_basis
        layer_cols = st.columns(4)
        with layer_cols[0]:
            _metric_card("总置信度", _label(CONFIDENCE_LABELS, judgment.confidence), f"定位：{judgment.positioning or '待定'}")
        with layer_cols[1]:
            _metric_card("研究充分度", _label(CONFIDENCE_LABELS, judgment.research_confidence), "覆盖度与证据缺口")
        with layer_cols[2]:
            _metric_card("方向信号", _label(CONFIDENCE_LABELS, judgment.signal_confidence), "冲突与信号强度")
        with layer_cols[3]:
            _metric_card("来源可信度", _label(CONFIDENCE_LABELS, judgment.source_confidence), "来源层级与独立性")
        cols = st.columns(4)
        with cols[0]:
            _metric_card("来源数", basis.source_count, f"独立性：{_label(SEVERITY_LABELS, basis.source_diversity)}")
        with cols[1]:
            _metric_card("有效证据", basis.effective_evidence_count, f"官方证据：{basis.official_evidence_count}")
        with cols[2]:
            _metric_card("冲突程度", _label(CONFLICT_LABELS, basis.conflict_level), "反证检验")
        with cols[3]:
            weak_source_text = "仅依赖弱来源" if basis.weak_source_only else "未触发弱来源单一警告"
            _metric_card("缺口等级", _label(SEVERITY_LABELS, basis.evidence_gap_level), weak_source_text)
        with st.expander("查看原始 confidence_basis JSON"):
            st.json(judgment.confidence_basis.model_dump())
    with tabs[6]:
        if not judgment.pressure_tests:
            st.info("当前未识别到显式结论脆弱点，但仍需人工复核证据质量。")
        for item in judgment.pressure_tests:
            _card(
                f"{item.test_id}｜{_label(PRESSURE_LABELS, item.attack_type)}｜{_label(SEVERITY_LABELS, item.severity)}",
                (
                    f"攻击目标：{item.target}\n"
                    f"脆弱点：{item.weakness}\n"
                    f"反向结论：{item.counter_conclusion}\n"
                    f"脆弱证据：{', '.join(item.fragile_evidence_ids) or '无'}\n"
                    f"反证：{', '.join(item.counter_evidence_ids) or '无'}"
                ),
                [_badge("pressure", "risk" if item.severity == "high" else "medium")],
            )


def render_actions(judgment) -> None:
    if not judgment.research_actions:
        st.info("暂无下一步研究建议。")
        return
    cols = st.columns(2)
    for index, action in enumerate(judgment.research_actions):
        with cols[index % 2]:
            body = (
                f"原因：{action.reason}\n"
                f"所需数据：{', '.join(action.required_data)}\n"
                f"检索模板：{'; '.join(action.query_templates)}\n"
                f"目标来源：{', '.join(action.source_targets)}\n"
                f"状态：{_label(ACTION_STATUS_LABELS, action.status)}"
            )
            _card(f"{action.id}｜{_label(PRIORITY_LABELS, action.priority)}｜{action.objective}", body, [_badge("action", "medium")])


def render_auto_research(trace) -> None:
    if not trace:
        st.info("本次没有触发自动补证，或补证 loop 没有产生 trace。")
        return
    for item in trace:
        _card(
            f"Round {item.round_index}｜{'已触发' if item.triggered else '未触发'}",
            (
                f"选中动作：{', '.join(item.selected_action_ids) or '无'}\n"
                f"执行查询：{'; '.join(item.executed_queries) or '无'}\n"
                f"新增来源：{', '.join(item.new_source_ids) or '无'}\n"
                f"新增证据：{', '.join(item.new_evidence_ids) or '无'}\n"
                f"停止原因：{item.stop_reason}"
            ),
            [_badge("auto-research", "counter" if item.triggered else "medium")],
        )


def render_investment(judgment) -> None:
    decision = judgment.investment_decision
    if decision is None:
        st.info("暂无投资层判断。")
        return

    cols = st.columns(4)
    with cols[0]:
        _metric_card("决策对象", _label(DECISION_TARGET_LABELS, decision.decision_target), "研究流程层面")
    with cols[1]:
        _metric_card("研究流程建议", _label(DECISION_LABELS, decision.decision), "非买卖建议")
    with cols[2]:
        _metric_card("证据数量", len(decision.evidence_ids), "决策证据")
    with cols[3]:
        _metric_card("依据数量", len(decision.decision_basis), "决策依据")

    _card(
        "投资处理建议",
        (
            f"理由：{decision.rationale}\n\n"
            f"研究定位：{decision.positioning or judgment.positioning or '待定'}\n\n"
            f"推荐理由：{decision.research_recommendation_reason or '无'}\n\n"
            f"下一步最佳路径：{decision.next_best_research_path or '无'}\n\n"
            f"复盘触发条件：{decision.trigger_to_revisit}\n\n"
            f"边界说明：{decision.caveat}"
        ),
        [_badge(_label(DECISION_LABELS, decision.decision), "counter" if decision.decision == "deep_dive_candidate" else "risk" if decision.decision == "deprioritize" else "medium")],
    )
    with st.expander("查看决策依据"):
        for item in decision.decision_basis:
            st.write(f"- {_humanize_text(item)}")


def render_default_brief(result: dict) -> None:
    summary = result.get("executive_summary")
    judgment = result["judgment"]
    decision = judgment.investment_decision
    evidence = result["evidence"]

    st.markdown("### 首屏结论")
    cols = st.columns(4)
    with cols[0]:
        _metric_card("Verdict", _label(DECISION_LABELS, decision.decision) if decision else "暂无", "研究流程建议")
    with cols[1]:
        _metric_card("Confidence", _label(CONFIDENCE_LABELS, judgment.confidence), "规则层计算")
    with cols[2]:
        _metric_card("Evidence", len(evidence), "有效证据数量")
    with cols[3]:
        next_action = summary.next_action if summary else "暂无"
        _metric_card("Next Action", next_action[:32] + ("..." if len(next_action) > 32 else ""), "下一步动作")

    _card(
        "一句话结论",
        summary.one_line_conclusion if summary else judgment.conclusion,
        [_badge("研究初筛", "fact"), _badge(judgment.positioning or "定位待定", "medium"), _badge("非投资建议", "risk")],
    )

    risk_cols = st.columns(2)
    with risk_cols[0]:
        top_risks = judgment.risk[:3]
        _card(
            "Top Risks",
            "\n".join(f"- {item.text}" for item in top_risks) if top_risks else "当前未形成有证据支撑的主要风险。",
            [_badge("risk", "risk")],
        )
    with risk_cols[1]:
        actions = judgment.research_actions[:3]
        _card(
            "Next Actions",
            "\n".join(f"- [{item.priority}] {item.objective}" for item in actions) if actions else "暂无下一步研究动作。",
            [_badge("action", "medium")],
        )


def run_research(query: str) -> dict:
    progress = st.progress(0)
    progress_steps = {
        "define": 8,
        "decompose": 16,
        "financial_snapshot": 24,
        "retrieve": 35,
        "extract": 48,
        "variable": 58,
        "reason": 68,
        "action": 76,
        "auto_research": 84,
        "investment": 90,
        "roles": 95,
        "report": 100,
        "early_stop": 100,
    }

    def _live_progress(step: str, message: str, payload) -> None:
        progress.progress(progress_steps.get(step, 5))
        st.write(f"✓ {message}")
        if step == "define" and payload is not None:
            st.write(
                "研究对象："
                f"{payload.entity or '未识别'}｜对象类型：{getattr(payload, 'research_object_type', 'unknown')}"
                f"｜上市状态：{getattr(payload, 'listing_status', 'unknown')}"
            )
        elif step == "financial_snapshot" and payload is not None:
            st.write(f"Provider：{payload.provider}｜Symbol：{payload.symbol or '未解析'}｜Status：{payload.status}")
        elif step == "retrieve" and payload is not None:
            st.write(f"来源数量：{len(payload)}")
        elif step == "extract" and payload is not None:
            st.write(f"证据数量：{len(payload)}")

    with st.status("正在执行研究流程...", expanded=True) as status:
        result = research_pipeline(query, progress_callback=_live_progress)
        status.update(label="研究流程执行完成", state="complete", expanded=False)

    topic = result["topic"]
    questions = result["questions"]
    sources = result["sources"]
    evidence = result["evidence"]
    variables = result["variables"]
    roles = result["roles"]
    judgment = result["judgment"]
    auto_research_trace = result.get("auto_research_trace", [])
    executive_summary = result.get("executive_summary")
    financial_snapshot = result.get("financial_snapshot")
    early_stop_reason = result.get("early_stop_reason")
    report = result["report"]

    render_default_brief(result)
    render_confidence_guidance()
    if early_stop_reason:
        st.warning(f"早停原因：{early_stop_reason}")

    layer_tabs = st.tabs(["Layer 1｜默认结论", "Layer 2｜关键证据与风险", "Layer 3｜完整研究报告"])
    with layer_tabs[0]:
        render_executive_summary(executive_summary)
        _render_step_title(1, "明确研究对象", "识别研究对象、研究主题、目标和类型。")
        render_topic(topic)
        _render_step_title(10, "投资层处理建议", "系统正式输出的研究流程处理建议。")
        render_investment(judgment)

    with layer_tabs[1]:
        _render_step_title(2, "结构化金融快照", "公司类研究会调用真实结构化金融数据接口，用作初筛辅助，不替代官方财报。")
        render_financial_snapshot(financial_snapshot)
        _render_step_title(5, "提取有效证据", "默认只看证据表；需要时展开单条证据。")
        render_evidence(evidence, sources)
        _render_step_title(6, "关键投研变量", "把底层 evidence 翻译成更接近用户语言的变量。")
        render_variables(variables)
        _render_step_title(7, "综合研究判断", "展示结论、风险、缺口、置信度和压力测试。")
        render_judgment(judgment, evidence)
        _render_step_title(8, "下一步研究动作", "根据证据缺口和风险，生成可执行补证动作。")
        render_actions(judgment)
        _render_step_title(11, "多角色投研团队", "对第十步建议做组织化复核与补充视角。")
        render_roles(roles)

    with layer_tabs[2]:
        _render_step_title(3, "拆解研究框架", "把模糊问题拆成财务、现金流、行业、治理、风险等子问题。")
        render_questions(questions)
        _render_step_title(4, "多视角真实检索", "事实流、风险流、反证流分别检索；优先寻找官方公告、IR、交易所与专业财经来源。")
        render_sources(sources)
        _render_step_title(9, "自动补证记录", "如果初步判断低置信度，系统会按结构化 action 有限补证。")
        render_auto_research(auto_research_trace)
        _render_step_title(12, "可验证研究报告", "最终报告保留证据引用、来源 URL 和不确定性。")
        st.markdown(report.markdown)
        st.download_button(
            "下载 Markdown 报告",
            data=report.markdown,
            file_name=f"{topic.topic}_research_report.md",
            mime="text/markdown",
        )
    progress.progress(100)

    return result


def main() -> None:
    _install_styles()
    render_hero()

    with st.sidebar:
        st.header("流程导航")
        steps = [
            "明确研究对象",
            "结构化金融快照",
            "拆解研究框架",
            "多视角真实检索",
            "提取有效证据",
            "形成关键变量",
            "综合研究判断",
            "下一步研究动作",
            "自动补证记录",
            "投资层处理建议",
            "多角色投研团队",
            "可验证研究报告",
        ]
        for index, step in enumerate(steps, start=1):
            st.write(f"{index:02d}. {step}")
        st.divider()
        render_search_api_status()
        st.divider()
        st.caption("运行前请确认 `.env` 已配置 LLM key；搜索侧会自动使用上方已启用 provider。")
        st.caption("页面只负责展示，底层仍调用 research_pipeline。")
        st.divider()
        st.header("3 分钟演示话术")
        st.write("1. 先看首屏：Verdict / Confidence / Next Action。")
        st.write("2. 再看 Layer 2：关键证据、风险、变量和角色复核。")
        st.write("3. 最后打开 Layer 3：完整来源、自动补证和报告。")
        st.warning("定位：研究初筛工具，不是荐股工具。")

    default_query = "研究宁德时代是否值得进一步研究"
    input_cols = st.columns([4, 1])
    with input_cols[0]:
        query = st.text_input(
            "请输入研究主题",
            value=default_query,
            placeholder="例如：研究拼多多高增长模式是否可持续",
            label_visibility="collapsed",
        )
    with input_cols[1]:
        run_clicked = st.button("开始研究", type="primary", use_container_width=True)

    if run_clicked:
        clean_query = query.strip()
        if not clean_query:
            st.error("请输入非空研究主题。")
            return
        try:
            run_research(clean_query)
        except Exception as exc:
            st.error(f"运行失败：{type(exc).__name__}: {exc}")
            st.info("请检查 `.env` 中的 DASHSCOPE_API_KEY / TAVILY_API_KEY，以及网络连接。")
    else:
        st.info("输入一个研究主题后点击“开始研究”，页面会逐步展示每个投研步骤。")


if __name__ == "__main__":
    main()
