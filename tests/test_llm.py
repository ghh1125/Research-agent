from __future__ import annotations

import sys
from types import SimpleNamespace

from src.llm import ProviderConfig, RealLLMClient


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
