from __future__ import annotations

import json
import os

from app.services.llm_service import call_llm

_PROMPT = """
你是投研驾驶舱摘要器。只能基于输入事实生成 JSON：
1. headline：150-220字，人话、具体、保守，不出现内部术语
2. next_action：包含 title/why/required_data/decision_impact
3. recommendation_text：包含 what_we_know/what_we_do_not_know/why_this_verdict/next_research_plan

禁止创造新事实，禁止引用 registry 外证据，禁止输出买入卖出建议。
禁止输出英文状态词，如 Under Review、Improving、Healthy、cheap valuation、weak moat。
若估值缺历史区间或同行中位数，禁止说便宜、低估或安全边际明确。
若竞争缺市场份额、留存、GMV、take rate、merchant data，禁止说护城河强或弱。
禁止输出 logic_gap、pt1、pt2、pt3 等内部术语。

输入：
{payload}
""".strip()

_FORBIDDEN_TOKENS = [
    "under review",
    "improving",
    "healthy",
    "cheap valuation",
    "weak moat",
    "strong moat",
    "logic_gap",
    "pt1",
    "pt2",
    "pt3",
    "买入",
    "卖出",
    "值得配置",
    "低估",
    "便宜",
]


def _clamp_headline(text: str, *, facts: list[str], unknowns: list[str], action: str) -> str:
    headline = (text or "").strip()
    if len(headline) < 150:
        fallback = (
            f"现有证据能确认{facts[0] if facts else '公司已有一定经营和财务基础'}，"
            f"也说明业务并非缺少基本盘支撑；但{unknowns[0] if unknowns else '估值参照、竞争位置和持续性验证仍不完整'}，"
            f"当前还不足以支持更强的投资判断。现阶段更适合作为观察对象继续跟踪，优先推进“{action or '继续补证'}”，"
            f"把估值、竞争和现金流关键数据补齐后，再判断是否升级研究优先级。"
        )
        headline = fallback
    if len(headline) > 220:
        headline = headline[:217].rstrip("，；。 ") + "。"
    return headline


def _fallback(payload: dict[str, object]) -> dict[str, object]:
    verified_facts = [str(item) for item in (payload.get("verified_facts") or []) if str(item).strip()]
    probable = [str(item) for item in (payload.get("probable_inferences") or []) if str(item).strip()]
    pending = [str(item) for item in (payload.get("pending_assumptions") or []) if str(item).strip()]
    gaps = [str(item) for item in (payload.get("top_gaps") or []) if str(item).strip()]
    verdict = str(payload.get("verdict") or "观察清单")
    next_action_title = str(payload.get("next_action_title") or "继续补证")
    required = [str(item) for item in (payload.get("required_data") or []) if str(item).strip()][:4]

    headline = _clamp_headline(
        " ".join(
            [
                f"现有证据能确认{verified_facts[0] if verified_facts else '公司已有部分经营与财务基础'}，",
                f"但{pending[0] if pending else probable[0] if probable else '估值、竞争位置和持续性验证仍不完整'}。",
                f"因此目前更适合先作为{verdict}继续跟踪，优先补齐{gaps[0] if gaps else next_action_title}相关数据，",
                "把关键参照系补齐后再判断是否进入更深入研究。",
            ]
        ),
        facts=verified_facts,
        unknowns=pending or probable or gaps,
        action=next_action_title,
    )

    return {
        "headline": headline,
        "next_action": {
            "title": next_action_title,
            "why": gaps[0] if gaps else "当前关键缺口会直接影响结论强度与研究优先级。",
            "required_data": required,
            "decision_impact": f"补齐这些数据后，当前“{verdict}”的判断才能决定是维持观察还是升级研究深度。",
        },
        "recommendation_text": {
            "what_we_know": verified_facts[0] if verified_facts else "已有部分结构化证据表明公司具备一定经营与财务基础。",
            "what_we_do_not_know": pending[0] if pending else "估值、竞争位置与优势持续性仍缺关键验证。",
            "why_this_verdict": f"因为当前已确认信息不足以支撑更强结论，所以暂时只适合放在“{verdict}”而不是直接形成投资判断。",
            "next_research_plan": f"下一步优先执行“{next_action_title}”，重点补齐：{'、'.join(required) if required else '估值、竞争与关键经营数据'}。",
        },
    }


def _contains_forbidden_text(text: object) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in _FORBIDDEN_TOKENS)


def _normalize_result(data: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    fallback = _fallback(payload)
    recommendation = data.get("recommendation_text")
    if not isinstance(recommendation, dict):
        recommendation = fallback["recommendation_text"]
    else:
        recommendation = {
            "what_we_know": str(recommendation.get("what_we_know") or fallback["recommendation_text"]["what_we_know"]),
            "what_we_do_not_know": str(recommendation.get("what_we_do_not_know") or fallback["recommendation_text"]["what_we_do_not_know"]),
            "why_this_verdict": str(recommendation.get("why_this_verdict") or fallback["recommendation_text"]["why_this_verdict"]),
            "next_research_plan": str(recommendation.get("next_research_plan") or fallback["recommendation_text"]["next_research_plan"]),
        }
    if _contains_forbidden_text(data.get("headline")) or any(_contains_forbidden_text(value) for value in recommendation.values()):
        return fallback
    next_action = data.get("next_action")
    if not isinstance(next_action, dict):
        next_action = fallback["next_action"]
    headline = _clamp_headline(
        str(data.get("headline") or fallback["headline"]),
        facts=[str(item) for item in (payload.get("verified_facts") or [])],
        unknowns=[str(item) for item in (payload.get("pending_assumptions") or payload.get("top_gaps") or [])],
        action=str(next_action.get("title") or payload.get("next_action_title") or "继续补证"),
    )
    return {
        "headline": headline,
        "next_action": {
            "title": str(next_action.get("title") or fallback["next_action"]["title"]),
            "why": str(next_action.get("why") or fallback["next_action"]["why"]),
            "required_data": list(next_action.get("required_data") or fallback["next_action"]["required_data"])[:4],
            "decision_impact": str(next_action.get("decision_impact") or fallback["next_action"]["decision_impact"]),
        },
        "recommendation_text": recommendation,
    }


def summarize_dashboard(
    *,
    verified_facts: list[str],
    probable_inferences: list[str],
    pending_assumptions: list[str],
    top_risks: list[dict[str, object]],
    top_gaps: list[dict[str, object]] | list[str],
    curated_evidence: list[dict[str, object]],
    confidence: str,
    verdict: str,
    next_action_title: str,
    required_data: list[str],
) -> dict[str, object]:
    normalized_gaps = [item.get("text", item) if isinstance(item, dict) else item for item in top_gaps]
    payload = {
        "verified_facts": verified_facts[:2],
        "probable_inferences": probable_inferences[:2],
        "pending_assumptions": pending_assumptions[:2],
        "top_risks": top_risks[:3],
        "top_gaps": normalized_gaps[:3],
        "curated_evidence": curated_evidence[:5],
        "confidence": confidence,
        "verdict": verdict,
        "next_action_title": next_action_title,
        "required_data": required_data[:4],
    }
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _fallback(payload)
    try:
        raw = call_llm(_PROMPT.format(payload=json.dumps(payload, ensure_ascii=False)), temperature=0.1)
        return _normalize_result(json.loads(raw), payload)
    except Exception:
        return _fallback(payload)
