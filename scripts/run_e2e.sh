#!/bin/sh

set -eu

if [ -z "${OPENAI_API_KEY:-}" ]; then
    printf '%s\n' "OPENAI_API_KEY must be set for just test-e2e" >&2
    exit 1
fi

if [ -z "${CODESTRAL_API_KEY:-}" ]; then
    printf '%s\n' "CODESTRAL_API_KEY must be set for just test-e2e" >&2
    exit 1
fi

workspace_root=${LAYERSENSE_E2E_WORKSPACE_ROOT:-/workspace}
project_name="layersense-e2e-$(date +%s)-$$"
compose_file="${workspace_root}/docker-compose.e2e.inner.yml"

cleanup() {
    docker compose -f "${compose_file}" -p "${project_name}" logs || true
    docker compose -f "${compose_file}" -p "${project_name}" down -v || true
}

trap cleanup EXIT

docker compose -f "${compose_file}" -p "${project_name}" up --build -d

wait_for_http() {
    url=$1
    name=$2
    attempts=${3:-60}
    i=0

    while [ "${i}" -lt "${attempts}" ]; do
        if curl --silent --show-error --fail "${url}" >/dev/null 2>&1; then
            return 0
        fi
        i=$((i + 1))
        sleep 2
    done

    printf '%s\n' "Timed out waiting for ${name} at ${url}" >&2
    docker compose -f "${compose_file}" -p "${project_name}" ps >&2 || true
    return 1
}

wait_for_http "http://host.docker.internal:3000/" "frontend root"
wait_for_http "http://host.docker.internal:8000/health" "agent health"
wait_for_http "http://host.docker.internal:8001/health" "controller health"

export LAYERSENSE_SMOKE_FRONTEND_BASE="http://host.docker.internal:3000"
export LAYERSENSE_SMOKE_AGENT_BASE="http://host.docker.internal:8000"
export LAYERSENSE_SMOKE_CONTROLLER_BASE="http://host.docker.internal:8001"
export LAYERSENSE_SMOKE_CONTROLLER_WS_URL="ws://host.docker.internal:8001/ws"
export LAYERSENSE_SMOKE_REPO_ROOT="${workspace_root}"

uv sync --all-packages
npm --prefix layersense_frontend install
uv run --all-packages pytest -m "not smoke"
npm --prefix layersense_frontend test
uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke
