from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from research_flow.schema import TriggeredAlert


@dataclass(frozen=True)
class TrackingRule:
    symbol: str
    kind: Literal["price_below", "price_above", "news_keyword"]
    label: str
    threshold: float | None = None
    keyword: str | None = None


class TrackingRunner:
    """Scheduled tracking core without owning the external scheduler."""

    def __init__(self, rules: list[TrackingRule]) -> None:
        self.rules = rules

    def evaluate(self, symbol: str, *, price: float | None = None, news_titles: list[str] | None = None) -> list[TriggeredAlert]:
        alerts: list[TriggeredAlert] = []
        text = " ".join(news_titles or []).lower()
        for rule in self.rules:
            if rule.symbol.upper() != symbol.upper():
                continue
            if rule.kind == "price_below" and price is not None and rule.threshold is not None and price <= rule.threshold:
                alerts.append(TriggeredAlert(label=rule.label, reason=f"{symbol} price {price} <= {rule.threshold}"))
            elif rule.kind == "price_above" and price is not None and rule.threshold is not None and price >= rule.threshold:
                alerts.append(TriggeredAlert(label=rule.label, reason=f"{symbol} price {price} >= {rule.threshold}"))
            elif rule.kind == "news_keyword" and rule.keyword and rule.keyword.lower() in text:
                alerts.append(TriggeredAlert(label=rule.label, reason=f"{symbol} news keyword matched: {rule.keyword}"))
        return alerts
