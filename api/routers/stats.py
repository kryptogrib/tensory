"""Stats endpoint — aggregated dashboard statistics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.dependencies import get_service
from tensory.service import DashboardStats, TensoryService

router = APIRouter(tags=["stats"])

ServiceDep = Annotated[TensoryService, Depends(get_service)]


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    svc: ServiceDep,
) -> DashboardStats:
    """Return aggregated dashboard statistics."""
    return await svc.get_stats()
