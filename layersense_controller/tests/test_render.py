import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from layersense_controller.render import (
    RenderError,
    _config_file_path,
    _raw_output_path,
    render_final,
    render_preview,
)


@contextmanager
def fake_config_resource(base_dir: Path, filename: str):
    config_path = base_dir / filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[CLI]\nmedia_dir = ./layersense_artifacts/scenes\n")
    yield config_path


@pytest.mark.asyncio
async def test_render_preview_uses_preview_config_and_nested_output_file_for_project_scene(
    tmp_path, monkeypatch
):
    scene_path = tmp_path / "layersense_scenes" / "demo_project" / "shots" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)
    raw_output = _raw_output_path(scene_path, "preview")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_bytes(b"preview")

    captured_args: tuple[str, ...] | None = None
    captured_kwargs: dict[str, object] | None = None
    expected_raw_output = raw_output

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.write_bytes(b"preview")
            return (b"misleading stdout", b"misleading stderr")

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        nonlocal captured_kwargs
        captured_args = args
        captured_kwargs = kwargs
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    target = await render_preview(scene_path, "abc123")

    assert captured_args is not None
    assert captured_kwargs is not None
    assert "--config_file" in captured_args
    assert str(_config_file_path("preview")) in captured_args
    assert "--media_dir" in captured_args
    assert str(artifacts_dir / "scenes") in captured_args
    assert "--output_file" in captured_args
    assert "demo_project/preview/shots/scene_preview" in captured_args
    assert Path(captured_kwargs["cwd"]) == Path(__file__).resolve().parents[1]
    assert target == artifacts_dir / "abc123_preview.mp4"
    assert target.read_bytes() == b"preview"


@pytest.mark.asyncio
async def test_render_final_uses_final_config_and_root_fallback_output_file(tmp_path, monkeypatch):
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)
    raw_output = _raw_output_path(scene_path, "final")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_bytes(b"final")

    captured_args: tuple[str, ...] | None = None
    expected_raw_output = raw_output

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.write_bytes(b"final")
            return (b"misleading stdout", b"misleading stderr")

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        captured_args = args
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    target = await render_final(scene_path, "abc123")

    assert captured_args is not None
    assert "--config_file" in captured_args
    assert str(_config_file_path("final")) in captured_args
    assert "--output_file" in captured_args
    assert "_root/final/scene_final" in captured_args
    assert target == artifacts_dir / "abc123_final.mp4"
    assert target.read_bytes() == b"final"


@pytest.mark.parametrize("render_kind", ["preview", "final"])
def test_config_file_path_resolves_packaged_resource(render_kind):
    config_path = _config_file_path(render_kind)

    assert config_path.is_file()
    assert config_path.name == f"manim-{render_kind}.cfg"
    assert "layersense_controller" in str(config_path)


@pytest.mark.parametrize("render_kind", ["preview", "final"])
def test_render_config_files_use_artifact_rooted_media_paths(render_kind):
    config_path = _config_file_path(render_kind)
    config_text = config_path.read_text()

    assert "media_dir = ./layersense_artifacts/scenes" in config_text
    assert "video_dir = {media_dir}" in config_text
    assert "sections_dir = {video_dir}/sections" in config_text
    assert "partial_movie_dir = {video_dir}/partial_movie_files/{output_file}" in config_text
    assert "output_file =" in config_text
    assert "format = mp4" in config_text


@pytest.mark.parametrize("render_kind", ["preview", "final"])
def test_render_config_files_write_movie_to_render_raw_output_path(
    tmp_path, monkeypatch, render_kind
):
    config_path = _config_file_path(render_kind)
    temp_repo_root = tmp_path / "repo"
    temp_repo_root.mkdir()
    copied_config_path = temp_repo_root / config_path.name
    copied_config_path.write_text(config_path.read_text())

    scenes_dir = temp_repo_root / "layersense_scenes"
    scene_path = scenes_dir / "demo_project" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(
        "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        self.play(FadeIn(Dot()))\n"
    )

    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)
    monkeypatch.setattr(
        "layersense_controller.render.settings.artifacts_dir",
        temp_repo_root / "layersense_artifacts",
    )
    expected_raw_output = _raw_output_path(scene_path, render_kind)
    expected_raw_output.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "manim",
            "render",
            "--config_file",
            copied_config_path.name,
            "--media_dir",
            str(temp_repo_root / "layersense_artifacts" / "scenes"),
            "--format=mp4",
            "--output_file",
            f"demo_project/{render_kind}/scene_{render_kind}",
            scene_path.relative_to(temp_repo_root).as_posix(),
            "GeneratedScene",
        ],
        cwd=temp_repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert expected_raw_output.is_file()


@pytest.mark.asyncio
async def test_render_preview_uses_deterministic_raw_output_path(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    scene_path = tmp_path / "layersense_scenes" / "demo_project" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    monkeypatch.setattr(
        "layersense_controller.render.settings.scenes_dir", tmp_path / "layersense_scenes"
    )
    scene_path.write_text("print('x')\n")

    expected_raw_output = _raw_output_path(scene_path, "preview")
    expected_raw_output.parent.mkdir(parents=True, exist_ok=True)
    expected_raw_output.write_bytes(b"preview")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            expected_raw_output.write_bytes(b"preview")
            return (b"stdout without path", b"stderr without path")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    target = await render_preview(scene_path, "abc123")

    assert target.read_bytes() == b"preview"


@pytest.mark.asyncio
async def test_render_preview_rejects_scene_outside_configured_scenes_dir(tmp_path, monkeypatch):
    scenes_dir = tmp_path / "layersense_scenes"
    scene_path = tmp_path / "outside.py"
    scene_path.write_text("print('x')\n")
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("manim subprocess should not be started")

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fail_if_called,
    )

    with pytest.raises(RenderError, match="configured scenes_dir"):
        await render_preview(scene_path, "abc123")


def test_raw_output_path_distinguishes_same_basename_in_different_projects(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    path_a = _raw_output_path(scenes_dir / "project_a" / "scene.py", "preview")
    path_b = _raw_output_path(scenes_dir / "project_b" / "scene.py", "preview")

    assert path_a != path_b


def test_raw_output_path_uses_root_fallback_for_top_level_scene(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    raw_output = _raw_output_path(scenes_dir / "scene.py", "preview")

    assert raw_output == artifacts_dir / "scenes" / "_root" / "preview" / "scene_preview.mp4"


def test_raw_output_path_keeps_nested_directories_within_project(tmp_path, monkeypatch):
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr("layersense_controller.render.settings.scenes_dir", scenes_dir)

    raw_output = _raw_output_path(
        scenes_dir / "demo_project" / "shots" / "intro" / "scene.py", "preview"
    )

    assert (
        raw_output
        == artifacts_dir
        / "scenes"
        / "demo_project"
        / "preview"
        / "shots"
        / "intro"
        / "scene_preview.mp4"
    )


@pytest.mark.parametrize("render_kind", ["preview", "final"])
def test_render_config_files_use_output_file_to_isolate_partial_movie_dirs(render_kind):
    config_path = _config_file_path(render_kind)
    config_text = config_path.read_text()

    assert "partial_movie_dir = {video_dir}/partial_movie_files/{output_file}" in config_text


def test_config_file_path_does_not_depend_on_repo_root(monkeypatch, tmp_path):
    resource_dir = tmp_path / "resources"

    monkeypatch.setattr(
        "layersense_controller.render._config_resource",
        lambda render_kind: fake_config_resource(resource_dir, f"manim-{render_kind}.cfg"),
    )

    config_path = _config_file_path("preview")

    assert config_path == resource_dir / "manim-preview.cfg"


@pytest.mark.asyncio
async def test_render_preview_rejects_stale_preexisting_raw_output(tmp_path, monkeypatch):
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr("layersense_controller.render.settings.artifacts_dir", artifacts_dir)
    monkeypatch.setattr(
        "layersense_controller.render.settings.scenes_dir", tmp_path / "layersense_scenes"
    )

    stale_raw_output = _raw_output_path(scene_path, "preview")
    stale_raw_output.parent.mkdir(parents=True, exist_ok=True)
    stale_raw_output.write_bytes(b"stale")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"stdout without path", b"stderr without path")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(RenderError, match="Could not locate rendered .mp4 output"):
        await render_preview(scene_path, "abc123")


@pytest.mark.asyncio
async def test_render_preview_raises_on_nonzero_exit(tmp_path, monkeypatch):
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    monkeypatch.setattr(
        "layersense_controller.render.settings.scenes_dir", tmp_path / "layersense_scenes"
    )

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
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('x')\n")
    monkeypatch.setattr(
        "layersense_controller.render.settings.scenes_dir", tmp_path / "layersense_scenes"
    )

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise OSError("spawn failure")

    monkeypatch.setattr(
        "layersense_controller.render.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    with pytest.raises(RenderError, match="failed to start manim process") as exc_info:
        await render_preview(scene_path, "abc123")

    assert exc_info.value.stderr == "spawn failure"
