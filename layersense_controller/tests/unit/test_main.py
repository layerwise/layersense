import importlib

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_app_health_endpoint_returns_ok() -> None:
    """Expose a healthy controller status response."""
    from layersense_controller.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_app_lifespan_does_not_start_watcher(monkeypatch) -> None:
    """Keep the default FastAPI lifespan from starting the watcher."""
    events: list[str] = []

    class FakeObserver:
        def stop(self) -> None:
            events.append("stop")

        def join(self) -> None:
            events.append("join")

    def fake_start_watcher() -> FakeObserver:
        events.append("start")
        return FakeObserver()

    monkeypatch.setattr("layersense_controller.watcher.start_watcher", fake_start_watcher)

    import layersense_controller.main as main_module

    main_module = importlib.reload(main_module)

    with TestClient(main_module.app):
        assert events == []

    assert events == []


def test_settings_expose_redis_and_long_poll_fields(monkeypatch) -> None:
    """Parse Redis and long-poll settings from environment variables."""
    monkeypatch.setenv("LAYERSENSE_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_TTL_SECONDS", "7200")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_WAIT_SECONDS", "20")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_MAX_WAIT_SECONDS", "30")

    from layersense_controller.config import Settings

    parsed = Settings()

    assert str(parsed.redis_url) == "redis://redis:6379/0"
    assert parsed.render_job_ttl_seconds == 7200
    assert parsed.render_job_wait_seconds == 20
    assert parsed.render_job_max_wait_seconds == 30
