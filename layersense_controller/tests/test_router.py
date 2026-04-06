import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from layersense_controller.config import settings
from layersense_controller.render import RenderError
from layersense_controller.router import _render_pipeline, router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health() -> None:
    client = _build_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_render_returns_404_for_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    client = _build_client()
    missing_path = tmp_path / "missing_scene.py"

    response = client.post(
        "/render",
        json={"scene_path": str(missing_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_cached_when_artifacts_exist(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")

    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
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
                    content_hash: {
                        "scene_path": str(scene_path),
                        "scene_uuid": "demo_scene",
                        "preview": "_root/preview/demo_scene_preview.mp4",
                        "final": "_root/final/demo_scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "cached"}
    assert len(events) == 1
    assert events[0]["type"] == "artifact_ready"
    assert events[0]["preview_url"] == f"/artifacts/by-hash/{content_hash}/preview"
    assert events[0]["final_url"] == f"/artifacts/by-hash/{content_hash}/final"


def test_render_queues_when_canonical_artifacts_exist_without_cache_index(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    events: list[dict[str, str]] = []

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == hashlib.sha256(scene_path.read_bytes()).hexdigest()
        return preview

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == hashlib.sha256(scene_path.read_bytes()).hexdigest()
        return final

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-1",
            "url": f"/artifacts/by-hash/{hashlib.sha256(scene_path.read_bytes()).hexdigest()}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-1",
            "url": f"/artifacts/by-hash/{hashlib.sha256(scene_path.read_bytes()).hexdigest()}/final",
        },
    ]


def test_render_skips_cached_fast_path_when_index_points_to_missing_files(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": str(scene_path),
                        "scene_uuid": "demo_scene",
                        "preview": "_root/preview/missing_preview.mp4",
                        "final": "_root/final/missing_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-stale-index"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-stale-index",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-stale-index",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


def test_render_returns_404_for_directory_path(tmp_path) -> None:
    client = _build_client()
    directory_path = tmp_path / "scene_dir"
    directory_path.mkdir()

    response = client.post(
        "/render",
        json={"scene_path": str(directory_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_400_for_scene_outside_configured_scenes_dir(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    client = _build_client()

    off_root_scene = tmp_path / "outside.py"
    off_root_scene.write_text("print('outside')\n")

    response = client.post(
        "/render",
        json={"scene_path": str(off_root_scene), "conversation_id": "conv-1"},
    )

    assert response.status_code == 400
    assert "configured scenes_dir" in response.json()["detail"]


def test_artifact_returns_404_for_directory(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    (artifacts_dir / "dir.mp4").mkdir()

    client = _build_client()
    response = client.get("/artifacts/dir.mp4")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"


def test_artifact_serves_nested_scene_path(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifact_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"preview")
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    client = _build_client()
    response = client.get("/artifacts/scenes/demo/preview/scene_preview.mp4")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_rejects_non_scene_files(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    cache_index = artifacts_dir / "cache" / "index.json"
    cache_index.parent.mkdir(parents=True)
    cache_index.write_text("{}")
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    client = _build_client()
    response = client.get("/artifacts/cache/index.json")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"


def test_artifact_by_hash_serves_preview(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    preview_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"preview")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "demo/preview/scene_preview.mp4",
                        "final": None,
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    client = _build_client()
    response = client.get("/artifacts/by-hash/hash-1/preview")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_scene_route_prefers_final_and_falls_back_to_preview(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    preview_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    final_path = artifacts_dir / "scenes" / "demo" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True)
    final_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"preview")
    final_path.write_bytes(b"final")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "demo/preview/scene_preview.mp4",
                        "final": "demo/final/scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    client = _build_client()

    response = client.get("/artifacts/scenes/scene-123")
    assert response.status_code == 200
    assert response.content == b"final"

    final_path.unlink()
    response = client.get("/artifacts/scenes/scene-123")
    assert response.status_code == 200
    assert response.content == b"preview"

    response = client.get("/artifacts/scenes/scene-123?preview=true")
    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_scene_route_uses_generated_filename_stem_as_scene_uuid(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    final_path = artifacts_dir / "scenes" / "demo" / "final" / "scene_final.mp4"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"final")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_123e4567.py",
                        "scene_uuid": "123e4567",
                        "preview": None,
                        "final": "demo/final/scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"123e4567": "hash-1"},
            }
        )
    )

    client = _build_client()
    response = client.get("/artifacts/scenes/123e4567")

    assert response.status_code == 200
    assert response.content == b"final"


def test_render_reuses_full_cached_hash_for_different_generated_scene_uuid(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "generated_new-scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview = artifacts_dir / "scenes" / "_root" / "preview" / "generated_new-scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "generated_new-scene_final.mp4"
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
                    content_hash: {
                        "scene_path": "generated_old-scene.py",
                        "scene_uuid": "old-scene",
                        "preview": "_root/preview/generated_new-scene_preview.mp4",
                        "final": "_root/final/generated_new-scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"old-scene": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-reuse-generated"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "cached"}
    assert events == [
        {
            "type": "artifact_ready",
            "conversation_id": "conv-reuse-generated",
            "preview_url": f"/artifacts/by-hash/{content_hash}/preview",
            "final_url": f"/artifacts/by-hash/{content_hash}/final",
        }
    ]

    scene_response = client.get("/artifacts/scenes/new-scene")
    assert scene_response.status_code == 200
    assert scene_response.content == b"final"


def test_render_treats_non_generated_scene_with_index_entry_as_uncached(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    (scenes_dir / "algebra").mkdir(parents=True)
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "algebra" / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview = artifacts_dir / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "algebra" / "final" / "demo_scene_final.mp4"
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
                    content_hash: {
                        "scene_path": "algebra/demo_scene.py",
                        "scene_uuid": "demo-scene-uuid",
                        "preview": "algebra/preview/demo_scene_preview.mp4",
                        "final": "algebra/final/demo_scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo-scene-uuid": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        return preview

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        return final

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-manual-scene"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-manual-scene",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-manual-scene",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


@pytest.mark.asyncio
async def test_render_pipeline_renders_non_generated_scene_when_hash_match_belongs_to_other_scene(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    (scenes_dir / "algebra").mkdir(parents=True)
    (scenes_dir / "geometry").mkdir(parents=True)
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "algebra" / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": "geometry/demo_scene.py",
                        "scene_uuid": "other-scene-uuid",
                        "preview": "geometry/preview/demo_scene_preview.mp4",
                        "final": "geometry/final/demo_scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"other-scene-uuid": content_hash},
            }
        )
    )

    preview_target = artifacts_dir / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "algebra" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, str]] = []

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-non-generated-hash-collision",
    )

    assert preview_target.exists()
    assert final_target.exists()
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-non-generated-hash-collision",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-non-generated-hash-collision",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


@pytest.mark.asyncio
async def test_render_pipeline_keeps_latest_generated_scene_uuid_mapping(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "generated_scene-123.py"
    scene_path.write_text("print('new')\n")
    old_content_hash = "old-hash"
    new_content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    old_preview = (
        artifacts_dir / "scenes" / "_root" / "preview" / "generated_scene-123_preview.mp4"
    )
    old_final = artifacts_dir / "scenes" / "_root" / "final" / "generated_scene-123_final.mp4"
    old_preview.parent.mkdir(parents=True, exist_ok=True)
    old_final.parent.mkdir(parents=True, exist_ok=True)
    old_preview.write_bytes(b"old-preview")
    old_final.write_bytes(b"old-final")

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    old_content_hash: {
                        "scene_path": "generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "_root/preview/generated_scene-123_preview.mp4",
                        "final": "_root/final/generated_scene-123_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": old_content_hash},
            }
        )
    )

    new_preview = (
        artifacts_dir / "scenes" / "_root" / "preview" / "generated_scene-123_preview.mp4"
    )
    new_final = artifacts_dir / "scenes" / "_root" / "final" / "generated_scene-123_final.mp4"

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == new_content_hash
        new_preview.write_bytes(b"new-preview")
        return new_preview

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == new_content_hash
        new_final.write_bytes(b"new-final")
        return new_final

    async def fake_broadcast(event: dict[str, str]) -> None:
        return None

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=new_content_hash,
        conversation_id="conv-latest-generated",
    )

    response = _build_client().get("/artifacts/scenes/scene-123")

    assert response.status_code == 200
    assert response.content == b"new-final"


def test_render_queues_and_broadcasts_preview_and_final(tmp_path, monkeypatch, caplog) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "queued_scene.py"
    scene_path.write_text("print('queued')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "queued_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "queued_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    with caplog.at_level("INFO", logger="layersense_controller.router"):
        response = client.post(
            "/render",
            json={"scene_path": str(scene_path), "conversation_id": "conv-queued"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-queued",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-queued",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]
    assert preview_target.exists()
    assert final_target.exists()
    index_data = json.loads((artifacts_dir / "cache" / "index.json").read_text())
    assert index_data["by_hash"][content_hash] == {
        "scene_path": "queued_scene.py",
        "scene_uuid": "queued_scene",
        "preview": "_root/preview/queued_scene_preview.mp4",
        "final": "_root/final/queued_scene_final.mp4",
        "updated_at": index_data["by_hash"][content_hash]["updated_at"],
        "artifact_version": 1,
    }
    assert index_data["by_scene_uuid"] == {"queued_scene": content_hash}

    artifact_client = _build_client()
    preview_response = artifact_client.get(f"/artifacts/by-hash/{content_hash}/preview")
    final_response = artifact_client.get(f"/artifacts/by-hash/{content_hash}/final")

    assert preview_response.status_code == 200
    assert preview_response.content == b"preview"
    assert final_response.status_code == 200
    assert final_response.content == b"final"
    assert [record.message for record in caplog.records] == [
        f"render started for conv-queued: {scene_path}",
        f"preview ready for conv-queued: {preview_target}",
        f"render ready for conv-queued: {final_target}",
    ]


def test_render_queued_path_uses_canonical_scene_outputs_for_cache_check(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    legacy_preview = artifacts_dir / f"{content_hash}_preview.mp4"
    legacy_final = artifacts_dir / f"{content_hash}_final.mp4"
    legacy_preview.write_bytes(b"legacy-preview")
    legacy_final.write_bytes(b"legacy-final")

    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)

    events: list[dict[str, str]] = []

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-canonical"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert preview_target.exists()
    assert final_target.exists()
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-canonical",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-canonical",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


@pytest.mark.asyncio
async def test_render_pipeline_broadcasts_cached_final_after_rendering_missing_preview(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.write_bytes(b"final")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": "demo_scene.py",
                        "scene_uuid": "demo_scene",
                        "preview": None,
                        "final": "_root/final/demo_scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-partial-preview",
    )

    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-partial-preview",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-partial-preview",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


@pytest.mark.asyncio
async def test_render_pipeline_broadcasts_cached_preview_before_rendering_missing_final(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    preview_target = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final_target = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    final_target.parent.mkdir(parents=True, exist_ok=True)
    preview_target.write_bytes(b"preview")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": "demo_scene.py",
                        "scene_uuid": "demo_scene",
                        "preview": "_root/preview/demo_scene_preview.mp4",
                        "final": None,
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    events: list[dict[str, str]] = []

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-partial-final",
    )

    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-partial-final",
            "url": f"/artifacts/by-hash/{content_hash}/preview",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-partial-final",
            "url": f"/artifacts/by-hash/{content_hash}/final",
        },
    ]


@pytest.mark.asyncio
async def test_render_pipeline_logs_and_broadcasts_render_error(
    tmp_path, monkeypatch, caplog
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "render_error_scene.py"
    scene_path.write_text("print('broken')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    render_error = RenderError("manim exited with code 1", "traceback lines")

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        raise render_error

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    with caplog.at_level("WARNING", logger="layersense_controller.router"):
        await _render_pipeline(
            scene_path=scene_path,
            content_hash=content_hash,
            conversation_id="conv-render-error",
        )

    assert events == [
        {
            "type": "render_failed",
            "conversation_id": "conv-render-error",
            "error": "manim exited with code 1",
            "stderr": "traceback lines",
        }
    ]
    assert [record.message for record in caplog.records if record.levelname == "WARNING"] == [
        (
            "render failed for conv-render-error at "
            f"{scene_path}: manim exited with code 1; stderr=traceback lines"
        )
    ]


@pytest.mark.asyncio
async def test_render_pipeline_broadcasts_failure_for_unexpected_errors(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "broken_scene.py"
    scene_path.write_text("print('broken')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        raise RuntimeError("preview exploded")

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-fail",
    )

    assert events == [
        {
            "type": "render_failed",
            "conversation_id": "conv-fail",
            "error": "preview exploded",
            "stderr": "",
        }
    ]
