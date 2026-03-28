import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

FAKE_CODE = (
    "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
)
SCENE_PAYLOAD = {"elements": [], "appState": {}, "files": {}}


def assert_animation_created(response_json: dict[str, str]) -> Path:
    assert "conversation_id" in response_json
    assert "scene_path" in response_json
    scene_path = Path(response_json["scene_path"])
    assert scene_path.exists()
    assert "GeneratedScene" in scene_path.read_text()
    return scene_path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENES_DIR", str(tmp_path))
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with patch("layersense_agent.api.v1.endpoints.animate_scene.SCENES_DIR", tmp_path):
            with TestClient(app) as c:
                yield c, tmp_path, mock_runner


def test_create_animation_writes_file(client):
    c, tmp_path, _ = client
    payload = {"prompt": "animate a circle", "scene": SCENE_PAYLOAD}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    assert_animation_created(response.json())


def test_create_animation_writes_file_from_scene_payload(client):
    c, tmp_path, mock_runner = client
    payload = {"prompt": "animate a circle", "scene": SCENE_PAYLOAD}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    assert_animation_created(response.json())
    runner_prompt = mock_runner.run.await_args.args[1]
    prompt_prefix, serialized_scene = runner_prompt.split("\n", maxsplit=1)
    assert prompt_prefix == "animate a circle"
    assert json.loads(serialized_scene) == SCENE_PAYLOAD


def test_create_animation_preserves_unknown_top_level_scene_keys(client):
    c, tmp_path, mock_runner = client
    payload = {
        "prompt": "animate a circle",
        "scene": {
            **SCENE_PAYLOAD,
            "elements": [
                {
                    "id": "shape-1",
                    "type": "rectangle",
                    "customData": {"label": "keep me"},
                }
            ],
            "unexpected": "value",
        },
    }

    response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    assert_animation_created(response.json())
    runner_prompt = mock_runner.run.await_args.args[1]
    _, serialized_scene = runner_prompt.split("\n", maxsplit=1)
    assert json.loads(serialized_scene) == payload["scene"]


def test_strip_code_fences_removes_fences():
    from layersense_agent.agents.agent import strip_code_fences

    wrapped = "```python\nfrom manim import *\n```"
    assert strip_code_fences(wrapped) == "from manim import *"


def test_strip_code_fences_passthrough():
    from layersense_agent.agents.agent import strip_code_fences

    plain = "from manim import *"
    assert strip_code_fences(plain) == "from manim import *"
