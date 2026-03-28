"""FastAPI application factory for the Tensory dashboard API.

Provides ``create_app()`` factory with lifespan management:
- Test mode: caller provides a TensoryService, no auto-close on shutdown.
- Production mode: creates Tensory from ``TENSORY_DB_PATH`` env var.

Key patterns:
- CORS middleware configured via ``CORS_ORIGINS`` env var
- All routers mounted under ``/api`` prefix
- Module-level ``app`` instance for ``uvicorn api.main:app``
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import get_service, set_service
from api.routers import claims, graph, stats
from tensory.service import TensoryService
from tensory.store import Tensory


def create_app(*, service: TensoryService | None = None) -> FastAPI:
    """Create a FastAPI application with optional pre-built service.

    Args:
        service: If provided, the app uses this service (test mode).
                 If None, creates a Tensory store from DB path on startup.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if service is not None:
            set_service(service)
            yield  # test mode — caller manages lifecycle
        else:
            db_path = os.getenv("TENSORY_DB_PATH", "data/tensory.db")
            store = await Tensory.create(db_path)
            set_service(TensoryService(store))
            yield
            svc = get_service()
            await svc.store.close()

    application = FastAPI(
        title="Tensory Dashboard API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    origins_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [o.strip() for o in origins_raw.split(",")]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    application.include_router(stats.router, prefix="/api")
    application.include_router(claims.router, prefix="/api")
    application.include_router(graph.router, prefix="/api")

    return application


app = create_app()
