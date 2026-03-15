from pathlib import Path

from layersense_controller.watcher import SceneFileHandler


def test_handle_ignores_non_python_files(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, json: dict[str, object], timeout: int) -> None:
        calls.append((url, json, timeout))

    monkeypatch.setattr("layersense_controller.watcher.httpx.post", fake_post)
    handler = SceneFileHandler()

    handler._handle("/tmp/demo.txt")

    assert calls == []


def test_handle_posts_render_payload_with_conversation_id(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object], int]] = []

    def fake_post(url: str, json: dict[str, object], timeout: int) -> None:
        calls.append((url, json, timeout))

    monkeypatch.setattr("layersense_controller.watcher.httpx.post", fake_post)
    handler = SceneFileHandler()
    scene_path = "/tmp/conversation_42.py"

    handler._handle(scene_path)

    assert calls == [
        (
            "http://localhost:8001/render",
            {"scene_path": scene_path, "conversation_id": "conversation_42"},
            5,
        )
    ]


def test_handle_strips_generated_prefix(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object], int]] = []

    def fake_post(url: str, json: dict[str, object], timeout: int) -> None:
        calls.append((url, json, timeout))

    monkeypatch.setattr("layersense_controller.watcher.httpx.post", fake_post)
    handler = SceneFileHandler()
    scene_path = str(Path("/tmp/generated_conv_99.py"))

    handler._handle(scene_path)

    assert calls[0][1]["conversation_id"] == "conv_99"
