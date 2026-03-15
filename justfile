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

# Run all tests with coverage
test:
    uv run --all-packages pytest

# Run type checks
typecheck:
    uv run --all-packages mypy

# Lint & format with ruff + black
lint:
    uv run --all-packages ruff check
    uv run --all-packages black --check .

format:
    uv run --all-packages ruff check --fix

# Run all quality checks
check: lint typecheck test

# -------------------------

# Build & Release

# -------------------------

# Build wheel + sdist
build:
    uv build --all-packages

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
