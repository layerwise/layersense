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


def test_frontend_dockerfile_describes_multi_stage_dev_and_prod_contract() -> None:
    content = (ROOT / "layersense_frontend" / "Dockerfile").read_text()

    assert content.count("FROM ") >= 3
    assert "npm ci" in content
    assert " AS dev" in content
    assert " AS build" in content
    assert "FROM nginx:alpine AS prod" in content


def test_frontend_dockerfile_has_no_runtime_npm_install() -> None:
    content = (ROOT / "layersense_frontend" / "Dockerfile").read_text()

    assert 'CMD ["sh", "-c", "npm install' not in content
    assert "npm install &&" not in content


def test_frontend_compose_builds_dev_target() -> None:
    content = (ROOT / "docker-compose.yml").read_text()

    assert "frontend:" in content
    assert "target: dev" in content


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
    assert not (ROOT / "docker-compose.e2e.inner.yml").exists()


def test_e2e_overlay_compose_adds_runner_and_port_remaps() -> None:
    content = (ROOT / "docker-compose.e2e.yml").read_text()

    assert "e2e-runner:" in content
    assert "frontend:" in content
    assert "agent:" in content
    assert "controller:" in content
    assert ".:/workspace" in content
    assert "working_dir: /workspace" in content
    assert "OPENAI_API_KEY: ${OPENAI_API_KEY}" in content
    assert "CODESTRAL_API_KEY: ${CODESTRAL_API_KEY}" in content
    assert '"3901:80"' in content
    assert '"8900:8000"' in content
    assert '"8901:8001"' in content
    assert "container_name: layersense_frontend_e2e" in content
    assert "container_name: layersense_agent_e2e" in content
    assert "container_name: layersense_controller_e2e" in content
    assert "/var/run/docker.sock:/var/run/docker.sock" not in content


def test_e2e_inner_compose_defines_app_stack() -> None:
    content = (ROOT / "docker-compose.e2e.yml").read_text()

    assert "frontend:" in content
    assert "agent:" in content
    assert "controller:" in content
    assert "target: prod" in content
    assert '"3901:80"' in content
    assert '"8900:8000"' in content
    assert '"8901:8001"' in content
    assert (
        'command: ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]'
        not in content
    )
    assert "!reset" in content
    assert "- ./layersense_frontend:/app" not in content
    assert "- frontend_node_modules:/app/node_modules" not in content


def test_e2e_runner_script_exists_and_orchestrates_stack() -> None:
    content = (ROOT / "scripts" / "run_e2e.sh").read_text()

    assert "OPENAI_API_KEY" in content
    assert "CODESTRAL_API_KEY" in content
    assert "docker compose" not in content
    assert 'pytest -m "not smoke"' in content
    assert "npm --prefix layersense_frontend test" in content
    assert "pytest tests/smoke/test_dev_stack_smoke.py -m smoke" in content
    assert "LAYERSENSE_SMOKE_REPO_ROOT" in content
    assert "LAYERSENSE_SMOKE_FRONTEND_BASE" in content
    assert "LAYERSENSE_SMOKE_AGENT_BASE" in content
    assert "LAYERSENSE_SMOKE_CONTROLLER_BASE" in content
    assert "LAYERSENSE_SMOKE_CONTROLLER_WS_URL" in content
    assert "http://frontend/" in content
    assert "http://agent:8000/health" in content
    assert "http://controller:8001/health" in content
    assert "ws://controller:8001/ws" in content
    assert "attempts=${3:-120}" in content


def test_e2e_dockerfile_installs_manimpango_build_deps() -> None:
    content = (ROOT / "Dockerfile.e2e").read_text()

    assert "pkg-config" in content
    assert "libpango1.0-dev" in content


def test_e2e_dockerfile_reuses_frontend_node_runtime() -> None:
    content = (ROOT / "Dockerfile.e2e").read_text()

    assert "FROM node:25-bookworm-slim AS node" in content
    assert "COPY --from=node /usr/local/bin/node /usr/local/bin/node" in content
    assert "COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules" in content
    assert "ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm" in content
    assert "ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx" in content
    assert "nodejs" not in content


def test_justfile_exposes_test_e2e_recipe() -> None:
    content = (ROOT / "justfile").read_text()

    assert "test-e2e:" in content
    assert (
        "docker compose -f docker-compose.yml -f docker-compose.e2e.yml up --build --abort-on-container-exit --exit-code-from e2e-runner"
        in content
    )
    assert "docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v" in content


def test_readme_documents_test_e2e_workflow() -> None:
    content = (ROOT / "README.md").read_text()

    assert "just smoke" in content
    assert "just test-e2e" in content
    assert "OPENAI_API_KEY" in content
    assert "CODESTRAL_API_KEY" in content
    assert "ephemeral compose project" in content
    assert "e2e-runner" in content
    assert "shared compose network" in content
    assert "3901" in content
    assert "assistant-friendly" in content


def test_frontend_dockerignore_excludes_local_build_artifacts() -> None:
    content = (ROOT / "layersense_frontend" / ".dockerignore").read_text()

    assert "node_modules" in content
    assert "dist" in content
    assert ".vite" in content


def test_readme_documents_frontend_dependency_refresh_after_lockfile_changes() -> None:
    content = (ROOT / "README.md").read_text()

    assert "package-lock.json" in content
    assert "docker compose down -v" in content
    assert "frontend_node_modules" in content
