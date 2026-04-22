from __future__ import annotations

from pydantic import BaseModel, Field


class FinancialMetric(BaseModel):
    """Structured market/financial metric from a real data provider."""

    name: str
    value: float | str | None
    unit: str | None = None
    period: str | None = None
    source: str


class ProviderAttempt(BaseModel):
    """One structured attempt against a financial data provider."""

    provider: str
    symbol: str | None = None
    market: str | None = None
    status: str
    message: str
    retryable: bool = False
    fallback_available: bool = False
    next_provider: str | None = None
    latency_ms: int | None = None
    error_type: str | None = None


class FinancialSnapshot(BaseModel):
    """Lightweight structured financial snapshot for a company."""

    entity: str
    symbol: str | None = None
    provider: str
    status: str
    provider_status: ProviderAttempt | None = None
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list)
    fallback_used: bool = False
    success_provider: str | None = None
    metrics: list[FinancialMetric] = Field(default_factory=list)
    peer_symbols: list[str] = Field(default_factory=list)
    peer_comparison: list[dict] = Field(default_factory=list)
    valuation: dict = Field(default_factory=dict)
    note: str | None = None
