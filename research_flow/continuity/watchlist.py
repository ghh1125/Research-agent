from __future__ import annotations

from research_flow.schema import ManagerDecision, PortfolioDecision, TriggeredAlert


def build_tracking_alerts(manager: ManagerDecision, portfolio: PortfolioDecision) -> list[TriggeredAlert]:
    return [
        TriggeredAlert(label="财报复盘", reason="下一次财报发布后重新检查收入、毛利率和现金流假设。"),
        TriggeredAlert(label="新闻触发", reason="公告、监管、价格战、海外政策相关新闻触发更新。"),
        TriggeredAlert(label="价格触发", reason=portfolio.revisit_trigger),
    ]


def evaluate_keyword_alerts(news_titles: list[str], keywords: list[str]) -> list[TriggeredAlert]:
    text = " ".join(news_titles)
    return [TriggeredAlert(label=keyword, reason=f"news keyword matched: {keyword}") for keyword in keywords if keyword in text]
