import json

import pytest
from layersense_controller.cache import (
    lookup_cached_artifacts,
    lookup_content_hash_for_scene,
    store_cached_artifacts,
)
from layersense_controller.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_lookup_cached_artifacts_returns_none_for_invalid_json_index(
    tmp_path, monkeypatch
) -> None:
    """Treat invalid JSON cache indexes as empty cache state."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("{not-json")

    assert lookup_cached_artifacts("hash-1") is None


def test_lookup_cached_artifacts_returns_none_for_absolute_indexed_path(
    tmp_path, monkeypatch
) -> None:
    """Reject absolute indexed artifact paths from the cache index."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "demo.py",
                        "scene_uuid": "demo",
                        "preview": "/tmp/escaped.mp4",
                        "final": None,
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo": "hash-1"},
            }
        )
    )

    assert lookup_cached_artifacts("hash-1") is None


def test_lookup_content_hash_for_scene_returns_none_for_stale_scene_mapping(
    tmp_path, monkeypatch
) -> None:
    """Ignore stale scene UUID mappings that no longer match the stored record."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_final.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "demo.py",
                        "scene_uuid": "actual-demo",
                        "preview": "_root/preview/demo_preview.mp4",
                        "final": "_root/final/demo_final.mp4",
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"stale-demo": "hash-1"},
            }
        )
    )

    assert lookup_content_hash_for_scene("stale-demo") is None


def test_store_cached_artifacts_replaces_previous_scene_uuid_mapping(
    tmp_path, monkeypatch
) -> None:
    """Replace the old scene UUID mapping when the same content hash is reassigned."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_final.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="old-scene",
        scene_path="old.py",
        preview="_root/preview/demo_preview.mp4",
        final="_root/final/demo_final.mp4",
    )
    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="new-scene",
        scene_path="new.py",
    )

    index = json.loads((artifacts_dir / "cache" / "index.json").read_text())
    assert index["by_scene_uuid"]["new-scene"] == "hash-1"
    assert "old-scene" not in index["by_scene_uuid"]
    assert index["by_hash"]["hash-1"]["scene_path"] == "new.py"
