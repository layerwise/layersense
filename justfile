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

docker-debug:
    # this overlays the debug configuration on top of the base configuration
    docker compose -f docker-compose.yml -f docker-compose.debug.yml up --build

docker-down:
    docker compose down

controller-dev:
    uv run --all-packages uvicorn layersense_controller.main:app --host 0.0.0.0 --port 8001

agent-dev:
    uv run --all-packages uvicorn layersense_agent.main:app --host 0.0.0.0 --port 8000


# -------------------------

# QA

# -------------------------

test_python:
    @echo "Python Tests"
    just test_python_unit

# run only Python unit tests
test_python_unit:
    @echo "Python Unit Tests"
    uv run --all-packages pytest -m unit

# run Python integration tests in replay mode off pre-recorded interactions
test_python_integration:
    @echo "Python Integration Tests (replay)"
    uv run --all-packages pytest -m integration --integration-mode=replay

# run Python integration tests in refresh mode against a live stack, refreshing the recorded interactions
test_python_integration_refresh:
    @echo "Python Integration Tests (refresh)"
    uv run --all-packages pytest -m integration --integration-mode=record

# run Python end-to-end tests that test a live stack
test_python_e2e:
    @echo "Python E2E Tests"
    uv run --all-packages pytest -m e2e

# Run all tests (Python + frontend)
test:
    just test_python_unit
    npm --prefix layersense_frontend test

smoke:
    uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke

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
    uv run --all-packages black .

verify_workspace:
    uv sync --all-packages && uv run --all-packages python -c "import layersense_controller; import layersense_agent; print('ok')"


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
