from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytest
import requests
from requests import Response
from websockets.sync.client import connect as websocket_connect

pytestmark = [pytest.mark.e2e, pytest.mark.ai]

FRONTEND_BASE = "http://localhost:3000"
AGENT_BASE = "http://localhost:8000"
CONTROLLER_BASE = "http://localhost:8001"
CONTROLLER_WS_URL = "ws://localhost:8001/ws"
REQUEST_TIMEOUT_SECONDS = 10
ANIMATION_REQUEST_TIMEOUT_SECONDS = 30
RENDER_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 1
SCENE_PAYLOAD = {"elements": [], "appState": {}, "files": {}}
KNOWN_GOOD_SCENE = """from manim import Dot, FadeIn, Scene


class GeneratedScene(Scene):
    def construct(self):
        dot = Dot()
        self.play(FadeIn(dot))
        self.wait(0.1)
"""


def _frontend_base() -> str:
    return os.getenv("LAYERSENSE_E2E_FRONTEND_BASE", "http://localhost:3000")


def _agent_base() -> str:
    return os.getenv("LAYERSENSE_E2E_AGENT_BASE", "http://localhost:8000")


def _controller_base() -> str:
    return os.getenv("LAYERSENSE_E2E_CONTROLLER_BASE", "http://localhost:8001")


def _controller_ws_url() -> str:
    return os.getenv("LAYERSENSE_E2E_CONTROLLER_WS_URL", "ws://localhost:8001/ws")


def _repo_root() -> Path:
    override = os.getenv("LAYERSENSE_E2E_REPO_ROOT")
    if override:
        return Path(override)

    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return Path(__file__).resolve().parents[2]

    return Path(top_level)


def _scenes_dir() -> Path:
    override = os.getenv("LAYERSENSE_E2E_SCENES_DIR")
    if override:
        return Path(override)
    return _repo_root() / "layersense_artifacts" / "code"


def _get_json(url: str) -> requests.Response:
    return requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)


def _post_json(url: str, payload: dict[str, Any]) -> requests.Response:
    return requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)


def _request_with_boundary_failure(
    method: str,
    url: str,
    boundary: str,
    payload: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> Response:
    try:
        if method == "GET":
            return requests.get(url, timeout=timeout)
        if method == "POST":
            return requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        pytest.fail(f"{boundary} could not be reached at {url}: {exc}")

    raise AssertionError(f"unsupported request method: {method}")


def _assert_ok(response: requests.Response, boundary: str) -> None:
    assert (
        response.ok
    ), f"{boundary} failed with status {response.status_code}: {response.text[:500]}"


def _create_animation(prompt: str) -> dict[str, Any]:
    response = _request_with_boundary_failure(
        "POST",
        urljoin(_agent_base(), "/api/v1/animation"),
        "agent animation request",
        {"prompt": prompt, "scene": SCENE_PAYLOAD},
        timeout=ANIMATION_REQUEST_TIMEOUT_SECONDS,
    )
    _assert_ok(response, "agent animation request")

    body = response.json()
    assert "conversation_id" in body, f"agent response missing conversation_id: {body}"
    assert "scene_path" in body, f"agent response missing scene_path: {body}"
    return body


def _queue_render(scene_path: str, conversation_id: str) -> dict[str, Any]:
    response = _request_with_boundary_failure(
        "POST",
        urljoin(_controller_base(), "/render"),
        "controller render request",
        {"scene_path": scene_path, "conversation_id": conversation_id},
    )
    _assert_ok(response, "controller render request")

    body = response.json()
    assert body.get("status") in {
        "queued",
        "cached",
    }, f"controller render returned unexpected body: {body}"
    return body


def _content_hash_for_scene(scene_path: str) -> str:
    host_scene_path = _host_scene_path(scene_path)
    return hashlib.sha256(host_scene_path.read_bytes()).hexdigest()


def _scene_uuid_for_scene(scene_path: str, conversation_id: str | None = None) -> str:
    scene_name = Path(scene_path).stem
    if scene_name.startswith("generated_") and conversation_id:
        return conversation_id
    if scene_name.startswith("generated_"):
        generated_uuid = scene_name.removeprefix("generated_")
        if generated_uuid:
            return generated_uuid
    return scene_name


def _artifact_candidates(scene_path: str) -> tuple[str, str]:
    content_hash = _content_hash_for_scene(scene_path)
    return (
        urljoin(_controller_base(), f"/artifacts/by-hash/{content_hash}/preview"),
        urljoin(_controller_base(), f"/artifacts/by-hash/{content_hash}/final"),
    )


def _scene_artifact_candidates(
    scene_path: str, conversation_id: str | None = None
) -> tuple[str, str]:
    scene_uuid = _scene_uuid_for_scene(scene_path, conversation_id)
    return (
        urljoin(_controller_base(), f"/artifacts/scenes/{scene_uuid}"),
        urljoin(_controller_base(), f"/artifacts/scenes/{scene_uuid}?preview=true"),
    )


def _host_scene_path(scene_path: str) -> Path:
    scene_name = Path(scene_path).name
    host_scene_path = _scenes_dir() / scene_name
    assert (
        host_scene_path.exists()
    ), f"scene path returned by stack is not present in host-mounted scenes dir: {host_scene_path}"
    return host_scene_path


def _write_known_good_scene(filename: str) -> tuple[Path, str]:
    scenes_dir = _scenes_dir()
    scenes_dir.mkdir(parents=True, exist_ok=True)
    host_scene_path = scenes_dir / filename
    host_scene_path.write_text(KNOWN_GOOD_SCENE)
    return host_scene_path, f"/layersense_artifacts/code/{filename}"


@contextmanager
def _temporary_known_good_scene(filename: str) -> Any:
    host_scene_path, controller_scene_path = _write_known_good_scene(filename)
    try:
        yield host_scene_path, controller_scene_path
    finally:
        if host_scene_path.exists():
            host_scene_path.unlink()


@contextmanager
def _controller_events() -> Any:
    with websocket_connect(_controller_ws_url()) as websocket:
        yield websocket


def _wait_for_controller_terminal_event(websocket: Any, conversation_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
    last_event: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        message = websocket.recv(timeout=remaining)
        event = json.loads(message)

        if event.get("conversation_id") != conversation_id:
            continue

        last_event = event
        if event.get("type") in {"artifact_ready", "render_ready", "render_failed"}:
            return event

    pytest.fail(
        f"controller websocket terminal event not reached within timeout for {conversation_id}; "
        f"last_event={last_event}"
    )


def _wait_for_artifacts(
    scene_path: str, conversation_id: str | None = None
) -> tuple[str, str, str, str]:
    preview_url, final_url = _artifact_candidates(scene_path)
    scene_url, scene_preview_url = _scene_artifact_candidates(scene_path, conversation_id)
    deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS

    last_preview_status: int | None = None
    last_final_status: int | None = None
    last_scene_status: int | None = None
    last_scene_preview_status: int | None = None
    while time.monotonic() < deadline:
        scene_response = _request_with_boundary_failure(
            "GET", scene_url, "controller scene artifact request"
        )
        scene_preview_response = _request_with_boundary_failure(
            "GET", scene_preview_url, "controller scene preview artifact request"
        )
        preview_response = _request_with_boundary_failure(
            "GET", preview_url, "controller preview artifact request"
        )
        final_response = _request_with_boundary_failure(
            "GET", final_url, "controller final artifact request"
        )
        last_scene_status = scene_response.status_code
        last_scene_preview_status = scene_preview_response.status_code
        last_preview_status = preview_response.status_code
        last_final_status = final_response.status_code

        if (
            scene_response.ok
            and scene_preview_response.ok
            and preview_response.ok
            and final_response.ok
        ):
            return scene_url, scene_preview_url, preview_url, final_url

        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        "controller terminal artifact state not reached within timeout; "
        f"scene={last_scene_status}, scene_preview={last_scene_preview_status}, "
        f"preview={last_preview_status}, final={last_final_status}, scene_path={scene_path}"
    )


def test_frontend_root_serves_layersense_app_shell() -> None:
    response = _request_with_boundary_failure(
        "GET",
        urljoin(_frontend_base(), "/"),
        "frontend root request",
    )

    _assert_ok(response, "frontend root request")
    content_type = response.headers.get("content-type", "")
    assert (
        "text/html" in content_type
    ), f"frontend returned unexpected content type: {content_type}"
    assert '<div id="root"></div>' in response.text, "frontend root mount marker missing"
    assert (
        "/src/main.tsx" in response.text or "/assets/" in response.text
    ), "frontend app entrypoint marker missing"


def test_agent_accepts_scene_payload_and_writes_scene_file() -> None:
    health_response = _request_with_boundary_failure(
        "GET",
        urljoin(_agent_base(), "/health"),
        "agent health request",
    )
    _assert_ok(health_response, "agent health request")

    animation = _create_animation("Animate a simple circle moving right.")
    scene_path = _host_scene_path(animation["scene_path"])

    assert scene_path.exists(), f"agent returned missing scene path: {scene_path}"
    assert scene_path.is_file(), f"agent returned non-file scene path: {scene_path}"


def test_controller_render_emits_terminal_websocket_event_for_known_good_scene() -> None:
    health_response = _request_with_boundary_failure(
        "GET",
        urljoin(_controller_base(), "/health"),
        "controller health request",
    )
    _assert_ok(health_response, "controller health request")

    unique_scene_name = f"smoke_controller_scene_{uuid.uuid4().hex}.py"
    with _temporary_known_good_scene(unique_scene_name) as (_, controller_scene_path):
        with _controller_events() as websocket:
            _queue_render(controller_scene_path, "controller-smoke")
            event = _wait_for_controller_terminal_event(websocket, "controller-smoke")
            scene_url, scene_preview_url, preview_url, final_url = _wait_for_artifacts(
                controller_scene_path
            )

    assert event["type"] in {"artifact_ready", "render_ready", "render_failed"}
    if event["type"] == "render_failed":
        pytest.fail(f"controller failed to render known-good smoke scene: {event}")
    assert scene_url.startswith(urljoin(_controller_base(), "/artifacts/scenes/"))
    assert scene_preview_url.endswith("?preview=true")
    assert preview_url.endswith("/preview")
    assert final_url.endswith("/final")


def test_api_chain_generate_to_render_completes() -> None:
    animation = _create_animation("Generate and render a simple smoke test animation.")
    with _controller_events() as websocket:
        render_response = _queue_render(animation["scene_path"], animation["conversation_id"])
        event = _wait_for_controller_terminal_event(websocket, animation["conversation_id"])

    assert render_response["status"] in {"queued", "cached"}
    if event["type"] == "artifact_ready":
        scene_url, scene_preview_url, preview_url, final_url = _wait_for_artifacts(
            animation["scene_path"], animation["conversation_id"]
        )
        assert event["preview_url"].startswith("/artifacts/by-hash/")
        assert event["final_url"].startswith("/artifacts/by-hash/")
        assert scene_url.startswith(urljoin(_controller_base(), "/artifacts/scenes/"))
        assert scene_preview_url.endswith("?preview=true")
        assert preview_url.endswith("/preview")
        assert final_url.endswith("/final")
        return
    if event["type"] == "render_ready":
        scene_url, scene_preview_url, preview_url, final_url = _wait_for_artifacts(
            animation["scene_path"], animation["conversation_id"]
        )
        assert event["url"].startswith("/artifacts/by-hash/")
        assert scene_url.startswith(urljoin(_controller_base(), "/artifacts/scenes/"))
        assert scene_preview_url.endswith("?preview=true")
        assert preview_url.endswith("/preview")
        assert final_url.endswith("/final")
        return

    assert event["type"] == "render_failed"
    assert event.get("error"), f"render_failed event missing error: {event}"
