import hashlib

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


def test_create_animation_records_live_model_response() -> None:
    """Record and replay the live model interaction through the API boundary."""
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
    assert "class GeneratedScene" in payload["source_code"]
    assert payload["content_hash"] == hashlib.sha256(payload["source_code"].encode()).hexdigest()
    assert "scene_path" not in payload
