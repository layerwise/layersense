import hashlib
import json
import multiprocessing
import time
from unittest.mock import ANY

import pytest
from layersense_controller.cache import (
    hash_file,
    is_cached,
    lookup_cached_artifacts,
    lookup_content_hash_for_scene,
    store_cached_artifacts,
)
from layersense_controller.config import settings

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def _store_cached_artifacts_in_subprocess(artifacts_dir: str) -> None:
    from pathlib import Path

    from layersense_controller.cache import store_cached_artifacts
    from layersense_controller.config import settings as child_settings

    child_settings.artifacts_dir = Path(artifacts_dir)
    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        final="demo/final/scene.mp4",
    )


def test_hash_file_is_sha256(tmp_path):
    """Hash files using SHA-256 content digests."""
    input_file = tmp_path / "scene.py"
    contents = b"print('hello')\n"
    input_file.write_bytes(contents)

    expected = hashlib.sha256(contents).hexdigest()

    assert hash_file(input_file) == expected


def test_is_cached_false_when_no_files(tmp_path, monkeypatch):
    """Report no cached artifacts when preview and final files are absent."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    assert is_cached("abc123") == (False, False)


def test_is_cached_preview_true(tmp_path, monkeypatch):
    """Report preview cache hits when only the preview artifact exists."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    (tmp_path / "abc123_preview.mp4").write_bytes(b"preview")

    assert is_cached("abc123") == (True, False)


def test_lookup_cache_miss_returns_no_artifacts(tmp_path, monkeypatch):
    """Return cache misses when no cache index entry exists."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    assert lookup_cached_artifacts("abc123") is None
    assert lookup_content_hash_for_scene("scene-123") is None


def test_store_and_lookup_cached_artifacts_round_trip(tmp_path, monkeypatch):
    """Persist cached artifact metadata and read it back losslessly."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    preview = tmp_path / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    final = tmp_path / "scenes" / "demo" / "final" / "scene_final.mp4"
    preview.parent.mkdir(parents=True)
    final.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        preview="demo/preview/scene_preview.mp4",
        final="demo/final/scene_final.mp4",
    )

    assert lookup_cached_artifacts("hash-1") == {
        "scene_path": "code/generated_scene-123.py",
        "scene_uuid": "scene-123",
        "preview": "demo/preview/scene_preview.mp4",
        "final": "demo/final/scene_final.mp4",
        "artifact_version": 1,
        "updated_at": ANY,
    }
    assert lookup_content_hash_for_scene("scene-123") == "hash-1"

    index_data = json.loads((tmp_path / "cache" / "index.json").read_text())
    assert index_data["by_scene_uuid"] == {"scene-123": "hash-1"}


def test_scene_uuid_maps_to_latest_content_hash(tmp_path, monkeypatch):
    """Map each scene UUID to the most recently stored content hash."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    first_final = tmp_path / "scenes" / "demo" / "final" / "scene_v1.mp4"
    second_final = tmp_path / "scenes" / "demo" / "final" / "scene_v2.mp4"
    first_final.parent.mkdir(parents=True)
    first_final.write_bytes(b"v1")
    second_final.write_bytes(b"v2")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        final="demo/final/scene_v1.mp4",
    )
    store_cached_artifacts(
        content_hash="hash-2",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        final="demo/final/scene_v2.mp4",
    )

    assert lookup_content_hash_for_scene("scene-123") == "hash-2"
    assert lookup_cached_artifacts("hash-2") is not None


def test_reusing_hash_for_new_scene_uuid_removes_stale_reverse_mapping(tmp_path, monkeypatch):
    """Remove stale reverse mappings when a hash is reused for a new scene UUID."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    final = tmp_path / "scenes" / "demo" / "final" / "scene.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-old",
        scene_path="code/generated_scene-old.py",
        final="demo/final/scene.mp4",
    )
    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-new",
        scene_path="code/generated_scene-new.py",
        final="demo/final/scene.mp4",
    )

    assert lookup_content_hash_for_scene("scene-old") is None
    assert lookup_content_hash_for_scene("scene-new") == "hash-1"

    index_data = json.loads((tmp_path / "cache" / "index.json").read_text())
    assert index_data["by_scene_uuid"] == {"scene-new": "hash-1"}


def test_lookup_ignores_missing_indexed_files(tmp_path, monkeypatch):
    """Drop missing artifact files while preserving surviving cached entries."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    preview = tmp_path / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        preview="demo/preview/scene_preview.mp4",
        final="demo/final/missing_final.mp4",
    )

    assert lookup_cached_artifacts("hash-1") == {
        "scene_path": "code/generated_scene-123.py",
        "scene_uuid": "scene-123",
        "preview": "demo/preview/scene_preview.mp4",
        "final": None,
        "artifact_version": 1,
        "updated_at": ANY,
    }


def test_lookup_rejects_paths_outside_scenes_root(tmp_path, monkeypatch):
    """Reject cached artifact records that escape the scenes root."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "../escape.mp4",
                        "final": None,
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    assert lookup_cached_artifacts("hash-1") is None


def test_store_rejects_paths_outside_scenes_root(tmp_path, monkeypatch):
    """Reject storing cached artifact paths outside the scenes root."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    with pytest.raises(ValueError, match="scenes"):
        store_cached_artifacts(
            content_hash="hash-1",
            scene_uuid="scene-123",
            scene_path="code/generated_scene-123.py",
            preview="../escape.mp4",
        )


def test_store_waits_for_cache_lock(tmp_path, monkeypatch):
    """Wait for the cache lock before updating the shared cache index."""
    fcntl = pytest.importorskip("fcntl")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    lock_path = tmp_path / "cache" / "index.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process = multiprocessing.Process(
            target=_store_cached_artifacts_in_subprocess,
            args=(str(tmp_path),),
        )
        process.start()

        time.sleep(0.2)
        assert process.is_alive()

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    process.join(timeout=5)

    assert process.exitcode == 0
    assert lookup_content_hash_for_scene("scene-123") == "hash-1"


def test_corrupt_index_degrades_to_cache_miss(tmp_path, monkeypatch):
    """Treat corrupt cache index files as cache misses."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not valid json")

    assert lookup_cached_artifacts("hash-1") is None
    assert lookup_content_hash_for_scene("scene-123") is None


def test_partially_corrupt_index_record_degrades_to_cache_miss(tmp_path, monkeypatch):
    """Treat malformed cache index records as cache misses."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {"hash-1": {"scene_uuid": "scene-123"}},
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    assert lookup_cached_artifacts("hash-1") is None
    assert lookup_content_hash_for_scene("scene-123") is None


def test_non_string_scene_reverse_mapping_degrades_to_cache_miss(tmp_path, monkeypatch):
    """Ignore scene reverse mappings whose content hash is not a string."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {},
                "by_scene_uuid": {"scene-123": 123},
            }
        )
    )

    assert lookup_content_hash_for_scene("scene-123") is None


def test_reverse_mapping_to_different_scene_uuid_degrades_to_cache_miss(tmp_path, monkeypatch):
    """Ignore reverse mappings that point at a different scene UUID record."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    final = tmp_path / "scenes" / "demo" / "final" / "scene.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-other.py",
                        "scene_uuid": "scene-other",
                        "preview": None,
                        "final": "demo/final/scene.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    assert lookup_content_hash_for_scene("scene-123") is None


def test_reverse_mapping_to_unsafe_artifact_path_degrades_to_cache_miss(tmp_path, monkeypatch):
    """Ignore reverse mappings whose artifact paths escape the scenes root."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "../escape.mp4",
                        "final": None,
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    assert lookup_content_hash_for_scene("scene-123") is None


def test_store_recovers_from_corrupt_index(tmp_path, monkeypatch):
    """Recover by rewriting the cache index after corruption."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    index_path = tmp_path / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("{not valid json")

    final = tmp_path / "scenes" / "demo" / "final" / "scene.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-123",
        scene_path="code/generated_scene-123.py",
        final="demo/final/scene.mp4",
    )

    assert lookup_content_hash_for_scene("scene-123") == "hash-1"
    assert lookup_cached_artifacts("hash-1") == {
        "scene_path": "code/generated_scene-123.py",
        "scene_uuid": "scene-123",
        "preview": None,
        "final": "demo/final/scene.mp4",
        "artifact_version": 1,
        "updated_at": ANY,
    }
