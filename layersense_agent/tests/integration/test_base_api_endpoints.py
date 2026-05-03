import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

pytestmark = [pytest.mark.integration]


def test_health_returns_ok() -> None:
    """Return a plain-text OK health response from the app boundary."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.text == "OK"


def test_info_returns_app_name() -> None:
    """Return application info from the app boundary."""
    with TestClient(app) as client:
        response = client.get("/info")

    assert response.status_code == 200
    assert response.json() == {"app_name": "Layersense: an AI-powered manim backend."}
