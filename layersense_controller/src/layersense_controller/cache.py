import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any, TypedDict

from layersense_controller.config import settings


class CachedArtifacts(TypedDict):
    scene_path: str
    scene_uuid: str
    preview: str | None
    final: str | None
    updated_at: str
    artifact_version: int


class CacheIndex(TypedDict):
    by_hash: dict[str, CachedArtifacts]
    by_scene_uuid: dict[str, str]


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_render_request(path: Path, cli_flags: dict[str, Any] | None = None) -> str:
    """Return SHA-256 hex digest of file contents plus controller CLI flags."""
    file_hash = hash_file(path)
    options_json = json.dumps(cli_flags or {}, sort_keys=True)
    return hashlib.sha256(f"{file_hash}:{options_json}".encode()).hexdigest()


def preview_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_preview.mp4"


def final_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_final.mp4"


def is_cached(content_hash: str) -> tuple[bool, bool]:
    """Return (preview_exists, final_exists)."""
    return (
        preview_artifact(content_hash).exists(),
        final_artifact(content_hash).exists(),
    )


def lookup_cached_artifacts(content_hash: str) -> CachedArtifacts | None:
    index = _load_cache_index()
    record = _cached_artifacts_record(index, content_hash)
    if record is None:
        return None

    try:
        preview = _checked_indexed_path(record["preview"])
        final = _checked_indexed_path(record["final"])
    except ValueError:
        return None

    result: CachedArtifacts = {
        "scene_path": record["scene_path"],
        "scene_uuid": record["scene_uuid"],
        "preview": record["preview"] if preview and preview.exists() else None,
        "final": record["final"] if final and final.exists() else None,
        "updated_at": record["updated_at"],
        "artifact_version": record["artifact_version"],
    }
    return result


def lookup_content_hash_for_scene(scene_uuid: str) -> str | None:
    index = _load_cache_index()
    content_hash = index["by_scene_uuid"].get(scene_uuid)
    if not isinstance(content_hash, str):
        return None
    record = _cached_artifacts_record(index, content_hash)
    if record is None:
        return None
    if record["scene_uuid"] != scene_uuid:
        return None
    try:
        _checked_indexed_path(record["preview"])
        _checked_indexed_path(record["final"])
    except ValueError:
        return None
    return content_hash


def store_cached_artifacts(
    content_hash: str,
    scene_uuid: str,
    scene_path: str,
    preview: str | None = None,
    final: str | None = None,
) -> None:
    if preview is not None:
        _checked_indexed_path(preview)
    if final is not None:
        _checked_indexed_path(final)

    with _cache_lock():
        index = _load_cache_index()
        existing = _cached_artifacts_record(index, content_hash)

        if existing is not None and existing["scene_uuid"] != scene_uuid:
            old_scene_uuid = existing["scene_uuid"]
            if index["by_scene_uuid"].get(old_scene_uuid) == content_hash:
                del index["by_scene_uuid"][old_scene_uuid]

        record: CachedArtifacts = {
            "scene_path": scene_path,
            "scene_uuid": scene_uuid,
            "preview": (
                preview if preview is not None else existing["preview"] if existing else None
            ),
            "final": final if final is not None else existing["final"] if existing else None,
            "updated_at": _utc_now(),
            "artifact_version": existing["artifact_version"] if existing else 1,
        }

        index["by_hash"][content_hash] = record
        index["by_scene_uuid"][scene_uuid] = content_hash
        _persist_cache_index(index)


def _cache_index_path() -> Path:
    return settings.artifacts_dir / "cache" / "index.json"


def _cache_lock_path() -> Path:
    return settings.artifacts_dir / "cache" / "index.lock"


def _load_cache_index() -> CacheIndex:
    index_path = _cache_index_path()
    if not index_path.exists():
        return {"by_hash": {}, "by_scene_uuid": {}}

    try:
        data = json.loads(index_path.read_text())
    except (JSONDecodeError, OSError):
        return {"by_hash": {}, "by_scene_uuid": {}}

    if not isinstance(data, dict):
        return {"by_hash": {}, "by_scene_uuid": {}}

    by_hash = data.get("by_hash", {})
    by_scene_uuid = data.get("by_scene_uuid", {})

    return {
        "by_hash": by_hash if isinstance(by_hash, dict) else {},
        "by_scene_uuid": by_scene_uuid if isinstance(by_scene_uuid, dict) else {},
    }


def _persist_cache_index(index: CacheIndex) -> None:
    index_path = _cache_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(index, indent=2, sort_keys=True))
    temp_path.replace(index_path)


@contextmanager
def _cache_lock():
    import fcntl

    lock_path = _cache_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _checked_indexed_path(relative_path: str | None) -> Path | None:
    if relative_path is None:
        return None

    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError("Indexed artifacts must stay inside scenes root")

    scenes_root = (settings.artifacts_dir / "scenes").resolve()
    resolved = (scenes_root / path).resolve()
    resolved.relative_to(scenes_root)
    return resolved


def _cached_artifacts_record(index: CacheIndex, content_hash: str) -> CachedArtifacts | None:
    raw_record = index["by_hash"].get(content_hash)
    if not isinstance(raw_record, dict):
        return None

    scene_path = raw_record.get("scene_path")
    scene_uuid = raw_record.get("scene_uuid")
    preview = raw_record.get("preview")
    final = raw_record.get("final")
    updated_at = raw_record.get("updated_at")
    artifact_version = raw_record.get("artifact_version")

    if not isinstance(scene_path, str):
        return None
    if not isinstance(scene_uuid, str):
        return None
    if preview is not None and not isinstance(preview, str):
        return None
    if final is not None and not isinstance(final, str):
        return None
    if not isinstance(updated_at, str):
        return None
    if not isinstance(artifact_version, int):
        return None

    return {
        "scene_path": scene_path,
        "scene_uuid": scene_uuid,
        "preview": preview,
        "final": final,
        "updated_at": updated_at,
        "artifact_version": artifact_version,
    }


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
