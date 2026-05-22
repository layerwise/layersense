import asyncio
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
Resolution = Annotated[str, StringConstraints(pattern=r"^\d+,\d+$")]


class CLIFlags(BaseModel):
    quality: Literal["l", "m", "h", "p", "k"] | None = None
    resolution: Resolution | None = None
    frame_rate: float | None = Field(default=None, gt=0)
    renderer: Literal["cairo", "opengl"] | None = None
    from_animation_number: str | None = None


class RenderError(Exception):
    def __init__(self, message: str, stderr: str) -> None:
        super().__init__(message)
        self.stderr = stderr


def _config_file_path(render_kind: str) -> Path:
    with _config_resource(render_kind) as config_path:
        return Path(config_path)


def _config_resource(render_kind: str):
    return as_file(files("layersense_controller.resources").joinpath(f"manim-{render_kind}.cfg"))


def _cli_args(cli_flags: CLIFlags | None) -> list[str]:
    if cli_flags is None:
        return []

    args: list[str] = []
    if cli_flags.quality is not None:
        args.extend(["-q", cli_flags.quality])
    if cli_flags.resolution is not None:
        args.extend(["-r", cli_flags.resolution])
    if cli_flags.frame_rate is not None:
        args.extend(["--fps", str(cli_flags.frame_rate)])
    if cli_flags.renderer is not None:
        args.extend(["--renderer", cli_flags.renderer])
    if cli_flags.from_animation_number is not None:
        args.extend(["-n", cli_flags.from_animation_number])
    return args


def _output_path(media_dir_path: Path, render_kind: str) -> Path:
    candidates = [
        media_dir_path / f"{render_kind}.mp4",
        media_dir_path / "videos" / "scene" / "1080p60" / f"{render_kind}.mp4",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


async def _run_manim(
    source_file_path: Path, render_kind: str, cli_flags: CLIFlags | None = None
) -> Path:
    media_dir_path = source_file_path.parent / "media"
    raw_output_path = media_dir_path / f"{render_kind}.mp4"
    nested_output_path = media_dir_path / "videos" / "scene" / "1080p60" / f"{render_kind}.mp4"
    media_dir_path.mkdir(parents=True, exist_ok=True)
    raw_output_path.unlink(missing_ok=True)
    nested_output_path.unlink(missing_ok=True)

    try:
        with _config_resource(render_kind) as config_path:
            process = await asyncio.create_subprocess_exec(
                "manim",
                "render",
                "--config_file",
                str(config_path),
                *_cli_args(cli_flags),
                "--media_dir",
                str(media_dir_path),
                "--format=mp4",
                "--output_file",
                render_kind,
                str(source_file_path),
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

    output_path = _output_path(media_dir_path, render_kind)
    if not output_path.exists():
        output = stdout.decode() + "\n" + stderr.decode()
        raise RenderError("Could not locate rendered .mp4 output.", output)

    return output_path


async def render_preview(
    source_file_path: Path, content_hash: str, cli_flags: CLIFlags | None = None
) -> Path:
    return await _run_manim(source_file_path, "preview", cli_flags)


async def render_final(
    source_file_path: Path, content_hash: str, cli_flags: CLIFlags | None = None
) -> Path:
    return await _run_manim(source_file_path, "final", cli_flags)
