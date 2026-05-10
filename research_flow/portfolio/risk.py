from __future__ import annotations

import csv
import math
from io import StringIO

from research_flow.schema import EvidenceBundle


def compute_portfolio_risk_metrics(bundle: EvidenceBundle, positions: dict[str, float] | None = None) -> dict[str, float | str]:
    prices, volumes = _extract_price_history(bundle)
    metrics: dict[str, float | str] = {}
    returns = [(prices[idx] / prices[idx - 1]) - 1 for idx in range(1, len(prices)) if prices[idx - 1] != 0]
    if returns:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / len(returns)
        metrics["annualized_volatility"] = math.sqrt(variance) * math.sqrt(252)
    drawdown = _max_drawdown(prices)
    if drawdown is not None:
        metrics["max_drawdown"] = drawdown
    if volumes:
        metrics["average_volume"] = sum(volumes) / len(volumes)
    if positions:
        weights = [abs(value) for value in positions.values()]
        metrics["gross_exposure"] = sum(weights)
        metrics["largest_position_weight"] = max(weights) if weights else 0.0
        metrics["position_count"] = float(len(positions))
    metrics.setdefault("risk_data_quality", "market_data" if prices else "insufficient")
    return metrics


def _extract_price_history(bundle: EvidenceBundle) -> tuple[list[float], list[float]]:
    prices: list[float] = []
    volumes: list[float] = []
    for artifact in bundle.artifacts:
        if artifact.category != "market_data" or "Close" not in artifact.content:
            continue
        start = artifact.content.find("Date,")
        if start < 0:
            continue
        table = artifact.content[start:]
        reader = csv.DictReader(StringIO(table))
        for row in reader:
            try:
                close = row.get("Close") or row.get("close")
                if close:
                    prices.append(float(close))
                volume = row.get("Volume") or row.get("volume")
                if volume:
                    volumes.append(float(volume))
            except ValueError:
                continue
    return prices, volumes


def _max_drawdown(prices: list[float]) -> float | None:
    if not prices:
        return None
    peak = prices[0]
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        if peak:
            worst = min(worst, (price / peak) - 1)
    return worst
