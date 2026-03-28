"""Graph endpoints — entities, edges, subgraph, entity claims."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_service
from tensory.service import EdgeData, EntityNode, SubGraph, TensoryService

router = APIRouter(prefix="/graph", tags=["graph"])

ServiceDep = Annotated[TensoryService, Depends(get_service)]


@router.get("/entities", response_model=list[EntityNode])
async def get_entities(
    svc: ServiceDep,
    limit: int = Query(100, ge=1, le=1000),
    min_mentions: int = Query(1, ge=0),
) -> list[EntityNode]:
    """List graph entities ordered by mention count."""
    return await svc.get_graph_entities(limit=limit, min_mentions=min_mentions)


@router.get("/edges", response_model=list[EdgeData])
async def get_edges(
    svc: ServiceDep,
    entity: str | None = Query(None),
) -> list[EdgeData]:
    """List active graph edges, optionally filtered by entity."""
    return await svc.get_graph_edges(entity_filter=entity)


@router.get("/subgraph/{entity}", response_model=SubGraph)
async def get_subgraph(
    entity: str,
    svc: ServiceDep,
    depth: int = Query(2, ge=1, le=5),
) -> SubGraph:
    """Get a subgraph of nodes and edges reachable from an entity."""
    return await svc.get_entity_subgraph(entity, depth=depth)


@router.get("/entity/{name}/claims")
async def get_entity_claims(
    name: str,
    svc: ServiceDep,
) -> list[dict[str, Any]]:
    """Get all claims associated with a specific entity.

    Returns claims with embedding fields excluded.
    """
    claims = await svc.get_entity_claims(name)
    return [c.model_dump(exclude={"embedding"}) for c in claims]
