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
# Empty string = same origin (API and UI served by same FastAPI)
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build
# Result: /ui/out/ — pure static files, no Node.js needed at runtime

# ── Stage 2: Python runtime ─────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

RUN pip install uv

# Install Python deps
# SETUPTOOLS_SCM_PRETEND_VERSION tells hatch-vcs the version
# (no .git in Docker context)
ARG SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}
COPY pyproject.toml uv.lock ./
RUN uv sync --extra ui --no-dev

# Copy source
COPY tensory/ tensory/
COPY api/ api/
COPY tensory_mcp.py ./

# Copy pre-built UI static files into the package
COPY --from=ui-builder /ui/out/ tensory/_ui_static/

# Create data directory
RUN mkdir -p /data

ENV TENSORY_DB_PATH=/data/tensory.db
EXPOSE 7770

CMD ["uv", "run", "tensory-dashboard", "--host", "0.0.0.0", "--port", "7770", "--no-open"]
