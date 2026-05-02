import pytest
from layersense_agent.models.scene import NormalizedScene
from pydantic import ValidationError

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_normalized_scene_accepts_rectangle_ellipse_and_freedraw() -> None:
    """Accept supported normalized Excalidraw element variants."""
    payload = {
        "elements": [
            {
                "id": "rect-1",
                "type": "rectangle",
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "opacity": 100,
            },
            {
                "id": "ellipse-1",
                "type": "ellipse",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 80,
                "angle": 0,
                "strokeColor": "#ff0000",
                "backgroundColor": "#ffffff",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
            },
            {
                "id": "path-1",
                "type": "freedraw",
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
                "points": [[0, 0], [1, 1]],
            },
        ],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }

    scene = NormalizedScene.model_validate(payload)

    assert len(scene.elements) == 3
    assert scene.appState.viewBackgroundColor == "#ffffff"


def test_freedraw_requires_points() -> None:
    """Require point data for normalized freedraw elements."""
    payload = {
        "elements": [
            {
                "id": "path-1",
                "type": "freedraw",
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

    with pytest.raises(ValidationError):
        NormalizedScene.model_validate(payload)


def test_normalized_scene_accepts_partial_app_state() -> None:
    """Allow partial app state data in normalized scene payloads."""
    payload = {
        "elements": [
            {
                "id": "rect-1",
                "type": "rectangle",
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "opacity": 100,
            }
        ],
        "appState": {"zoom": 1.5},
        "files": {"file-1": {"mimeType": "image/png"}},
    }

    scene = NormalizedScene.model_validate(payload)

    assert scene.appState.viewBackgroundColor is None
    assert scene.files.root["file-1"] == {"mimeType": "image/png"}


def test_normalized_scene_rejects_unsupported_element_type() -> None:
    """Reject scene payloads containing unsupported element discriminators."""
    payload = {
        "elements": [
            {
                "id": "diamond-1",
                "type": "diamond",
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

    with pytest.raises(ValidationError, match="type"):
        NormalizedScene.model_validate(payload)
