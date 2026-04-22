from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import ResearchRequest, ResearchResponse
from app.dependencies import get_agent
from app.agent.orchestrator import ResearchAgent

router = APIRouter(tags=["research"])


@router.post("/research", response_model=ResearchResponse)
def run_research(
    request: ResearchRequest,
    agent: ResearchAgent = Depends(get_agent),
) -> ResearchResponse:
    """Run the research pipeline and return structured artifacts plus final report."""

    try:
        result = agent.run(request.query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - safety net for demo API
        raise HTTPException(status_code=500, detail="Research pipeline failed") from exc

    return ResearchResponse(**result)
