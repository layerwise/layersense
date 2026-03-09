import asyncio
import re
import shutil
from pathlib import Path

from layersense_controller.cache import final_artifact
from layersense_controller.cache import preview_artifact
from layersense_controller.config import settings


class RenderError(Exception):
    def __init__(self, message: str, stderr: str) -> None:
        super().__init__(message)
        self.stderr = stderr


async def _run_manim(scene_path: Path, quality_flag: str) -> Path:
    process = await asyncio.create_subprocess_exec(
        "manim",
        "render",
        quality_flag,
        "--format=mp4",
        str(scene_path),
        "GeneratedScene",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RenderError(f"manim exited with code {process.returncode}", stderr.decode())

    output = stdout.decode() + "\n" + stderr.decode()
    return _parse_output_path(output, scene_path)


def _parse_output_path(manim_output: str, scene_path: Path) -> Path:
    match = re.search(r"File ready at '?([^\s']+\.mp4)'?", manim_output)
    if match:
        return Path(match.group(1))

    media_dir = settings.scenes_dir / scene_path.parent / "media"
    candidates = sorted(
        media_dir.rglob("GeneratedScene.mp4"), key=lambda path: path.stat().st_mtime
    )
    if candidates:
        return candidates[-1]

    raise RenderError("Could not locate rendered .mp4 output.", manim_output)


async def render_preview(scene_path: Path, content_hash: str) -> Path:
    rendered_path = await _run_manim(scene_path, "-ql")
    target = preview_artifact(content_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered_path, target)
    return target


async def render_final(scene_path: Path, content_hash: str) -> Path:
    rendered_path = await _run_manim(scene_path, "-qh")
    target = final_artifact(content_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rendered_path, target)
    return target
