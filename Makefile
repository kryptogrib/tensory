.PHONY: dashboard api ui install test lint

# Launch everything with one command
dashboard:
	@echo "\033[0;33m[Tensory Dashboard]\033[0m Starting API + UI..."
	@trap 'kill 0' EXIT; \
	uv run uvicorn api.main:app --reload --port 8000 & \
	cd ui && npm run dev & \
	wait

# Launch API only
api:
	uv run uvicorn api.main:app --reload --port 8000

# Launch UI only (assumes API is running)
ui:
	cd ui && npm run dev

# Install all deps (Python + Node)
install:
	uv sync --all-extras
	cd ui && npm install

# Run all tests
test:
	uv run pytest tests/ --ignore=tests/test_locomo_score.py -v

# Lint + type check
lint:
	uv run pyright tensory/ api/
	uv run ruff check tensory/ api/ tests/

# Docker launch
docker:
	docker compose up --build
