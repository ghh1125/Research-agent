from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from app.models.evidence import Evidence
from app.models.question import Question
from app.models.source import Source
from app.models.topic import Topic
from app.services.evidence_engine import (
    is_usable_evidence_text,
    recency_score_for_source,
    relevance_score_for_text,
    score_evidence_text,
)

_CONTRAST_TOKENS = ["但是", "但", "然而", "不过", "却", "尽管", "虽然"]
_RISK_STANCE_TOKENS = [
    "风险",
    "承压",
    "为负",
    "集中度",
    "高杠杆",
    "短债",
    "处罚",
    "整改",
    "资金占用",
    "依赖",
    "违约",
    "逾期",
    "收缩",
    "无证经营",
    "下滑",
    "下降",
    "减少",
    "恶化",
    "差距",
    "利润下滑",
    "净利润同比下滑",
    "毛利率下降",
]
_COUNTER_STANCE_TOKENS = [
    "现金流转正",
    "回款改善",
    "杠杆改善",
    "债务下降",
    "治理改善",
    "内控完善",
    "客户多元化",
    "业务多元化",
    "牌照齐备",
    "资质完备",
    "合规通过",
    "未见重大处罚",
    "经营改善",
    "修复信号",
    "市场份额提升",
    "续约率提升",
]
_NOISE_TOKENS = [
    "javascript",
    "cookie",
    "privacy policy",
    "login",
    "sign up",
    "subscribe",
    "版权所有",
    "登录",
    "注册",
    "导航",
    "菜单",
    "首页",
    "免责声明",
    "点击",
    "展开",
    "扫码",
    "二维码",
    "分享到",
    "分享至",
    "热门搜索",
    "搜索历史",
    "收藏",
    "评论",
    "点赞",
    "微信",
    "微博",
    "空间",
    "作者：",
    "独立思考",
    ".docx",
    ".pdf",
    "发布于",
    "阅读全文",
    "相关推荐",
    "相关专题",
    "官方披露入口",
    "用于优先获取",
    "新闻 体育 娱乐 财经",
    "体育 娱乐 财经",
    "目录",
    "第一节",
    "释义",
    "董事长：",
    "联系电话",
    "传真",
    "邮箱",
    "电子信箱",
    "公司住所",
    "办公地址",
]
_GENERIC_BRIDGE_PHRASES = [
    "就在这样的行业环境中",
    "到这里答案就清晰了",
    "先看最核心",
    "更值得关注的是",
    "值得注意的是",
    "换句话说",
]
_TRUNCATED_NUMERIC_PATTERNS = [
    re.compile(r"^[\u4e00-\u9fffA-Za-z（）()]{2,18}\s*[-－]?\s*\d{1,4}(?:\.\d+)?$"),
    re.compile(r"^\d+(?:\.\d+)?\s*$"),
    re.compile(r"^第?\s*\d+\s*页?$"),
    re.compile(r"^\d+\s*/\s*\d+$"),
]
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"第\s*\d+\s*页"),
    re.compile(r"\d+\s*/\s*\d+"),
    re.compile(r"20\d{2}\s*年?\s*年度报告全文"),
    re.compile(r"年度报告全文"),
    re.compile(r"章节"),
    re.compile(r"联系电话"),
    re.compile(r"公司网址"),
    re.compile(r"法律声明"),
    re.compile(r"免责声明"),
]
_FINANCIAL_UNIT_TOKENS = [
    "亿元",
    "万元",
    "百万",
    "千元",
    "%",
    "同比",
    "环比",
    "百分点",
    "倍",
    "美元",
    "人民币",
    "港元",
]
_CONTEXT_TOKENS_FOR_NUMBERS = [
    "营收",
    "收入",
    "净利润",
    "毛利率",
    "现金流",
    "经营活动",
    "资产负债率",
    "负债",
    "费用率",
    "研发",
    "市场份额",
    "订单",
    "用户",
    "GMV",
    "增长",
    "下降",
    "改善",
    "承压",
]
_HIGH_VALUE_EVIDENCE_TOKENS = [
    "营业收入",
    "营收",
    "归母净利润",
    "净利润",
    "经营活动现金流",
    "经营活动产生的现金流量净额",
    "毛利率",
    "资产负债率",
    "CAPEX",
    "资本开支",
    "研发投入",
    "同比",
]
_PROMOTIONAL_TOKENS = [
    "创新驱动发展",
    "高质量发展",
    "持续创造价值",
    "公司愿景",
    "企业文化",
    "董事长讲话",
    "坚定推进",
    "砥砺前行",
    "再创辉煌",
]

_CURRENT_YEAR = datetime.now().year


def _source_content_for_extract(source: Source) -> str:
    return source.enriched_content or source.fetched_content or source.content


def _clean_text(text: str) -> str:
    cleaned = unescape(text)
    cleaned = re.sub(r"<(script|style|nav|footer|header).*?</\1>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"#{1,6}\s*", " ", cleaned)
    cleaned = re.sub(r"[*_`]+", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _is_meaningful_clause(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(token in lowered or token in text for token in _NOISE_TOKENS):
        return False
    if any(phrase in text for phrase in _GENERIC_BRIDGE_PHRASES):
        return False
    if "<" in text or ">" in text or "{" in text or "}" in text:
        return False
    if "[]" in text or "](" in text or text.count("[") >= 2 or text.count("]") >= 2:
        return False
    nav_tokens = ["新闻", "体育", "娱乐", "财经", "汽车", "科技", "时尚", "手机", "数码", "房产", "家居", "教育"]
    if sum(1 for token in nav_tokens if token in text) >= 4:
        return False
    ui_tokens = ["热门搜索", "搜索历史", "收藏", "评论", "点赞", "微信", "微博", "空间"]
    if sum(1 for token in ui_tokens if token in text) >= 2:
        return False
    meaningful_chars = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
    if meaningful_chars < 8:
        return False
    research_signal_tokens = [
        "增长",
        "下降",
        "风险",
        "承压",
        "现金流",
        "负债",
        "利润",
        "营收",
        "毛利率",
        "市场",
        "行业",
        "竞争",
        "产能",
        "合规",
        "监管",
        "关联交易",
        "内控",
        "治理",
        "依赖",
        "集中度",
        "客户",
        "价格",
        "亏损",
        "补贴",
        "份额",
        "债务",
    ]
    has_unit = any(token in text for token in _FINANCIAL_UNIT_TOKENS)
    has_context = any(token in text for token in _CONTEXT_TOKENS_FOR_NUMBERS)
    has_effective_verb = any(token in text for token in ["增长", "下降", "改善", "承压", "保持", "披露", "显示", "转正", "扩大", "收缩"])
    if len(text) < 10 and not (has_unit or has_context or has_effective_verb):
        return False
    if len(text) < 18 and not any(token in text for token in research_signal_tokens) and not re.search(r"\d", text):
        return False
    punctuation_ratio = len(re.findall(r"[|/_=<>#{}\\[\\]]", text)) / max(len(text), 1)
    weird_chars = len(re.findall(r"""[^\u4e00-\u9fffA-Za-z0-9\s，,。！？!?；;：:（）()《》“”"'/%+.\-]""", text))
    weird_ratio = weird_chars / max(len(text), 1)
    return punctuation_ratio < 0.15 and weird_ratio < 0.12


def is_noise_evidence(text: str) -> bool:
    """Reject table fragments, page numbers, UI text and incomplete numeric rows."""

    stripped = re.sub(r"\s+", " ", text or "").strip(" ，,。；;：:")
    if not stripped:
        return True
    lowered = stripped.lower()
    if any(token in lowered or token in stripped for token in _NOISE_TOKENS):
        return True
    if any(pattern.search(stripped) for pattern in _HEADER_FOOTER_PATTERNS):
        return True
    if any(token in stripped for token in _PROMOTIONAL_TOKENS) and not re.search(r"\d", stripped):
        return True
    if "<" in stripped or ">" in stripped or "](" in stripped or "javascript:" in lowered:
        return True
    if any(pattern.match(stripped) for pattern in _TRUNCATED_NUMERIC_PATTERNS):
        return True

    digits = len(re.findall(r"\d", stripped))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    letters = len(re.findall(r"[A-Za-z]", stripped))
    has_context = any(token in stripped for token in _CONTEXT_TOKENS_FOR_NUMBERS)
    has_unit = any(token in stripped for token in _FINANCIAL_UNIT_TOKENS)
    has_direction = any(token in stripped for token in ["增长", "下降", "改善", "承压", "保持", "转正", "扩大", "收缩"])

    if digits and len(stripped) <= 16 and not (has_context and (has_unit or has_direction)):
        return True
    if digits >= 1 and cjk + letters <= 4 and not has_unit:
        return True
    if len(stripped) < 14 and not has_context and not has_unit:
        return True
    return False


def is_truncated_fragment(text: str) -> bool:
    """Detect OCR/table fragments that contain numbers but lack a complete metric value."""

    stripped = re.sub(r"\s+", " ", text or "").strip(" ，,。；;：:")
    if not stripped or not re.search(r"\d", stripped):
        return False
    if any(unit in stripped for unit in _FINANCIAL_UNIT_TOKENS):
        return False
    numbers = re.findall(r"\d+(?:\.\d+)?", stripped)
    has_context = any(token in stripped for token in _CONTEXT_TOKENS_FOR_NUMBERS)
    has_direction = any(token in stripped for token in ["同比", "增长", "下降", "改善", "承压", "保持", "转正"])
    starts_or_ends_with_loose_number = bool(re.match(r"^\d+(?:\.\d+)?\s+", stripped) or re.search(r"\s+\d+(?:\.\d+)?$", stripped))
    if has_context and starts_or_ends_with_loose_number and not has_direction:
        return True
    if len(numbers) >= 2 and has_context and not has_direction:
        return True
    return False


def _has_high_value_financial_evidence(text: str) -> bool:
    if not any(token in text for token in _HIGH_VALUE_EVIDENCE_TOKENS):
        return False
    return bool(re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|百万|千元|美元|人民币|港元|%|百分点|倍)", text))


def _information_density_adjustment(text: str) -> tuple[float, list[str]]:
    """Reward complete metric rows and penalize empty slogans."""

    notes: list[str] = []
    adjustment = 0.0
    metric_hits = sum(1 for token in _HIGH_VALUE_EVIDENCE_TOKENS if token in text)
    complete_values = re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|百万|千元|美元|人民币|港元|%|百分点|pct|倍)", text, flags=re.IGNORECASE)
    has_yoy = any(token in text for token in ["同比", "同比增长", "同比下降", "较上年", "较去年"])
    has_comparison = has_yoy or any(token in text for token in ["环比", "同期", "上年同期", "同比增减"])
    if metric_hits >= 2:
        adjustment += 0.06
        notes.append("multi_metric_row")
    if metric_hits and complete_values and has_yoy:
        adjustment += 0.08
        notes.append("metric_value_yoy")
    if has_comparison:
        adjustment += 0.04
        notes.append("period_comparison")
    if any(token in text for token in _PROMOTIONAL_TOKENS):
        adjustment -= 0.14
        notes.append("promotional_language_penalty")
    if re.search(r"(营业收入|净利润|毛利率|现金流|资产负债率)\s+\d{1,2}(?:\s|$)", text) and not complete_values:
        adjustment -= 0.18
        notes.append("incomplete_table_field_penalty")
    return adjustment, notes


def _staleness_adjustment(text: str, source: Source) -> tuple[float, list[str]]:
    """Penalize old fiscal-year evidence without discarding it completely."""

    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", " ".join([source.published_at or "", source.title, text]))]
    if not years:
        return 1.0, []
    latest_year = max(years)
    if latest_year < _CURRENT_YEAR - 1:
        return 0.5, ["stale_source", f"latest_year={latest_year}"]
    return 1.0, []


def _calc_clarity_score(text: str) -> float:
    """Readable investment evidence requires context, not just numbers."""

    stripped = re.sub(r"\s+", " ", text or "").strip()
    if is_noise_evidence(stripped):
        return 0.0

    cjk = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    letters = len(re.findall(r"[A-Za-z]", stripped))
    digits = len(re.findall(r"\d", stripped))
    has_context = any(token in stripped for token in _CONTEXT_TOKENS_FOR_NUMBERS)
    has_unit = any(token in stripped for token in _FINANCIAL_UNIT_TOKENS)
    sentence_shape = 0.18 if len(stripped) >= 24 else 0.06
    context_score = 0.28 if has_context else 0.0
    unit_score = 0.18 if digits and has_unit else 0.0
    alpha_score = min((cjk + letters) / 80, 0.28)
    number_score = 0.08 if digits and has_context else 0.0
    punctuation_penalty = min(len(re.findall(r"[|/_=<>#{}\\[\\]]", stripped)) / max(len(stripped), 1), 0.2)
    score = sentence_shape + context_score + unit_score + alpha_score + number_score - punctuation_penalty
    return max(0.0, min(1.0, round(score, 3)))


def _split_sentences(content: str) -> list[str]:
    cleaned = _clean_text(content)
    parts = re.split(r"[。！？!?；;]\s*", cleaned)
    return [part.strip(" ，,") for part in parts if _is_meaningful_clause(part.strip(" ，,"))]


def _split_clauses(sentence: str) -> list[str]:
    stripped = sentence.strip()
    if any(token in stripped for token in _CONTRAST_TOKENS):
        # Keep full sentence when it contains contrast so support/counter meaning is not fragmented.
        return [stripped] if _is_meaningful_clause(stripped) else []

    parts = re.split(r"[，,、]|且|并且|同时|以及", stripped)
    return [part.strip() for part in parts if _is_meaningful_clause(part.strip())]


def _normalize_clause_for_evidence(text: str) -> str:
    normalized = text.strip(" ，,。")
    normalized = re.sub(r"^.*?作者[:：]\S+\s+", "", normalized)
    normalized = re.sub(r"^\d{1,2}\s*[：:]\s*", "", normalized)
    normalized = re.sub(r"^\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}\s*", "", normalized)
    normalized = re.sub(r"^(利润为什么跑赢营收|先看最核心的利润表数据)\s*", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _classify_evidence(text: str) -> str:
    if any(token in text for token in ["认为", "指出", "提到", "披露", "称"]):
        return "claim"
    if re.search(r"\d", text) or any(token in text for token in ["增长", "下降", "比例", "毛利率", "资产负债率", "现金流"]):
        return "data"
    if any(token in text for token in _RISK_STANCE_TOKENS):
        return "risk_signal"
    return "fact"


def _infer_stance(text: str, flow_type: str = "fact") -> str:
    if any(token in text for token in _COUNTER_STANCE_TOKENS):
        return "counter"
    if any(token in text for token in ["未见", "未出现", "未触发", "不存在", "不构成"]):
        return "counter"
    if any(token in text for token in _CONTRAST_TOKENS) and any(
        token in text for token in ["改善", "转正", "修复", "齐备", "完备", "通过", "多元化", "缓解", "回升"]
    ):
        return "counter"
    if any(token in text for token in _RISK_STANCE_TOKENS):
        return "support"
    if flow_type == "counter" and any(token in text for token in ["改善", "增长", "提升", "修复", "缓解", "拐点", "领先"]):
        return "counter"
    if flow_type == "risk" and any(token in text for token in ["风险", "承压", "下行", "亏损", "处罚", "负债", "竞争"]):
        return "support"
    return "neutral"


def _normalize_for_dedup(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    return re.sub(r"[，,。！？!?；;：:\-\(\)（）、]", "", normalized)


def _normalize_for_grounding(text: str) -> str:
    cleaned = _clean_text(text)
    return re.sub(r"[\s，,。！？!?；;：:\-\(\)（）、\"'“”‘’\[\]]+", "", cleaned)


def verify_evidence_grounding(content: str, source: Source) -> bool:
    """Return True when evidence text is anchored in source content."""

    evidence_text = _normalize_for_grounding(content)
    source_text = _normalize_for_grounding(_source_content_for_extract(source))
    if not evidence_text or not source_text:
        return False
    key_fragment = evidence_text[: min(20, len(evidence_text))]
    if len(key_fragment) < 8:
        return False
    return key_fragment in source_text


def _match_question_id(clause: str, questions: list[Question], default_index: int) -> str | None:
    keyword_map = {
        "案例": ["案例", "样本", "历史上", "公开资料"],
        "机制": ["驱动", "成因", "导致", "机制"],
        "财务": ["资产负债率", "现金流", "回款", "应收账款", "毛利率", "短债"],
        "经营": ["客户", "订单", "经营", "供应链", "产品", "业务"],
        "预警": ["风险信号", "预警", "处罚", "整改", "为负", "承压"],
        "合规": ["监管", "合规", "牌照", "许可", "授权", "经营权", "合同"],
    }
    for question in questions:
        if any(token in question.content for token in keyword_map["合规"]) and any(token in clause for token in keyword_map["合规"]):
            return question.id
        if any(token in question.content for token in keyword_map["财务"]) and any(token in clause for token in keyword_map["财务"]):
            return question.id
        if any(token in question.content for token in keyword_map["经营"]) and any(token in clause for token in keyword_map["经营"]):
            return question.id
        if any(token in question.content for token in keyword_map["案例"]) and any(token in clause for token in keyword_map["案例"]):
            return question.id
        if any(token in question.content for token in keyword_map["预警"]) and any(token in clause for token in keyword_map["预警"]):
            return question.id
    if questions:
        return questions[default_index % len(questions)].id
    return None


def extract_evidence(
    topic: Topic,
    questions: list[Question],
    sources: list[Source],
) -> list[Evidence]:
    """Extract structured evidence directly from source content."""

    evidence_list: list[Evidence] = []
    candidates: list[Evidence] = []
    seen_content_by_source: set[tuple[str, str]] = set()

    for source_index, source in enumerate(sources):
        sentences = _split_sentences(_source_content_for_extract(source))
        for sentence in sentences:
            for clause in _split_clauses(sentence):
                normalized_clause = _normalize_clause_for_evidence(clause)
                if not _is_meaningful_clause(normalized_clause):
                    continue
                if is_noise_evidence(normalized_clause):
                    continue
                if not verify_evidence_grounding(normalized_clause, source):
                    continue
                if not is_usable_evidence_text(normalized_clause, source, topic):
                    continue
                dedup_key = (source.id, _normalize_for_dedup(normalized_clause))
                if dedup_key in seen_content_by_source:
                    continue
                seen_content_by_source.add(dedup_key)
                evidence_score, quality_notes = score_evidence_text(normalized_clause, source, topic)
                is_truncated = is_truncated_fragment(normalized_clause)
                if is_truncated:
                    evidence_score = round(evidence_score * 0.3, 3)
                    quality_notes = [*quality_notes, "truncated_numeric_fragment"]
                elif _has_high_value_financial_evidence(normalized_clause):
                    evidence_score = min(1.0, round(evidence_score + 0.12, 3))
                    quality_notes = [*quality_notes, "high_value_financial_metric"]
                density_adjustment, density_notes = _information_density_adjustment(normalized_clause)
                evidence_score = max(0.0, min(1.0, round(evidence_score + density_adjustment, 3)))
                quality_notes = [*quality_notes, *density_notes]
                staleness_factor, staleness_notes = _staleness_adjustment(normalized_clause, source)
                if staleness_factor < 1.0:
                    evidence_score = round(evidence_score * staleness_factor, 3)
                    quality_notes = [*quality_notes, *staleness_notes]
                clarity_score = _calc_clarity_score(normalized_clause)
                if clarity_score <= 0:
                    continue
                relevance_score = relevance_score_for_text(normalized_clause, topic, source)
                if clarity_score < 0.35:
                    quality_notes = [*quality_notes, "low_clarity_or_insufficient_context"]
                    relevance_score = max(0.0, round(relevance_score - 0.1, 3))
                recency_score = recency_score_for_source(source)
                candidates.append(
                    Evidence(
                        id="pending",
                        topic_id=topic.id,
                        question_id=_match_question_id(normalized_clause, questions, source_index),
                        source_id=source.id,
                        flow_type=source.flow_type,
                        content=normalized_clause,
                        evidence_type=_classify_evidence(normalized_clause),
                        stance=_infer_stance(normalized_clause, source.flow_type),
                        grounded=True,
                        is_noise=False,
                        is_truncated=is_truncated,
                        quality_score=evidence_score,
                        quality_notes=quality_notes,
                        source_tier=source.tier.value,
                        source_score=source.source_score,
                        relevance_score=relevance_score,
                        clarity_score=clarity_score,
                        recency_score=recency_score,
                        evidence_score=evidence_score,
                    )
                )

    flow_order = {"fact": 0, "risk": 1, "counter": 2}
    candidates.sort(
        key=lambda item: (
            -(item.evidence_score or item.quality_score or 0),
            flow_order.get(item.flow_type, 99),
            item.source_id,
        )
    )
    primary_candidates = [item for item in candidates if not item.is_truncated]
    overflow_candidates = [item for item in candidates if item.is_truncated]
    selected_candidates = (primary_candidates + overflow_candidates)[:12]
    evidence_list = [item.model_copy(update={"id": f"e{index}"}) for index, item in enumerate(selected_candidates, start=1)]
    return evidence_list[: max(3, len(evidence_list))]
