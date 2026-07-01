from __future__ import annotations

import sys
from dataclasses import replace
from types import SimpleNamespace

from pydantic import BaseModel

from src.llm import ProviderConfig, RealLLMClient
from src.settings import get_settings


class _JSONResult(BaseModel):
    ok: bool


def test_dashscope_qwen_37_json_request_disables_thinking(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = RealLLMClient()

    client._request_content(
        ProviderConfig("dashscope", "secret", "https://example.test", "qwen3.7-plus"),
        [{"role": "user", "content": "return json"}],
    )

    assert calls[0]["extra_body"] == {"enable_thinking": False}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_non_dashscope_request_does_not_set_qwen_thinking_flag(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = RealLLMClient()

    client._request_content(
        ProviderConfig("openai", "secret", "https://example.test", "gpt-4.1"),
        [{"role": "user", "content": "return json"}],
    )

    assert "extra_body" not in calls[0]


def test_dashscope_hybrid_thinking_model_disables_thinking_for_json(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = RealLLMClient()

    for model in ("deepseek-v4-pro", "deepseek-v4-flash", "glm-5.2", "glm-5.1", "kimi-k2.6"):
        client._request_content(
            ProviderConfig("dashscope", "secret", "https://example.test", model),
            [{"role": "user", "content": "return json"}],
        )

    assert all(call["extra_body"] == {"enable_thinking": False} for call in calls)
    assert all("temperature" not in call for call in calls)


def test_dashscope_kimi_code_keeps_required_thinking_mode(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = RealLLMClient()

    client._request_content(
        ProviderConfig("dashscope", "secret", "https://example.test", "kimi-k2.7-code"),
        [{"role": "user", "content": "return json"}],
    )

    assert "extra_body" not in calls[0]
    assert "temperature" not in calls[0]


def test_dashscope_explicit_model_has_stable_json_fallback_models(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = replace(
        get_settings(),
        dashscope_api_key="secret",
        dashscope_model="deepseek-v4-pro",
    )
    client = RealLLMClient(settings=settings)

    candidates = client._provider("dashscope", explicit_model="kimi-k2.7-code")

    assert [item.model for item in candidates] == [
        "kimi-k2.7-code",
        "qwen3.7-plus",
        "qwen3.6-plus",
    ]


def test_complete_json_repairs_empty_response_then_switches_model(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = replace(
        get_settings(),
        dashscope_api_key="secret",
        dashscope_model="kimi-k2.7-code",
    )
    client = RealLLMClient(settings=settings)
    calls: list[str] = []

    def request(provider, messages):
        calls.append(provider.model)
        if provider.model == "kimi-k2.7-code":
            return ""
        return '{"ok": true}'

    monkeypatch.setattr(client, "_request_content", request)

    result = client.complete_json(
        "Return JSON",
        _JSONResult,
        context={"provider": "dashscope", "model": "kimi-k2.7-code"},
    )

    assert result.ok is True
    assert calls == [
        "kimi-k2.7-code",
        "kimi-k2.7-code",
        "kimi-k2.7-code",
        "qwen3.7-plus",
    ]
