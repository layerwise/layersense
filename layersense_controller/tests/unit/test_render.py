from contextlib import contextmanager
from pathlib import Path

import pytest
from layersense_controller.render import (
    CLIFlags,
    RenderError,
    _config_file_path,
    render_final,
    render_preview,
)

pytestmark = [pytest.mark.unit, pytest.mark.ai]


@contextmanager
def fake_config_resource(base_dir: Path, filename: str):
    config_path = base_dir / filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[CLI]\n")
    yield config_path


@pytest.mark.asyncio
async def test_render_preview_uses_temp_media_dir_and_preview_output(
    monkeypatch, tmp_path
) -> None:
    """Render previews into the per-render temp workdir before ObjectStore upload."""
    scene_path = tmp_path / "work" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    expected_raw_output = scene_path.parent / "media" / "preview.mp4"
    captured_args: tuple[str, ...] | None = None

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.parent.mkdir(parents=True, exist_ok=True)
            expected_raw_output.write_bytes(b"preview")
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        captured_args = args
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    target = await render_preview(scene_path, "abc123")

    assert captured_args is not None
    assert "--media_dir" in captured_args
    assert str(scene_path.parent / "media") in captured_args
    assert "--output_file" in captured_args
    assert "preview" in captured_args
    assert target == expected_raw_output
    assert target.read_bytes() == b"preview"


@pytest.mark.asyncio
async def test_render_preview_passes_quality_and_renderer_flags(tmp_path, monkeypatch) -> None:
    """Pass supported controller CLI flags through to the Manim subprocess."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")
    expected_raw_output = scene_path.parent / "media" / "preview.mp4"
    captured_args: tuple[str, ...] | None = None

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.parent.mkdir(parents=True, exist_ok=True)
            expected_raw_output.write_bytes(b"preview")
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        captured_args = args
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    await render_preview(scene_path, "abc123", CLIFlags(quality="m", renderer="cairo"))

    assert captured_args is not None
    assert "-q" in captured_args
    assert "m" in captured_args
    assert "--renderer" in captured_args
    assert "cairo" in captured_args


@pytest.mark.asyncio
async def test_render_final_uses_final_config_and_output_name(tmp_path, monkeypatch) -> None:
    """Render final outputs into the temp workdir final movie path."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")
    expected_raw_output = scene_path.parent / "media" / "final.mp4"
    captured_args: tuple[str, ...] | None = None

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.parent.mkdir(parents=True, exist_ok=True)
            expected_raw_output.write_bytes(b"final")
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        captured_args = args
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    target = await render_final(scene_path, "abc123")

    assert captured_args is not None
    assert str(_config_file_path("final")) in captured_args
    assert "final" in captured_args
    assert target == expected_raw_output
    assert target.read_bytes() == b"final"


@pytest.mark.asyncio
async def test_render_preview_accepts_nested_manim_output_path(tmp_path, monkeypatch) -> None:
    """Accept Manim's nested default output path if a config produces it."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")
    expected_raw_output = (
        scene_path.parent / "media" / "videos" / "scene" / "1080p60" / "preview.mp4"
    )

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.parent.mkdir(parents=True, exist_ok=True)
            expected_raw_output.write_bytes(b"preview")
            return (b"", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    assert await render_preview(scene_path, "abc123") == expected_raw_output


@pytest.mark.parametrize("render_kind", ["preview", "final"])
def test_config_file_path_resolves_packaged_resource(render_kind: str) -> None:
    """Resolve packaged Manim config resources for each render kind."""
    config_path = _config_file_path(render_kind)

    assert config_path.is_file()
    assert config_path.name == f"manim-{render_kind}.cfg"


@pytest.mark.asyncio
async def test_render_preview_raises_on_nonzero_exit(tmp_path, monkeypatch) -> None:
    """Raise render errors when the Manim subprocess exits nonzero."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return (b"", b"fake stderr")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(RenderError, match="manim exited with code 1") as exc_info:
        await render_preview(scene_path, "abc123")

    assert exc_info.value.stderr == "fake stderr"


@pytest.mark.asyncio
async def test_render_preview_normalizes_subprocess_start_failures(tmp_path, monkeypatch) -> None:
    """Normalize subprocess startup failures into render errors."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('x')\n")

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise OSError("spawn failure")

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(RenderError, match="failed to start manim process") as exc_info:
        await render_preview(scene_path, "abc123")

    assert exc_info.value.stderr == "spawn failure"


def test_config_file_path_does_not_depend_on_repo_root(monkeypatch, tmp_path) -> None:
    """Resolve config resources without depending on the repo root path."""
    resource_dir = tmp_path / "resources"

    monkeypatch.setattr(
        "layersense_controller.render._config_resource",
        lambda render_kind: fake_config_resource(resource_dir, f"manim-{render_kind}.cfg"),
    )

    assert _config_file_path("preview") == resource_dir / "manim-preview.cfg"
