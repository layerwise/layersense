from pathlib import Path

import pytest
from layersense_controller.config import settings
from layersense_controller.render import (
    CLIFlags,
    RenderError,
    _output_file_path,
    _raw_output_path,
    _run_manim,
)
from layersense_controller.render_runtime import scene_relative_artifact_path
from layersense_domain.models import RenderOptions

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_run_manim_passes_cli_flags_and_returns_expected_output_path(
    monkeypatch, tmp_path
) -> None:
    """Pass supported controller CLI flags through to manim and return the expected preview output path."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scene_path = scenes_dir / "algebra" / "demo_scene.py"
    scene_path.parent.mkdir(parents=True)
    artifacts_dir.mkdir()
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    recorded = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"stdout", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        raw_output = artifacts_dir / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_bytes(b"preview")
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    output = await _run_manim(
        scene_path,
        "preview",
        CLIFlags(quality="m", renderer="cairo"),
    )

    assert output == artifacts_dir / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
    assert "-q" in recorded["args"]
    assert "m" in recorded["args"]
    assert "--renderer" in recorded["args"]
    assert "cairo" in recorded["args"]


@pytest.mark.asyncio
async def test_run_manim_raises_render_error_when_process_fails(monkeypatch, tmp_path) -> None:
    """Raise RenderError with stderr content when manim exits non-zero."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scene_path = scenes_dir / "demo_scene.py"
    scene_path.parent.mkdir(parents=True)
    artifacts_dir.mkdir()
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    class FakeProcess:
        returncode = 2

        async def communicate(self):
            return (b"", b"stderr output")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RenderError, match="manim exited with code 2") as exc_info:
        await _run_manim(scene_path, "preview")

    assert exc_info.value.stderr == "stderr output"


@pytest.mark.asyncio
async def test_run_manim_raises_render_error_when_output_file_missing(
    monkeypatch, tmp_path
) -> None:
    """Raise RenderError when manim exits successfully but no mp4 is produced."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scene_path = scenes_dir / "demo_scene.py"
    scene_path.parent.mkdir(parents=True)
    artifacts_dir.mkdir()
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"stdout text", b"stderr text")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RenderError, match="Could not locate rendered .mp4 output."):
        await _run_manim(scene_path, "preview")


def test_render_path_helpers_preserve_nested_scene_layout(tmp_path, monkeypatch) -> None:
    """Build nested render output paths under the expected project layout."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scene_path = scenes_dir / "algebra" / "linear" / "demo_scene.py"
    scene_path.parent.mkdir(parents=True)
    artifacts_dir.mkdir()
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    assert _raw_output_path(scene_path, "preview") == (
        artifacts_dir / "scenes" / "algebra" / "preview" / "linear" / "demo_scene_preview.mp4"
    )
    assert (
        _output_file_path(scene_path, "preview").as_posix()
        == "algebra/preview/linear/demo_scene_preview"
    )


def test_scene_relative_artifact_path_returns_scenes_relative_path(tmp_path, monkeypatch) -> None:
    """Convert artifact files to paths relative to the scenes artifact root."""
    artifacts_dir = tmp_path / "artifacts"
    artifact = artifacts_dir / "scenes" / "algebra" / "preview" / "demo.mp4"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"preview")
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    assert scene_relative_artifact_path(artifact) == "algebra/preview/demo.mp4"
