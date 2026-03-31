"""Timeline API endpoints for temporal knowledge visualization."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from tensory.service import TensoryService

router = APIRouter(prefix="/timeline", tags=["timeline"])
ServiceDep = Annotated[TensoryService, Depends(get_service)]


@router.get("/snapshot/at")
async def get_graph_snapshot(
    service: ServiceDep,
    at: str = Query(..., description="ISO datetime for snapshot"),
) -> dict[str, Any]:
    """Get knowledge graph state at a point in time."""
    from datetime import UTC, datetime

    try:
        dt = datetime.fromisoformat(at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {at}") from exc

    snapshot = await service.get_graph_snapshot(dt)
    return snapshot.model_dump()


@router.get("/range/bounds")
async def get_timeline_range(service: ServiceDep) -> dict[str, Any]:
    """Get date range and event histogram for timeline slider."""
    result = await service.get_timeline_range()
    return result.model_dump()


@router.get("/{entity_name}")
async def get_entity_timeline(
    entity_name: str,
    service: ServiceDep,
    include_superseded: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Get chronological timeline of claims for an entity."""
    entries = await service.get_entity_timeline(
        entity_name, include_superseded=include_superseded, limit=limit
    )
    return [
        {
            "claim": e.claim.model_dump(exclude={"embedding"}),
            "supersedes": e.supersedes,
        }
        for e in entries
    ]
