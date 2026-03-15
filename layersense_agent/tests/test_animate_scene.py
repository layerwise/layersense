import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

FAKE_CODE = (
    "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENES_DIR", str(tmp_path))
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with patch("layersense_agent.api.v1.endpoints.animate_scene.SCENES_DIR", tmp_path):
            with TestClient(app) as c:
                yield c, tmp_path


def test_create_animation_writes_file(client):
    c, tmp_path = client
    payload = {"prompt": "animate a circle", "json_data": "{}"}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "conversation_id" in body
    assert "scene_path" in body
    scene_path = Path(body["scene_path"])
    assert scene_path.exists()
    assert "GeneratedScene" in scene_path.read_text()


def test_strip_code_fences_removes_fences():
    from layersense_agent.agents.agent import strip_code_fences

    wrapped = "```python\nfrom manim import *\n```"
    assert strip_code_fences(wrapped) == "from manim import *"


def test_strip_code_fences_passthrough():
    from layersense_agent.agents.agent import strip_code_fences

    plain = "from manim import *"
    assert strip_code_fences(plain) == "from manim import *"
