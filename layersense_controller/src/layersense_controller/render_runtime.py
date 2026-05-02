from pathlib import Path
from typing import Literal

from layersense_controller.config import settings


def scene_uuid_from_scene_path(scene_path: Path) -> str:
    stem = scene_path.stem
    if stem.startswith("generated_"):
        generated_uuid = stem.removeprefix("generated_")
        if generated_uuid:
            return generated_uuid
    return stem


def is_generated_scene_path(scene_path: Path) -> bool:
    return scene_path.stem.startswith("generated_")


def artifact_url_by_hash(content_hash: str, kind: Literal["preview", "final"]) -> str:
    return f"/artifacts/by-hash/{content_hash}/{kind}"


def scene_relative_artifact_path(path: Path) -> str:
    scenes_root = (settings.artifacts_dir / "scenes").resolve()
    return path.resolve().relative_to(scenes_root).as_posix()
