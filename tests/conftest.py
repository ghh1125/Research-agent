from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> TestClient:
    """Create a test client for the FastAPI app."""

    return TestClient(create_app())
