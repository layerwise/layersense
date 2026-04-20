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
