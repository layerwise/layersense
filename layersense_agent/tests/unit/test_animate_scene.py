import hashlib
import json
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
EXPECTED_CODE = FAKE_CODE.strip()
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
def client():
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with TestClient(app) as c:
            yield c, mock_runner


def test_create_animation_returns_source_and_hash(client) -> None:
    """Return generated source bytes instead of writing a scene file."""
    c, _ = client

    response = c.post("/api/v1/animation", json={"prompt": "animate", "scene": SCENE_PAYLOAD})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_code"] == EXPECTED_CODE
    assert payload["content_hash"] == hashlib.sha256(EXPECTED_CODE.encode()).hexdigest()
    assert "scene_path" not in payload


def test_create_animation_injects_background_color_into_source(client) -> None:
    """Preserve background color in the returned generated scene source."""
    c, _ = client

    response = c.post(
        "/api/v1/animation",
        json={
            "prompt": "animate",
            "scene": {**SCENE_PAYLOAD, "appState": {"viewBackgroundColor": "#334455"}},
        },
    )

    source_code = response.json()["source_code"]
    assert response.status_code == 200
    assert (
        source_code
        == 'from manim import config\nconfig.background_color = "#334455"\n\n' + FAKE_CODE
    )
    assert response.json()["content_hash"] == hashlib.sha256(source_code.encode()).hexdigest()


def test_create_animation_appends_normalized_scene_to_generation_prompt(client) -> None:
    """Append the normalized scene payload to the model prompt."""
    c, mock_runner = client

    response = c.post("/api/v1/animation", json={"prompt": "animate", "scene": SCENE_PAYLOAD})

    assert response.status_code == 200
    runner_prompt = mock_runner.run.await_args.args[1]
    prompt_prefix, serialized_scene = runner_prompt.split("\n", maxsplit=1)
    assert prompt_prefix == "animate"
    assert json.loads(serialized_scene) == normalize_scene(SCENE_PAYLOAD).model_dump()


def test_create_animation_rejects_effectively_empty_scene(client) -> None:
    """Reject scene payloads that normalize to no supported elements."""
    c, mock_runner = client

    response = c.post(
        "/api/v1/animation",
        json={"prompt": "animate", "scene": {"elements": [], "appState": {}, "files": {}}},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Scene must contain at least one supported element."}
    mock_runner.run.assert_not_awaited()


def test_strip_code_fences_removes_fences() -> None:
    """Strip fenced markdown wrappers from model output code."""
    assert strip_code_fences("```python\nfrom manim import *\n```") == "from manim import *"


def test_strip_code_fences_passthrough() -> None:
    """Leave unfenced code output unchanged."""
    assert strip_code_fences("from manim import *") == "from manim import *"
