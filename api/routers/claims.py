"""Claims and search endpoints — list, detail, hybrid search."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from tensory.service import ClaimDetail, PaginatedClaims, TensoryService

router = APIRouter(tags=["claims"])

ServiceDep = Annotated[TensoryService, Depends(get_service)]


@router.get("/claims", response_model=PaginatedClaims)
async def list_claims(
    svc: ServiceDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    type: str | None = Query(None),  # noqa: A002
    salience_min: float | None = Query(None),
    salience_max: float | None = Query(None),
    entity: str | None = Query(None),
    context_id: str | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
) -> PaginatedClaims:
    """List claims with pagination and optional filters."""
    return await svc.list_claims(
        offset=offset,
        limit=limit,
        type_filter=type,
        salience_min=salience_min,
        salience_max=salience_max,
        entity_filter=entity,
        context_id=context_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/claims/{claim_id}", response_model=ClaimDetail)
async def get_claim(
    claim_id: str,
    svc: ServiceDep,
) -> ClaimDetail:
    """Get full detail for a single claim."""
    try:
        return await svc.get_claim(claim_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/search")
async def search_claims(
    svc: ServiceDep,
    q: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    context_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Search claims via hybrid search (FTS + vector + graph).

    Returns search results with embedding fields excluded from claims.
    """
    results = await svc.search_claims(q, context_id=context_id, limit=limit)
    return [
        {
            "claim": r.claim.model_dump(exclude={"embedding"}),
            "score": r.score,
            "relevance": r.relevance,
            "method": r.method,
        }
        for r in results
    ]
