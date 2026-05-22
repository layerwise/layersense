import layersense_controller.watcher as watcher_module
import pytest
from layersense_controller.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_scene_file_handler_posts_python_scene_changes(monkeypatch) -> None:
    """Post render requests for Python scene file events only."""
    posts: list[dict[str, object]] = []

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> None:
        posts.append({"url": url, "json": json, "timeout": timeout})

    monkeypatch.setattr(watcher_module.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "port", 8123)
    handler = watcher_module.SceneFileHandler()

    handler._handle("/tmp/generated_conversation.py")
    handler._handle("/tmp/notes.txt")

    assert posts == [
        {
            "url": "http://localhost:8123/render",
            "json": {
                "scene_path": "/tmp/generated_conversation.py",
                "conversation_id": "conversation",
            },
            "timeout": 5,
        }
    ]


def test_scene_file_handler_logs_failed_posts(monkeypatch, caplog) -> None:
    """Log and suppress render enqueue failures from watcher events."""

    def fail_post(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(watcher_module.httpx, "post", fail_post)

    handler = watcher_module.SceneFileHandler()
    handler._handle("/tmp/generated_conversation.py")

    assert "failed to enqueue render" in caplog.text


def test_scene_file_handler_ignores_directory_events(monkeypatch) -> None:
    """Ignore created and modified directory events."""
    handled: list[str] = []
    handler = watcher_module.SceneFileHandler()
    monkeypatch.setattr(handler, "_handle", handled.append)
    directory_event = type("Event", (), {"is_directory": True, "src_path": "/tmp/generated.py"})()
    file_event = type("Event", (), {"is_directory": False, "src_path": "/tmp/generated.py"})()

    handler.on_created(directory_event)
    handler.on_modified(directory_event)
    handler.on_created(file_event)
    handler.on_modified(file_event)

    assert handled == ["/tmp/generated.py", "/tmp/generated.py"]


def test_start_watcher_schedules_configured_scenes_dir(tmp_path, monkeypatch) -> None:
    """Start a watchdog observer against the configured scenes directory."""
    calls: list[tuple[str, object]] = []

    class FakeObserver:
        def schedule(self, handler: object, path: str, *, recursive: bool) -> None:
            calls.append(("schedule", path, recursive, type(handler).__name__))

        def start(self) -> None:
            calls.append(("start", None))

    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "scenes")
    monkeypatch.setattr(watcher_module, "Observer", FakeObserver)

    observer = watcher_module.start_watcher()

    assert isinstance(observer, FakeObserver)
    assert settings.scenes_dir.exists()
    assert calls == [
        ("schedule", str(settings.scenes_dir), False, "SceneFileHandler"),
        ("start", None),
    ]
