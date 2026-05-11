from __future__ import annotations

from research_flow.schema import ManagerDecision, PortfolioDecision, TriggeredAlert


def build_tracking_alerts(
    manager: ManagerDecision,
    portfolio: PortfolioDecision,
    *,
    entity: str | None = None,
) -> list[TriggeredAlert]:
    subject = entity or "研究对象"
    alerts: list[TriggeredAlert] = [
        TriggeredAlert(
            label="财报复盘",
            reason=f"下次财报发布后重新检查 {subject} 的收入、毛利率和现金流假设。",
        ),
        TriggeredAlert(
            label="价格触发",
            reason=portfolio.revisit_trigger,
        ),
        TriggeredAlert(
            label="脆弱假设监控",
            reason=f"若以下假设被证伪请立即更新研究：{manager.fragile_assumption}",
        ),
    ]
    # Entity-specific metric alerts derived from manager's tracking list
    for metric in manager.tracking_metrics[:5]:
        alerts.append(
            TriggeredAlert(
                label=f"指标：{metric}",
                reason=f"{subject} 的 {metric} 出现明显变化时，重新评估判断（脆弱假设：{manager.fragile_assumption}）。",
            )
        )
    return alerts


def evaluate_keyword_alerts(news_titles: list[str], keywords: list[str]) -> list[TriggeredAlert]:
    text = " ".join(news_titles)
    return [TriggeredAlert(label=keyword, reason=f"news keyword matched: {keyword}") for keyword in keywords if keyword in text]
