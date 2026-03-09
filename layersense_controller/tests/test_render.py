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
