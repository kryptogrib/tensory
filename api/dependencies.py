"""FastAPI dependency injection for TensoryService."""

from __future__ import annotations

from tensory.service import TensoryService

_service: TensoryService | None = None


def set_service(svc: TensoryService) -> None:
    """Set the global TensoryService instance."""
    global _service  # noqa: PLW0603
    _service = svc


def get_service() -> TensoryService:
    """Return the global TensoryService, raising if not initialized."""
    if _service is None:
        msg = "TensoryService not initialized"
        raise RuntimeError(msg)
    return _service
