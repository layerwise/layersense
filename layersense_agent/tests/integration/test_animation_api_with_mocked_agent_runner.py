from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

pytestmark = [pytest.mark.integration, pytest.mark.ai]

FAKE_CODE = (
    "```python\n"
    "from manim import Scene\n\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        pass\n"
    "```"
)

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
def mock_client(tmp_path: Path):
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with patch(
            "layersense_agent.api.v1.endpoints.animate_scene.LAYERSENSE_SCENES_DIR", tmp_path
        ):
            with TestClient(app) as client:
                yield client, mock_runner, tmp_path


@pytest.fixture()
def non_raising_client(tmp_path: Path):
    with patch("layersense_agent.api.v1.endpoints.animate_scene.LAYERSENSE_SCENES_DIR", tmp_path):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


def test_create_animation_writes_generated_scene_file(mock_client) -> None:
    """Write generated scene code through the API boundary for valid requests."""
    test_client, _runner, scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={"prompt": "Animate a square.", "scene": SCENE_PAYLOAD},
    )

    assert response.status_code == 200
    payload = response.json()
    scene_path = Path(payload["scene_path"])
    assert scene_path.parent == scenes_dir
    assert scene_path.exists()
    assert scene_path.read_text() == (
        "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass"
    )


def test_create_animation_rejects_effectively_empty_scene(mock_client) -> None:
    """Reject scene payloads that normalize to no supported elements."""
    test_client, mock_runner, _scenes_dir = mock_client

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


def test_create_animation_rejects_malformed_scene(mock_client) -> None:
    """Reject scene payloads that have malformed elements."""
    test_client, mock_runner, _scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate nothing.",
            "scene": {
                "elements": ["elements should be dict, this is not"],
                "appState": {},
                "files": {},
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_create_animation_rejects_scenes_with_only_deleted_elements(mock_client) -> None:
    """Reject scene payloads that have only deleted elements."""
    test_client, mock_runner, _scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate nothing.",
            "scene": {
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
                        "isDeleted": True,
                    }
                ],
                "appState": {},
                "files": {},
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_create_animation_persists_background_color_in_generated_scene_file(mock_client) -> None:
    """Persist explicit background color in the generated scene source."""
    test_client, _runner, _scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate a square.",
            "scene": {**SCENE_PAYLOAD, "appState": {"viewBackgroundColor": "#334455"}},
        },
    )

    assert response.status_code == 200
    assert 'config.background_color = "#334455"' in Path(response.json()["scene_path"]).read_text()


def test_create_animation_rejects_unsupported_scene_elements(mock_client) -> None:
    """Reject scenes whose elements all normalize away at the API boundary."""
    test_client, mock_runner, _scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={
            "prompt": "Animate a line.",
            "scene": {
                "elements": [
                    {
                        **SCENE_PAYLOAD["elements"][0],
                        "type": "line",
                    }
                ],
                "appState": {},
                "files": {},
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_create_animation_requires_prompt_field(mock_client) -> None:
    """Return request validation errors when the prompt field is missing."""
    test_client, _runner, _scenes_dir = mock_client

    response = test_client.post(
        "/api/v1/animation",
        json={"scene": SCENE_PAYLOAD},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "prompt"]


def test_create_animation_returns_internal_error_when_runner_fails(non_raising_client) -> None:
    """Surface upstream runner failures as internal server errors at the API boundary."""
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(side_effect=RuntimeError("model request failed"))

        response = non_raising_client.post(
            "/api/v1/animation",
            json={"prompt": "Animate a square.", "scene": SCENE_PAYLOAD},
        )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
