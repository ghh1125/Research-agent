from __future__ import annotations

import sys
import typing
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fake_value(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return typing.get_args(annotation)[0]
    if annotation is str:
        return "占位文本"
    if origin in (list,):
        return []
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _fake_value(args[0]) if args else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fill_required(annotation)
    return "占位文本"


def _fill_required(schema: type[BaseModel]) -> dict[str, Any]:
    """Fill every required field with a placeholder. Optional list[BaseModel] fields also get one
    synthesized item, so pipeline code that expects at least one row (e.g. competitor candidates)
    keeps working against the fake client."""

    kwargs: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        annotation = field.annotation
        if field.is_required():
            kwargs[name] = _fake_value(annotation)
            continue
        origin = typing.get_origin(annotation)
        if origin is list:
            args = typing.get_args(annotation)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                kwargs[name] = [_fill_required(args[0])]
    return kwargs


class FakeLLMClient:
    """Deterministic stand-in for RealLLMClient: fills every required field with a placeholder, no network calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete_json(self, prompt: str, schema: type[BaseModel], *, context: dict[str, Any] | None = None) -> BaseModel:
        self.calls.append(schema.__name__)
        return schema.model_validate(_fill_required(schema))


class FakeSearchClient:
    """Deterministic stand-in for RealSearchClient: returns one canned result per query, no network calls."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, category: str = "general", max_results: int = 5) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [{"title": f"fake result: {query}", "url": "https://example.com/fake", "content": "fake content", "provider": "fake"}]


@pytest.fixture
def fake_llm_client() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fake_search_client() -> FakeSearchClient:
    return FakeSearchClient()
