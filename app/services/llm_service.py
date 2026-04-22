from __future__ import annotations

from app.config import get_settings


def call_llm(prompt: str, temperature: float = 0.2) -> str:
    """Call the configured DashScope OpenAI-compatible model and return text.

    The demo tolerates missing credentials by raising a runtime error, so
    pipeline steps can decide whether to fall back to deterministic logic.
    """

    settings = get_settings()
    api_key = settings.dashscope_api_key or settings.openai_api_key
    model = settings.dashscope_model
    base_url = settings.dashscope_base_url
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一名严谨的专业买方投研分析师，只输出用户要求的结构化内容，不输出寒暄、解释或多余文本。"},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    except Exception as exc:  # pragma: no cover - external dependency
        raise RuntimeError("LLM request failed") from exc
