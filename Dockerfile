# ══════════════════════════════════════════════════════════════════════
# Tensory Dashboard: API + UI in one container
#
# Build:  docker build -t tensory .
# Run:    docker run -d -p 7770:7770 -v tensory-data:/data tensory
# Open:   http://localhost:7770
# ══════════════════════════════════════════════════════════════════════

# ── Stage 1: Build Next.js dashboard to static HTML/CSS/JS ──────────
FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# ── Stage 2: Python runtime ─────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install only the runtime deps (no build system needed)
RUN pip install --no-cache-dir \
    aiosqlite \
    sqlite-vec \
    pydantic \
    fastapi \
    "uvicorn[standard]" \
    httpx

# Copy source directly (no package install, no hatch-vcs)
COPY tensory/ tensory/
COPY api/ api/
COPY tensory_mcp.py ./

# Copy pre-built UI static files
COPY --from=ui-builder /ui/out/ tensory/_ui_static/

RUN mkdir -p /data

ENV TENSORY_DB_PATH=/data/tensory.db
ENV PYTHONPATH=/app
EXPOSE 7770

CMD ["python", "-m", "tensory.dashboard", "--host", "0.0.0.0", "--port", "7770", "--no-open"]
