#!/bin/sh

set -eu

if [ -z "${OPENAI_API_KEY:-}" ]; then
    printf '%s\n' "OPENAI_API_KEY must be set for just test-e2e" >&2
    exit 1
fi

workspace_root=${LAYERSENSE_E2E_WORKSPACE_ROOT:-/workspace}

log_pwd() {
    label=$1
    printf '%s: %s\n' "${label}" "$(pwd)"
}

wait_for_http() {
    url=$1
    name=$2
    attempts=${3:-120}
    i=0

    while [ "${i}" -lt "${attempts}" ]; do
        if curl --silent --show-error --fail "${url}" >/dev/null 2>&1; then
            return 0
        fi
        i=$((i + 1))
        sleep 2
    done

    printf '%s\n' "Timed out waiting for ${name} at ${url}" >&2
    return 1
}

wait_for_http "http://frontend/" "frontend root"
wait_for_http "http://agent:8000/health" "agent health"
wait_for_http "http://controller:8001/health" "controller health"

export LAYERSENSE_E2E_FRONTEND_BASE="http://frontend"
export LAYERSENSE_E2E_AGENT_BASE="http://agent:8000"
export LAYERSENSE_E2E_CONTROLLER_BASE="http://controller:8001"
export LAYERSENSE_E2E_REPO_ROOT="${workspace_root}"

log_pwd "before uv sync"
uv sync --all-packages
log_pwd "after uv sync"
bun install --cwd layersense_frontend --frozen-lockfile
log_pwd "after bun install"
uv run --all-packages pytest -m "not e2e"
log_pwd "after python tests"
bun run --cwd layersense_frontend test
log_pwd "after frontend tests"
uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e
log_pwd "after http e2e"
uv run --all-packages pytest tests/e2e/test_browser_flow_e2e.py -m e2e
log_pwd "after browser e2e"
