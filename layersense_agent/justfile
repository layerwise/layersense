# Justfile for my_project

# Run recipes with `just <recipe>`

# Default recipe: show available commands

default:
    @just --list

# -------------------------

# Dev Workflow

# -------------------------

# Start FastAPI app in dev mode (hot reload)
dev:
    uv run uvicorn my_project.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests with coverage
test:
    uv run pytest --cov=my_project --cov-report=term-missing

# Run type checks
typecheck:
    uv run mypy src/ tests/

# Lint & format with ruff + black
lint:
    uv run ruff check src tests
    uv run black --check src tests

format:
    uv run ruff check --fix src tests
    uv run black src tests

# Run all quality checks
check: lint typecheck test

# -------------------------

# Build & Release

# -------------------------

# Build wheel + sdist

build:
    uv build

# Install locally (editable)

install:
    uv pip install -e .

# Publish to PyPI (needs API token in env)
# publish: build
#    uv publish

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
