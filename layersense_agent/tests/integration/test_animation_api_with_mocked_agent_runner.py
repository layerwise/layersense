import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

pytestmark = [pytest.mark.integration, pytest.mark.ai]

FAKE_CODE = "```python\nfrom manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n```"
EXPECTED_CODE = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass"
SCENE_PAYLOAD = {
    "elements": [
        {
            "id": "shape-1",
            "type": "rectangle",
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "angle": 0,
            "strokeColor": "#000000",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "opacity": 100,
        }
    ],
    "appState": {},
    "files": {},
}


@pytest.fixture()
def mock_client():
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with TestClient(app) as client:
            yield client, mock_runner


def test_create_animation_returns_source_and_hash(mock_client) -> None:
    """Return generated source and source hash through the API boundary."""
    test_client, _runner = mock_client

    response = test_client.post(
        "/api/v1/animation", json={"prompt": "Animate a square.", "scene": SCENE_PAYLOAD}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_code"] == EXPECTED_CODE
    assert payload["content_hash"] == hashlib.sha256(EXPECTED_CODE.encode()).hexdigest()
    assert "scene_path" not in payload


def test_create_animation_rejects_effectively_empty_scene(mock_client) -> None:
    """Reject scene payloads that normalize to no supported elements."""
    test_client, mock_runner = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate nothing.",
            "scene": {"elements": [], "appState": {}, "files": {}},
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_create_animation_persists_background_color_in_source(mock_client) -> None:
    """Persist explicit background color in the returned generated scene source."""
    test_client, _runner = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate a square.",
            "scene": {**SCENE_PAYLOAD, "appState": {"viewBackgroundColor": "#334455"}},
        },
    )

    assert response.status_code == 200
    assert 'config.background_color = "#334455"' in response.json()["source_code"]


def test_create_animation_returns_internal_error_when_runner_fails() -> None:
    """Surface upstream runner failures as internal server errors at the API boundary."""
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(side_effect=RuntimeError("model request failed"))
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/animation",
                json={"prompt": "Animate a square.", "scene": SCENE_PAYLOAD},
            )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
