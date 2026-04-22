from __future__ import annotations

from app.config import Settings


def test_default_research_retrieval_limits_are_not_demo_sized() -> None:
    settings = Settings(_env_file=None)

    assert settings.tavily_max_results == 8
    assert settings.retrieve_max_sources == 15
    assert settings.retrieve_per_question_limit == 4
