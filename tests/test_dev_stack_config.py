import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]

ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST_PATH = ROOT / "tests" / "smoke" / "test_dev_stack_smoke.py"

_smoke_spec = importlib.util.spec_from_file_location(
    "test_dev_stack_smoke_module", SMOKE_TEST_PATH
)
assert _smoke_spec is not None
assert _smoke_spec.loader is not None
smoke = importlib.util.module_from_spec(_smoke_spec)
_smoke_spec.loader.exec_module(smoke)


def test_docker_compose_defines_full_dev_stack() -> None:
    content = (ROOT / "docker-compose.yml").read_text()

    assert "frontend:" in content
    assert "agent:" in content
    assert "controller:" in content
    assert "3000:3000" in content
    assert "8000:8000" in content
    assert "8001:8001" in content


def test_debug_compose_and_vscode_debug_configs_exist() -> None:
    assert (ROOT / "docker-compose.debug.yml").exists()
    assert (ROOT / ".vscode" / "launch.json").exists()


def test_debug_compose_exposes_debug_ports_and_source_mounts() -> None:
    content = (ROOT / "docker-compose.debug.yml").read_text()

    assert "5678:5678" in content
    assert "5679:5679" in content
    assert "./layersense_agent/src:/app/src" in content
    assert "./layersense_controller/src:/app/src" in content
    assert "PYTHONPATH: /app/src" in content


def test_vscode_launch_config_targets_python_services() -> None:
    content = (ROOT / ".vscode" / "launch.json").read_text()

    assert '"Attach: Agent"' in content
    assert '"Attach: Controller"' in content
    assert '"Attach: Full dev stack"' in content
    assert '"port": 5678' in content
    assert '"port": 5679' in content
    assert '"localRoot": "${workspaceFolder}/layersense_agent/src"' in content
    assert '"localRoot": "${workspaceFolder}/layersense_controller/src"' in content


def test_debug_dockerfiles_extend_named_base_stages() -> None:
    agent_dockerfile = (ROOT / "layersense_agent" / "Dockerfile").read_text()
    controller_dockerfile = (ROOT / "layersense_controller" / "Dockerfile").read_text()

    assert "FROM python:3.14-slim AS base" in agent_dockerfile
    assert "FROM base AS final" in agent_dockerfile
    assert "FROM base AS debug" in agent_dockerfile
    assert "RUN uv pip install --system --no-cache debugpy" in agent_dockerfile

    assert "FROM manimcommunity/manim:v0.20.1 AS base" in controller_dockerfile
    assert "FROM base AS final" in controller_dockerfile
    assert "FROM base AS debug" in controller_dockerfile
    assert (
        "RUN uv pip install --python /opt/venv/bin/python --no-cache debugpy"
        in controller_dockerfile
    )


def test_smoke_repo_root_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LAYERSENSE_SMOKE_REPO_ROOT", "/tmp/worktree")

    assert smoke._repo_root() == Path("/tmp/worktree")


def test_smoke_repo_root_prefers_git_show_toplevel(monkeypatch) -> None:
    monkeypatch.delenv("LAYERSENSE_SMOKE_REPO_ROOT", raising=False)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="/tmp/git-worktree\n",
        )

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke._repo_root() == Path("/tmp/git-worktree")


def test_smoke_repo_root_falls_back_to_test_file_parent(monkeypatch) -> None:
    monkeypatch.delenv("LAYERSENSE_SMOKE_REPO_ROOT", raising=False)

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=args[0])

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke._repo_root() == Path(smoke.__file__).resolve().parents[2]


def test_e2e_runner_files_exist() -> None:
    assert (ROOT / "docker-compose.e2e.yml").exists()
    assert (ROOT / "Dockerfile.e2e").exists()


def test_e2e_runner_compose_mounts_socket_workspace_and_env() -> None:
    content = (ROOT / "docker-compose.e2e.yml").read_text()

    assert "e2e-runner:" in content
    assert "/var/run/docker.sock:/var/run/docker.sock" in content
    assert ".:/workspace" in content
    assert "working_dir: /workspace" in content
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY}" in content
    assert "CODESTRAL_API_KEY: ${CODESTRAL_API_KEY}" in content


def test_e2e_inner_compose_defines_app_stack() -> None:
    content = (ROOT / "docker-compose.e2e.inner.yml").read_text()

    assert "frontend:" in content
    assert "agent:" in content
    assert "controller:" in content
    assert "context: ./layersense_frontend" in content
    assert "context: ./layersense_agent" in content
    assert "context: ./layersense_controller" in content
    assert "layersense_artifacts:" in content
    assert "layersense_code:" in content


def test_e2e_runner_script_exists_and_orchestrates_stack() -> None:
    content = (ROOT / "scripts" / "run_e2e.sh").read_text()

    assert "OPENAI_API_KEY" in content
    assert "CODESTRAL_API_KEY" in content
    assert "docker-compose.e2e.inner.yml" in content
    assert "up --build -d" in content
    assert "down -v" in content
    assert 'pytest -m "not smoke"' in content
    assert "npm --prefix layersense_frontend test" in content
    assert "pytest tests/smoke/test_dev_stack_smoke.py -m smoke" in content
    assert "LAYERSENSE_SMOKE_REPO_ROOT" in content
    assert "LAYERSENSE_SMOKE_FRONTEND_BASE" in content
    assert "LAYERSENSE_SMOKE_AGENT_BASE" in content
    assert "LAYERSENSE_SMOKE_CONTROLLER_BASE" in content
    assert "LAYERSENSE_SMOKE_CONTROLLER_WS_URL" in content


def test_justfile_exposes_test_e2e_recipe() -> None:
    content = (ROOT / "justfile").read_text()

    assert "test-e2e:" in content
    assert "docker compose -f docker-compose.e2e.yml run --rm e2e-runner" in content


def test_readme_documents_test_e2e_workflow() -> None:
    content = (ROOT / "README.md").read_text()

    assert "just smoke" in content
    assert "just test-e2e" in content
    assert "OPENAI_API_KEY" in content
    assert "CODESTRAL_API_KEY" in content
    assert "host Docker socket" in content
    assert "assistant-friendly" in content
