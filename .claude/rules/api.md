---
description: FastAPI backend conventions for Tensory Dashboard
globs: "api/**/*.py"
---

- Python 3.11+, pyright strict mode, type annotations on ALL functions
- Every module MUST have a module-level docstring
- FastAPI routers in `api/routers/`, one file per resource (stats, claims, graph)
- Dependency injection via `Depends(get_service)` — use `Annotated[TensoryService, Depends(get_service)]`
- Response models from `tensory/service.py` — do NOT define duplicate models in api/
- CORS origins: `CORS_ORIGINS` env var, default `http://localhost:3000`
- DB path: checks `TENSORY_DB_PATH` → `TENSORY_DB` → default `data/tensory.db`. Always expanduser()
- MVP is read-only: only GET endpoints, no POST/PUT/DELETE
- Test with httpx `ASGITransport` + `AsyncClient`, pass `service` to `create_app(service=svc)` for test isolation
- Lifespan: skip `close()` in test mode (caller manages lifecycle)
