import importlib

from fastapi.testclient import TestClient


def test_app_health_endpoint_returns_ok() -> None:
    from layersense_controller.main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_app_lifespan_does_not_start_watcher(monkeypatch) -> None:
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
