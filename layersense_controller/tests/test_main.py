from fastapi.testclient import TestClient
from layersense_controller.main import app


def test_app_health_endpoint_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_starts_and_stops_watcher(monkeypatch) -> None:
    events: list[str] = []

    class FakeObserver:
        def stop(self) -> None:
            events.append("stop")

        def join(self) -> None:
            events.append("join")

    def fake_start_watcher() -> FakeObserver:
        events.append("start")
        return FakeObserver()

    monkeypatch.setattr("layersense_controller.main.start_watcher", fake_start_watcher)

    with TestClient(app):
        assert events == ["start"]

    assert events == ["start", "stop", "join"]
