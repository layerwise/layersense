import asyncio
from pathlib import Path

import layersense_controller.render as render_module
import pytest
from layersense_controller.render import CLIFlags, RenderError, render_final, render_preview

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_config_file_path_resolves_packaged_resource() -> None:
    """Resolve packaged Manim config resources through the integration boundary."""
    assert render_module._config_file_path("preview").name == "manim-preview.cfg"


def test_cli_flags_include_all_supported_options() -> None:
    """Serialize every supported controller CLI flag to Manim arguments."""
    args = render_module._cli_args(
        CLIFlags(
            quality="m",
            resolution="1920,1080",
            frame_rate=30,
            renderer="cairo",
            from_animation_number="2,4",
        )
    )

    assert args == [
        "-q",
        "m",
        "-r",
        "1920,1080",
        "--fps",
        "30.0",
        "--renderer",
        "cairo",
        "-n",
        "2,4",
    ]


@pytest.mark.asyncio
async def test_run_manim_reports_process_start_failure(tmp_path, monkeypatch) -> None:
    """Raise RenderError when the Manim subprocess cannot be started."""
    scene_path = tmp_path / "scene.py"
    scene_path.write_text("print('demo')\n")

    async def fail_to_start(*args: object, **kwargs: object) -> object:
        raise OSError("missing manim")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_to_start)

    with pytest.raises(RenderError, match="failed to start manim process") as exc_info:
        await render_module._run_manim(scene_path, "preview")

    assert "missing manim" in exc_info.value.stderr


@pytest.mark.asyncio
async def test_render_wrappers_delegate_to_run_manim(tmp_path, monkeypatch) -> None:
    """Delegate preview and final rendering wrappers to the shared Manim runner."""
    scene_path = tmp_path / "scene.py"
    preview_path = tmp_path / "preview.mp4"
    final_path = tmp_path / "final.mp4"
    calls: list[tuple[Path, str, CLIFlags | None]] = []

    async def fake_run_manim(scene_path_arg: Path, render_kind: str, cli_flags=None) -> Path:
        calls.append((scene_path_arg, render_kind, cli_flags))
        return preview_path if render_kind == "preview" else final_path

    monkeypatch.setattr(render_module, "_run_manim", fake_run_manim)
    cli_flags = CLIFlags(quality="l")

    assert await render_preview(scene_path, "hash-1", cli_flags) == preview_path
    assert await render_final(scene_path, "hash-1", cli_flags) == final_path
    assert calls == [(scene_path, "preview", cli_flags), (scene_path, "final", cli_flags)]
