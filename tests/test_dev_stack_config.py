from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
