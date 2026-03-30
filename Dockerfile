# ══════════════════════════════════════════════════════════════════════
# Tensory All-in-One: API + Dashboard UI + MCP
# Build: docker build -t tensory .
# Run:   docker run -p 8000:8000 -v tensory-data:/data tensory
# ══════════════════════════════════════════════════════════════════════

# ── Stage 1: Build Next.js dashboard to static HTML/CSS/JS ──────────
FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
# Empty string = same origin (API and UI served by same FastAPI)
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build
# Result: /ui/out/ — pure static files, no Node.js needed at runtime

# ── Stage 2: Python runtime ─────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

RUN pip install uv

# Install Python deps
COPY pyproject.toml uv.lock ./
RUN uv sync --extra all --no-dev

# Copy source
COPY tensory/ tensory/
COPY api/ api/
COPY tensory_mcp.py ./

# Copy pre-built UI static files into the package
COPY --from=ui-builder /ui/out/ tensory/_ui_static/

# Create data directory
RUN mkdir -p /data

ENV TENSORY_DB_PATH=/data/tensory.db
EXPOSE 8888

CMD ["uv", "run", "tensory-server", "--host", "0.0.0.0", "--port", "8888"]
