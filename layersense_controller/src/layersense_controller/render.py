import asyncio
import shutil
from importlib.resources import as_file, files
from pathlib import Path

from layersense_controller.cache import final_artifact, preview_artifact
from layersense_controller.config import settings

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class RenderError(Exception):
    def __init__(self, message: str, stderr: str) -> None:
        super().__init__(message)
        self.stderr = stderr


def _config_file_path(render_kind: str) -> Path:
    with _config_resource(render_kind) as config_path:
        return Path(config_path)


def _config_resource(render_kind: str):
    return as_file(files("layersense_controller.resources").joinpath(f"manim-{render_kind}.cfg"))


def _scene_path_relative_to_scenes_dir(scene_path: Path) -> Path:
    try:
        return scene_path.resolve().relative_to(settings.scenes_dir.resolve())
    except ValueError as exc:
        raise RenderError(
            f"scene path must be inside configured scenes_dir: {settings.scenes_dir}",
            "",
        ) from exc


def _scene_layout_parts(scene_path: Path) -> tuple[str, tuple[str, ...], str]:
    relative_scene = _scene_path_relative_to_scenes_dir(scene_path)

    parent_parts = relative_scene.parent.parts
    if not parent_parts:
        project = "_root"
        nested_parts: tuple[str, ...] = ()
    else:
        project = parent_parts[0]
        nested_parts = parent_parts[1:]

    return project, nested_parts, relative_scene.stem


def _raw_output_path(scene_path: Path, render_kind: str) -> Path:
    project, nested_parts, scene_name = _scene_layout_parts(scene_path)
    return (
        settings.artifacts_dir
        / "scenes"
        / project
        / render_kind
        / Path(*nested_parts)
        / f"{scene_name}_{render_kind}.mp4"
    )


def _output_file_path(scene_path: Path, render_kind: str) -> Path:
    project, nested_parts, scene_name = _scene_layout_parts(scene_path)
    return Path(project, render_kind, *nested_parts, f"{scene_name}_{render_kind}")


def _media_dir_path() -> Path:
    return settings.artifacts_dir / "scenes"


async def _run_manim(scene_path: Path, render_kind: str) -> Path:
    config_path = _config_file_path(render_kind)
    raw_output_path = _raw_output_path(scene_path, render_kind)
    output_file_path = _output_file_path(scene_path, render_kind)
    media_dir_path = _media_dir_path()
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_path.unlink(missing_ok=True)

    try:
        process = await asyncio.create_subprocess_exec(
            "manim",
            "render",
            "--config_file",
            str(config_path),
            "--media_dir",
            str(media_dir_path),
            "--format=mp4",
            "--output_file",
            output_file_path.as_posix(),
            str(scene_path),
            "GeneratedScene",
            cwd=PACKAGE_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise RenderError("failed to start manim process", str(exc)) from exc
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RenderError(f"manim exited with code {process.returncode}", stderr.decode())

    if not raw_output_path.exists():
        output = stdout.decode() + "\n" + stderr.decode()
        raise RenderError("Could not locate rendered .mp4 output.", output)

    return raw_output_path


async def render_preview(scene_path: Path, content_hash: str) -> Path:
    rendered_path = await _run_manim(scene_path, "preview")
    target = preview_artifact(content_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered_path, target)
    return target


async def render_final(scene_path: Path, content_hash: str) -> Path:
    rendered_path = await _run_manim(scene_path, "final")
    target = final_artifact(content_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered_path, target)
    return target
