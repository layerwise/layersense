from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]

ROOT = Path(__file__).resolve().parents[1]


def test_e2e_runner_script_uses_current_e2e_taxonomy() -> None:
    """Keep the runner aligned with the current e2e taxonomy and paths."""
    content = (ROOT / "scripts" / "run_e2e.sh").read_text()

    assert 'export LAYERSENSE_E2E_FRONTEND_BASE="http://frontend"' in content
    assert 'export LAYERSENSE_E2E_AGENT_BASE="http://agent:8000"' in content
    assert 'export LAYERSENSE_E2E_CONTROLLER_BASE="http://controller:8001"' in content
    assert 'export LAYERSENSE_E2E_CONTROLLER_WS_URL="ws://controller:8001/ws"' in content
    assert 'export LAYERSENSE_E2E_REPO_ROOT="${workspace_root}"' in content
    assert 'uv run --all-packages pytest -m "not e2e"' in content
    assert "uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e" in content
    assert "tests/smoke/test_dev_stack_smoke.py" not in content
    assert 'pytest -m "not smoke"' not in content


def test_justfile_exports_openai_key_from_keychain() -> None:
    content = (ROOT / "justfile").read_text()

    assert "[private]\n_export-secrets:" in content
    assert '#!/usr/bin/env bash' in content
    assert 'set -euo pipefail' in content
    assert 'security find-generic-password -a "$USER" -s "layersense-openai-api-key" -w 2>/dev/null' in content
    assert 'OPENAI_API_KEY not found in macOS Keychain service layersense-openai-api-key' in content
    assert "printf 'export OPENAI_API_KEY=%q\\n' \"$openai_api_key\"" in content


def test_test_e2e_recipe_loads_secrets_and_cleans_up() -> None:
    content = (ROOT / "justfile").read_text()

    expected_block = """test-e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-secrets)"
    trap 'docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v' EXIT
    docker compose -f docker-compose.yml -f docker-compose.e2e.yml up --build --abort-on-container-exit --exit-code-from e2e-runner
"""

    assert expected_block in content
    assert "smoker:" not in content


def test_readme_documents_keychain_backed_test_e2e_setup() -> None:
    content = (ROOT / "README.md").read_text()

    assert (
        "Store `OPENAI_API_KEY` in macOS Keychain under service `layersense-openai-api-key` before running it."
        in content
    )
    assert "`just test-e2e` loads the key automatically via `just _export-secrets`." in content
    assert (
        'security add-generic-password -U -a "$USER" -s "layersense-openai-api-key" -w "<your-openai-api-key>"'
        in content
    )
    assert "Export `OPENAI_API_KEY` in your shell before running it." not in content
