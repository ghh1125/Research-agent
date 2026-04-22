from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router as research_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Create the FastAPI application."""

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Research Agent MVP that turns fuzzy research queries into structured judgments.",
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(research_router, prefix=settings.api_prefix)
    return app


app = create_app()
