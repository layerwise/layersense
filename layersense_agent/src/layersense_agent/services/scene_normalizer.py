from typing import Any

from layersense_agent.models.scene import NormalizedScene

SUPPORTED_ELEMENT_TYPES = frozenset({"rectangle", "ellipse", "freedraw"})


def normalize_scene(payload: dict[str, Any]) -> NormalizedScene:
    filtered_elements = []
    for element in payload.get("elements", []):
        if not isinstance(element, dict):
            raise ValueError("Malformed scene element")
        if element.get("isDeleted", False):
            continue
        if element.get("type") not in SUPPORTED_ELEMENT_TYPES:
            continue
        filtered_elements.append(element)

    if not filtered_elements:
        raise ValueError("Scene has no supported non-deleted elements")

    normalized_payload = {
        "elements": filtered_elements,
        "appState": payload.get("appState", {}),
        "files": payload.get("files", {}),
    }
    return NormalizedScene.model_validate(normalized_payload)
