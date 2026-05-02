import pytest
from layersense_agent.services.scene_normalizer import normalize_scene

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def make_rectangle(*, element_id: str, element_type: str = "rectangle") -> dict[str, object]:
    return {
        "id": element_id,
        "type": element_type,
        "x": 5,
        "y": 5,
        "width": 20,
        "height": 20,
        "angle": 0,
        "strokeColor": "#000000",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "opacity": 100,
    }


def test_normalize_scene_filters_deleted_elements() -> None:
    """Drop deleted elements before validating the normalized scene."""
    payload = {
        "elements": [
            {
                "id": "deleted-1",
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
            },
            make_rectangle(element_id="live-1"),
        ],
        "appState": {},
        "files": {},
    }

    scene = normalize_scene(payload)

    assert len(scene.elements) == 1
    assert scene.elements[0].id == "live-1"


def test_normalize_scene_rejects_malformed_elements() -> None:
    """Fail fast when scene elements are not structured dictionaries."""
    payload = {
        "elements": ["not-a-dict", make_rectangle(element_id="live-1")],
        "appState": {},
        "files": {},
    }

    with pytest.raises(ValueError, match="Malformed scene element"):
        normalize_scene(payload)


def test_normalize_scene_filters_unsupported_elements() -> None:
    """Drop unsupported element types during scene normalization."""
    payload = {
        "elements": [
            {**make_rectangle(element_id="unsupported-1"), "type": "diamond"},
            make_rectangle(element_id="live-1"),
        ],
        "appState": {},
        "files": {},
    }

    scene = normalize_scene(payload)

    assert len(scene.elements) == 1
    assert scene.elements[0].id == "live-1"


def test_normalize_scene_rejects_effectively_empty_scene() -> None:
    """Reject scenes left empty after filtering unsupported elements."""
    payload = {
        "elements": [
            {**make_rectangle(element_id="deleted-1"), "isDeleted": True},
            {**make_rectangle(element_id="unsupported-1"), "type": "diamond"},
        ],
        "appState": {},
        "files": {},
    }

    with pytest.raises(ValueError, match="Scene has no supported non-deleted elements"):
        normalize_scene(payload)
