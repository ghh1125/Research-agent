from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "Research Agent MVP"
    api_prefix: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-plus"
    openai_api_key: str = ""
    openai_model: str = "gpt-5"
    search_provider: str = "auto"
    search_timeout_seconds: float = 20.0
    pdf_download_timeout_seconds: float = 30.0
    pdf_cache_dir: str = ".cache/pdf"
    pdf_max_pages: int = 12
    retrieve_max_sources: int = 15
    retrieve_per_question_limit: int = 4
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com/search"
    tavily_max_results: int = 8
    tavily_days: int = 180
    finnhub_api_key: str = ""
    finnhub_base_url: str = "https://finnhub.io/api/v1"
    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    sec_user_agent_email: str = "research-agent@example.com"
    supplemental_search_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
