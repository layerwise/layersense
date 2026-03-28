# Justfile for my_project

# Run recipes with `just <recipe>`

# Default recipe: show available commands

default:
    @just --list

# -------------------------

# Dev Workflow

# -------------------------

# Sync dependencies across all packages
setup:
    uv sync --all-packages

# Start frontend dev server
frontend-dev:
    npm --prefix layersense_frontend install
    npm --prefix layersense_frontend run dev -- --host 0.0.0.0 --port 3000

docker:
    docker compose up --build

docker-down:
    docker compose down

controller-dev:
    uv run --all-packages uvicorn layersense_controller.main:app --host 0.0.0.0 --port 8001

agent-dev:
    uv run --all-packages uvicorn layersense_agent.main:app --host 0.0.0.0 --port 8000


# -------------------------

# QA

# -------------------------

# Run all tests with coverage
test:
    uv run --all-packages pytest
    cd layersense_frontend && npm test

# Run type checks
typecheck:
    uv run --all-packages mypy

# Lint & format with ruff + black
lint:
    uv run --all-packages ruff check
    uv run --all-packages black --check .
    docker compose config

format:
    uv run --all-packages ruff check --fix

verify_workspace:
    uv sync --all-packages && uv run --all-packages python -c "import layersense_controller; import layersense_agent; import layersense_renderer; print('ok')"


# Run all quality checks
check: lint typecheck test verify_workspace

# -------------------------

# Build & Release

# -------------------------

# Build wheel + sdist
build:
    uv build --all-packages


# Build frontend production bundle
frontend-build:
    npm --prefix layersense_frontend install
    npm --prefix layersense_frontend run build

# Install locally (editable)

install:
    uv pip install -e .

# -------------------------

# Docs

# -------------------------

# Serve MkDocs site locally

docs:
    uv run mkdocs serve

# Build docs

docs-build:
    uv run mkdocs build --clean

# -------------------------

# Utilities

# -------------------------

# Clean build/test artifacts

clean:
    rm -rf build/ dist/ \*.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov

# Regenerate lockfile

lock:
    uv lock --upgrade
