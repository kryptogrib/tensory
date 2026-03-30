"""FastAPI application factory for the Tensory dashboard API.

Provides ``create_app()`` factory with lifespan management:
- Test mode: caller provides a TensoryService, no auto-close on shutdown.
- Production mode: creates Tensory from ``TENSORY_DB_PATH`` env var.

Key patterns:
- CORS middleware configured via ``CORS_ORIGINS`` env var
- All routers mounted under ``/api`` prefix
- Static UI served from ``tensory/_ui_static/`` (Next.js export build)
- Module-level ``app`` instance for ``uvicorn api.main:app``
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import get_service, set_service
from api.routers import claims, graph, stats
from tensory.service import TensoryService
from tensory.store import Tensory

# UI static files location (built Next.js export)
_UI_STATIC_DIR = Path(__file__).resolve().parent.parent / "tensory" / "_ui_static"


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

    # API routers (MUST be before static files catch-all)
    application.include_router(stats.router, prefix="/api")
    application.include_router(claims.router, prefix="/api")
    application.include_router(graph.router, prefix="/api")

    # Serve UI static files if available (Next.js export build)
    ui_dir = Path(os.getenv("TENSORY_UI_DIR", str(_UI_STATIC_DIR)))
    if ui_dir.is_dir():
        # Next.js static assets (_next/*, icons, etc.)
        application.mount("/_next", StaticFiles(directory=ui_dir / "_next"), name="nextjs")

        # Catch-all: serve index.html for client-side routing
        @application.get("/{path:path}")
        async def serve_ui(path: str) -> FileResponse:
            """Serve Next.js static export — SPA catch-all."""
            file = ui_dir / path
            # Serve exact file if it exists (e.g., favicon.ico)
            if file.is_file():
                return FileResponse(file)
            # Try .html extension (Next.js exports /claims → claims.html)
            html_file = ui_dir / f"{path}.html"
            if html_file.is_file():
                return FileResponse(html_file)
            # Fallback to index.html (SPA client-side routing)
            return FileResponse(ui_dir / "index.html")

    return application


app = create_app()
