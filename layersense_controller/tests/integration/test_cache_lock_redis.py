import json
import threading

import fakeredis
import layersense_controller.cache as cache_module
import pytest
from layersense_controller.cache import (
    final_artifact,
    is_cached,
    lookup_content_hash_for_scene,
    preview_artifact,
    store_cached_artifacts,
)
from layersense_controller.config import settings
from layersense_controller.locks import LockAcquisitionError

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_store_cached_artifacts_uses_redis_lock_transparently(tmp_path, monkeypatch) -> None:
    """Store cache metadata through the Redis-backed lock without changing index shape."""
    redis = _patch_cache_redis(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    final = artifacts_dir / "scenes" / "_root" / "final" / "scene.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")

    store_cached_artifacts(
        content_hash="hash-1",
        scene_uuid="scene-1",
        scene_path="scene.py",
        final="_root/final/scene.mp4",
    )

    index = json.loads((artifacts_dir / "cache" / "index.json").read_text())
    assert index["by_hash"]["hash-1"]["final"] == "_root/final/scene.mp4"
    assert redis.get(cache_module.CACHE_INDEX_LOCK_KEY) is None
    assert preview_artifact("hash-1") == artifacts_dir / "hash-1_preview.mp4"
    assert final_artifact("hash-1") == artifacts_dir / "hash-1_final.mp4"
    assert is_cached("hash-1") == (False, False)


def test_store_cached_artifacts_serializes_concurrent_writers(tmp_path, monkeypatch) -> None:
    """Merge concurrent cache writes instead of losing one writer's index update."""
    _patch_cache_redis(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    for name in ("one", "two"):
        final = artifacts_dir / "scenes" / "_root" / "final" / f"{name}.mp4"
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(name.encode())

    errors: list[BaseException] = []

    def store(name: str) -> None:
        try:
            store_cached_artifacts(
                content_hash=f"hash-{name}",
                scene_uuid=f"scene-{name}",
                scene_path=f"{name}.py",
                final=f"_root/final/{name}.mp4",
            )
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=store, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    index = json.loads((artifacts_dir / "cache" / "index.json").read_text())
    assert set(index["by_hash"]) == {"hash-one", "hash-two"}
    assert index["by_scene_uuid"] == {"scene-one": "hash-one", "scene-two": "hash-two"}


def test_store_cached_artifacts_raises_when_redis_lock_is_occupied(tmp_path, monkeypatch) -> None:
    """Abort the cache write when the Redis cache-index lock cannot be acquired."""
    redis = _patch_cache_redis(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(cache_module, "CACHE_LOCK_ACQUIRE_TIMEOUT_MS", 20, raising=False)
    final = artifacts_dir / "scenes" / "_root" / "final" / "scene.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")
    redis.set(cache_module.CACHE_INDEX_LOCK_KEY, "foreign", px=1_000)

    with pytest.raises(LockAcquisitionError):
        store_cached_artifacts(
            content_hash="hash-1",
            scene_uuid="scene-1",
            scene_path="scene.py",
            final="_root/final/scene.mp4",
        )

    assert not (artifacts_dir / "cache" / "index.json").exists()


def test_cache_index_validation_edges_remain_lock_independent(tmp_path, monkeypatch) -> None:
    """Keep cache-index validation behavior intact after moving locking to Redis."""
    _patch_cache_redis(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True)

    index_path.write_text("[]")
    assert lookup_content_hash_for_scene("scene-1") is None

    malformed_records = [
        {
            "scene_uuid": "scene-1",
            "preview": None,
            "final": None,
            "updated_at": "now",
            "artifact_version": 1,
        },
        {
            "scene_path": "scene.py",
            "preview": None,
            "final": None,
            "updated_at": "now",
            "artifact_version": 1,
        },
        {
            "scene_path": "scene.py",
            "scene_uuid": "scene-1",
            "preview": 1,
            "final": None,
            "updated_at": "now",
            "artifact_version": 1,
        },
        {
            "scene_path": "scene.py",
            "scene_uuid": "scene-1",
            "preview": None,
            "final": 1,
            "updated_at": "now",
            "artifact_version": 1,
        },
        {
            "scene_path": "scene.py",
            "scene_uuid": "scene-1",
            "preview": None,
            "final": None,
            "artifact_version": 1,
        },
        {
            "scene_path": "scene.py",
            "scene_uuid": "scene-1",
            "preview": None,
            "final": None,
            "updated_at": "now",
        },
    ]
    for record in malformed_records:
        index_path.write_text(
            json.dumps(
                {
                    "by_hash": {"hash-1": record},
                    "by_scene_uuid": {"scene-1": "hash-1"},
                }
            )
        )
        assert lookup_content_hash_for_scene("scene-1") is None


def _patch_cache_redis(monkeypatch) -> fakeredis.FakeRedis:
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(cache_module, "_cache_redis_client", lambda: redis)
    return redis
