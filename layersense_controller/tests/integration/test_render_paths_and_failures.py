import pytest
from layersense_controller.render import CLIFlags, RenderError, _run_manim

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_run_manim_passes_cli_flags_and_returns_expected_output_path(
    monkeypatch, tmp_path
) -> None:
    """Pass supported controller CLI flags through to manim and return the object-store staging output."""
    scene_path = tmp_path / "work" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    recorded = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"stdout", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded["args"] = args
        raw_output = scene_path.parent / "media" / "preview.mp4"
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_bytes(b"preview")
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    output = await _run_manim(scene_path, "preview", CLIFlags(quality="m", renderer="cairo"))

    assert output == scene_path.parent / "media" / "preview.mp4"
    assert "-q" in recorded["args"]
    assert "m" in recorded["args"]
    assert "--renderer" in recorded["args"]
    assert "cairo" in recorded["args"]


@pytest.mark.asyncio
async def test_run_manim_raises_render_error_when_process_fails(monkeypatch, tmp_path) -> None:
    """Raise RenderError with stderr content when manim exits non-zero."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('demo')\n")

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
