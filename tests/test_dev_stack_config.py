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
