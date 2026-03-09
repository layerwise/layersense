import os
from pathlib import Path

import pytest

from layersense_controller.render import RenderError
from layersense_controller.render import _parse_output_path
from layersense_controller.render import render_preview


def test_parse_output_path_from_file_ready_line(tmp_path):
    scene_path = tmp_path / "scene.py"
    rendered = tmp_path / "media" / "videos" / "scene" / "480p15" / "GeneratedScene.mp4"
    manim_output = f"... File ready at '{rendered}' ..."

    parsed = _parse_output_path(manim_output, scene_path)

    assert parsed == rendered


def test_parse_output_path_from_quoted_file_ready_line_with_spaces(tmp_path):
    scene_path = tmp_path / "scene.py"
    rendered = tmp_path / "media" / "videos" / "scene with spaces" / "Generated Scene.mp4"
    manim_output = f"... File ready at '{rendered}' ..."

    parsed = _parse_output_path(manim_output, scene_path)

    assert parsed == rendered


def test_parse_output_path_fallback_chooses_latest_generated_scene(tmp_path, monkeypatch):
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    relative_scene = Path("project_a") / "scene.py"
    media_root = scenes_dir / relative_scene.parent / "media"
    older = media_root / "videos" / "scene" / "480p15" / "GeneratedScene.mp4"
    newer = media_root / "videos" / "scene" / "1080p60" / "GeneratedScene.mp4"

    older.parent.mkdir(parents=True)
    older.write_bytes(b"old")
    newer.parent.mkdir(parents=True)
    newer.write_bytes(b"new")

    now = newer.stat().st_mtime
    os.utime(older, (now - 10, now - 10))
    os.utime(newer, (now + 10, now + 10))

    parsed = _parse_output_path("no file line present", relative_scene)

    assert parsed == newer


def test_parse_output_path_fallback_supports_absolute_scene_path(tmp_path, monkeypatch):
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    scene_path = tmp_path / "project_b" / "scene.py"
    media_root = scene_path.parent / "media"
    expected = media_root / "videos" / "scene" / "480p15" / "GeneratedScene.mp4"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"video")

    parsed = _parse_output_path("no file line present", scene_path)

    assert parsed == expected


@pytest.mark.asyncio
async def test_render_preview_raises_on_nonzero_exit(tmp_path, monkeypatch):
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return (b"", b"fake stderr")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(RenderError, match="manim exited with code 1") as exc_info:
        await render_preview(scene_path, "abc123")

    assert exc_info.value.stderr == "fake stderr"


@pytest.mark.asyncio
async def test_render_preview_normalizes_subprocess_start_failures(tmp_path, monkeypatch):
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise OSError("spawn failure")

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(RenderError, match="failed to start manim process") as exc_info:
        await render_preview(scene_path, "abc123")

    assert exc_info.value.stderr == "spawn failure"
