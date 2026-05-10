from __future__ import annotations

import re
from datetime import date
from hashlib import md5

from research_flow.schema import QuestionType, ResearchDepth, ResearchTask, RiskPreference

ENTITY_ALIASES: dict[str, dict[str, object]] = {
    "宁德时代": {"symbols": ["300750.SZ"], "market": "A_share"},
    "阿里巴巴": {"symbols": ["BABA", "9988.HK"], "market": "US/HK"},
    "腾讯": {"symbols": ["0700.HK"], "market": "HK"},
    "比亚迪": {"symbols": ["002594.SZ", "1211.HK"], "market": "A_share/HK"},
    "英伟达": {"symbols": ["NVDA"], "market": "US"},
    "苹果": {"symbols": ["AAPL"], "market": "US"},
    "特斯拉": {"symbols": ["TSLA"], "market": "US"},
    "美团": {"symbols": ["3690.HK"], "market": "HK"},
}


def _guess_entity(query: str) -> str | None:
    for name in ENTITY_ALIASES:
        if name in query:
            return name
    match = re.search(r"(?:研究|分析|复盘|看看)([\u4e00-\u9fffA-Za-z0-9 ._-]{2,32})", query)
    if match:
        candidate = match.group(1)
        candidate = re.split(r"的|是否|还能|行业|财务|估值|风险|影响", candidate)[0].strip()
        return candidate or None
    return None


def _infer_question_type(query: str, entity: str | None) -> QuestionType:
    lowered = query.lower()
    if any(token in query for token in ("组合", "持仓", "仓位", "回撤", "暴露", "相关性")):
        return "portfolio_risk_review"
    if any(token in query for token in ("买", "卖", "加仓", "减仓", "入场", "止损", "交易")) or any(token in lowered for token in ("buy", "sell", "trade")):
        return "trading_decision_assist"
    if any(token in query for token in ("事件", "影响", "制裁", "并购", "降息", "政策落地", "突发")):
        return "event_impact"
    if any(token in query for token in ("行业比较", "同行比较", "横向比较", "赛道对比", "行业格局")):
        return "industry_comparison"
    if entity:
        return "single_stock_deep_dive"
    return "industry_comparison" if "行业" in query else "single_stock_deep_dive"


def _infer_depth(query: str, question_type: QuestionType) -> ResearchDepth:
    if any(token in query for token in ("深度", "完整", "全面", "投委会", "详细")):
        return "deep"
    if question_type in {"single_stock_deep_dive", "industry_comparison", "portfolio_risk_review"}:
        return "standard"
    return "quick"


def _infer_horizon(query: str) -> str:
    match = re.search(r"(\d+\s*(?:天|周|个月|年)|\d+\s*[-到至]\s*\d+\s*(?:天|周|个月|年))", query)
    if match:
        return match.group(1).replace(" ", "")
    if "短线" in query or "交易" in query:
        return "1-4周"
    if "长期" in query or "三年" in query:
        return "3年以上"
    return "6-12个月"


def _infer_risk(query: str) -> RiskPreference:
    if any(token in query for token in ("保守", "稳健", "低风险", "防守")):
        return "conservative"
    if any(token in query for token in ("激进", "高风险", "进攻", "高弹性")):
        return "aggressive"
    return "neutral"


def parse_task(
    query: str,
    *,
    symbols: list[str] | None = None,
    entity: str | None = None,
    market: str | None = None,
    time_range: str | None = None,
    horizon: str | None = None,
    question_type: QuestionType | None = None,
    output_format: str | None = None,
    risk_preference: RiskPreference | None = None,
    research_depth: ResearchDepth | None = None,
    model_profile: str | None = None,
    quick_model: str | None = None,
    deep_model: str | None = None,
    output_language: str = "zh-CN",
) -> ResearchTask:
    clean = query.strip()
    if not clean:
        raise ValueError("query must not be empty")
    resolved_entity = entity or _guess_entity(clean)
    alias = ENTITY_ALIASES.get(resolved_entity or "", {})
    resolved_symbols = symbols or list(alias.get("symbols", []))
    resolved_market = market or str(alias.get("market", "other"))
    resolved_type = question_type or _infer_question_type(clean, resolved_entity)
    resolved_depth = research_depth or _infer_depth(clean, resolved_type)
    resolved_output = output_format or (
        "decision_memo"
        if resolved_type == "trading_decision_assist"
        else "risk_review"
        if resolved_type == "portfolio_risk_review"
        else "institutional_research_report"
    )
    return ResearchTask(
        id=f"task_{md5(clean.encode('utf-8')).hexdigest()[:10]}",
        raw_query=clean,
        symbols=resolved_symbols,
        entity=resolved_entity,
        market=resolved_market,
        time_range=time_range or date.today().isoformat(),
        horizon=horizon or _infer_horizon(clean),
        question_type=resolved_type,
        output_format=resolved_output,
        risk_preference=risk_preference or _infer_risk(clean),
        research_depth=resolved_depth,
        model_profile=model_profile or "default",
        quick_model=quick_model,
        deep_model=deep_model,
        output_language=output_language,
    )


parse_research_task = parse_task


def parse_task_with_llm(query: str, llm_client, **overrides) -> ResearchTask:
    prompt = f"""
你是投研任务解析器。用户输入一个自然语言投研问题后，你要判断它属于：
single_stock_deep_dive、industry_comparison、event_impact、portfolio_risk_review、trading_decision_assist。
然后输出标准化 ResearchTask，包括 symbols、entity、market、time_range、horizon、question_type、output_format、risk_preference、research_depth。
如用户显式传入覆盖参数，必须尊重。

用户问题：{query}
覆盖参数：{overrides}
""".strip()
    task = llm_client.complete_json(
        prompt,
        ResearchTask,
        role="quick",
        context={
            "stage": "task_parser",
            "quick_model": overrides.get("quick_model"),
            "deep_model": overrides.get("deep_model"),
        },
    )
    data = task.model_dump()
    data.update({key: value for key, value in overrides.items() if value is not None})
    if data.get("raw_query") != query:
        data["raw_query"] = query
    data["id"] = f"task_{md5(query.strip().encode('utf-8')).hexdigest()[:10]}"
    return ResearchTask.model_validate(data)
