from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from layersense_agent.main import app

pytestmark = [pytest.mark.integration, pytest.mark.ai, pytest.mark.vcr]


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


def test_create_animation_returns_background_color_render_options(tmp_path: Path) -> None:
    """Return explicit render options derived from the scene app state."""
    with patch("layersense_agent.api.v1.endpoints.animate_scene.LAYERSENSE_SCENES_DIR", tmp_path):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/animation",
                json={
                    "prompt": "Animate a square.",
                    "scene": {**SCENE_PAYLOAD, "appState": {"viewBackgroundColor": "#334455"}},
                },
            )

    assert response.status_code == 200
    assert response.json()["render_options"] == {"background_color": "#334455"}


def test_create_animation_records_live_model_response(tmp_path: Path) -> None:
    """Record and replay the live model interaction through the API boundary."""
    with patch("layersense_agent.api.v1.endpoints.animate_scene.LAYERSENSE_SCENES_DIR", tmp_path):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/animation",
                json={
                    "prompt": "Animate a simple square appearing on screen.",
                    "scene": SCENE_PAYLOAD,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    scene_path = Path(payload["scene_path"])
    assert scene_path.exists()
    assert "class GeneratedScene" in scene_path.read_text()
