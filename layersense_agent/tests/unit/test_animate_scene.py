import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.agents.agent import strip_code_fences
from layersense_agent.main import app
from layersense_agent.services.scene_normalizer import normalize_scene

pytestmark = [pytest.mark.unit, pytest.mark.ai]

FAKE_CODE = (
    "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
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


def assert_animation_created(response_json: dict[str, str]) -> Path:
    assert "conversation_id" in response_json
    assert "scene_path" in response_json
    scene_path = Path(response_json["scene_path"])
    assert scene_path.exists()
    assert "GeneratedScene" in scene_path.read_text()
    return scene_path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYERSENSE_SCENES_DIR", str(tmp_path))
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with patch(
            "layersense_agent.api.v1.endpoints.animate_scene.LAYERSENSE_SCENES_DIR", tmp_path
        ):
            with TestClient(app) as c:
                yield c, tmp_path, mock_runner


def test_create_animation_writes_file(client):
    """Write the generated Manim scene file for valid animation requests."""
    c, tmp_path, _ = client
    payload = {"prompt": "animate a circle", "scene": SCENE_PAYLOAD}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    assert_animation_created(response.json())


def test_create_animation_writes_file_from_scene_payload(client):
    """Append the normalized scene payload to the model prompt."""
    c, tmp_path, mock_runner = client
    payload = {"prompt": "animate a circle", "scene": SCENE_PAYLOAD}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    assert_animation_created(response.json())
    runner_prompt = mock_runner.run.await_args.args[1]
    prompt_prefix, serialized_scene = runner_prompt.split("\n", maxsplit=1)
    assert prompt_prefix == "animate a circle"
    assert json.loads(serialized_scene) == {
        **normalize_scene(SCENE_PAYLOAD).model_dump(),
        "appState": {},
    }


def test_create_animation_normalizes_scene_before_generation(client):
    """Normalize the scene before serializing it into the model prompt."""
    c, tmp_path, mock_runner = client
    payload = {"prompt": "animate a circle", "scene": SCENE_PAYLOAD}

    with patch(
        "layersense_agent.api.v1.endpoints.animate_scene.normalize_scene"
    ) as normalize_mock:
        normalize_mock.return_value.appState.viewBackgroundColor = None
        normalize_mock.return_value.model_dump_json.return_value = (
            '{"elements":[],"appState":{},"files":{}}'
        )

        response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    assert_animation_created(response.json())
    normalize_mock.assert_called_once_with(payload["scene"])
    normalize_mock.return_value.model_dump_json.assert_called_once_with(
        exclude={"appState": {"viewBackgroundColor"}}
    )
    runner_prompt = mock_runner.run.await_args.args[1]
    assert '{"elements":[],"appState":{},"files":{}}' in runner_prompt


def test_create_animation_excludes_bypassed_background_color_from_generation_prompt(client):
    """Exclude explicit render colors from the generated scene prompt payload."""
    c, _, mock_runner = client
    payload = {
        "prompt": "animate a circle",
        "scene": {
            **SCENE_PAYLOAD,
            "appState": {"viewBackgroundColor": "#334455"},
        },
    }

    response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    runner_prompt = mock_runner.run.await_args.args[1]
    _, serialized_scene = runner_prompt.split("\n", maxsplit=1)
    assert json.loads(serialized_scene) == {
        **normalize_scene(payload["scene"]).model_dump(),
        "appState": {},
    }


def test_create_animation_returns_render_options(client):
    """Return render options derived from the normalized Excalidraw scene."""
    c, _, _ = client
    payload = {
        "prompt": "animate a circle",
        "scene": {
            **SCENE_PAYLOAD,
            "appState": {"viewBackgroundColor": "#334455"},
        },
    }

    response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    assert response.json()["render_options"] == {"background_color": "#334455"}


def test_create_animation_rejects_effectively_empty_scene(client):
    """Reject scene payloads that normalize to no supported elements."""
    c, _, mock_runner = client
    payload = {
        "prompt": "animate a circle",
        "scene": {"elements": [], "appState": {}, "files": {}},
    }

    response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_strip_code_fences_removes_fences():
    """Strip fenced markdown wrappers from model output code."""
    wrapped = "```python\nfrom manim import *\n```"
    assert strip_code_fences(wrapped) == "from manim import *"


def test_strip_code_fences_passthrough():
    """Leave unfenced code output unchanged."""
    plain = "from manim import *"
    assert strip_code_fences(plain) == "from manim import *"
