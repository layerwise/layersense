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

pytestmark = [pytest.mark.e2e, pytest.mark.ai]

REQUEST_TIMEOUT_SECONDS = 10
ANIMATION_REQUEST_TIMEOUT_SECONDS = 30
RENDER_TIMEOUT_SECONDS = 30
SCENE_PAYLOAD = {
    "elements": [
        {
            "id": "shape-1",
            "type": "rectangle",
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
            "angle": 0,
            "strokeColor": "#000000",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "opacity": 100,
        }
    ],
    "appState": {},
    "files": {},
}
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


def _request_with_boundary_failure(
    method: str,
    url: str,
    boundary: str,
    payload: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    params: dict[str, Any] | None = None,
) -> Response:
    try:
        if method == "GET":
            return requests.get(url, timeout=timeout, params=params)
        if method == "POST":
            return requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        pytest.fail(f"{boundary} could not be reached at {url}: {exc}")

    raise AssertionError(f"unsupported request method: {method}")


def _assert_ok(response: requests.Response, boundary: str) -> None:
    assert (
        response.ok
    ), f"{boundary} failed with status {response.status_code}: {response.text[:500]}"


def _assert_video_artifact_response(response: requests.Response, boundary: str) -> None:
    assert response.status_code == 200, (
        f"{boundary} failed with status {response.status_code}: " f"{response.text[:500]}"
    )
    content_type = response.headers.get("content-type", "")
    assert (
        "video/mp4" in content_type
    ), f"{boundary} returned unexpected content type: {content_type}"
    assert response.content, f"{boundary} returned an empty artifact body"


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
    assert "source_code" in body, f"agent response missing source_code: {body}"
    assert "content_hash" in body, f"agent response missing content_hash: {body}"
    return body


def _queue_render(
    source_code: str,
    content_hash: str,
    conversation_id: str,
    cli_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_code": source_code,
        "content_hash": content_hash,
        "conversation_id": conversation_id,
    }
    if cli_flags is not None:
        payload["cli_flags"] = cli_flags

    response = _request_with_boundary_failure(
        "POST",
        urljoin(_controller_base(), "/render"),
        "controller render request",
        payload,
    )
    _assert_ok(response, "controller render request")

    body = response.json()
    assert "job_id" in body, f"controller render returned unexpected body: {body}"
    assert "job" in body, f"controller render returned unexpected body: {body}"
    return body


def _wait_for_render_job(job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
    version = None
    last_job = None

    while time.monotonic() < deadline:
        params: dict[str, Any] = {}
        if version is not None:
            params["after_version"] = version
            params["wait_seconds"] = 5
        response = _request_with_boundary_failure(
            "GET",
            urljoin(_controller_base(), f"/render-jobs/{job_id}"),
            "controller render job request",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS + 5,
        )
        _assert_ok(response, "controller render job request")
        last_job = response.json()
        version = last_job["version"]
        if last_job["status"] in {"succeeded", "failed"}:
            return last_job

    pytest.fail(f"render job {job_id} did not reach a terminal state; last_job={last_job}")


def _completed_or_wait_for_render_job(render_response: dict[str, Any]) -> dict[str, Any]:
    job = render_response["job"]
    if job["status"] == "succeeded":
        return job
    return _wait_for_render_job(render_response["job_id"])


def _content_hash_for_source(source_code: str, cli_flags: dict[str, Any] | None = None) -> str:
    options_json = json.dumps(cli_flags or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source_code.encode() + options_json.encode()).hexdigest()


def _artifact_candidates(
    source_code: str, cli_flags: dict[str, Any] | None = None
) -> tuple[str, str]:
    content_hash = _content_hash_for_source(source_code, cli_flags)
    return (
        urljoin(_controller_base(), f"/artifacts/by-hash/{content_hash}/preview"),
        urljoin(_controller_base(), f"/artifacts/by-hash/{content_hash}/final"),
    )


def _scene_artifact_candidates(conversation_id: str) -> tuple[str, str]:
    return (
        urljoin(_controller_base(), f"/artifacts/scenes/{conversation_id}"),
        urljoin(_controller_base(), f"/artifacts/scenes/{conversation_id}?preview=true"),
    )


@contextmanager
def _temporary_known_good_scene(filename: str) -> Any:
    del filename
    yield KNOWN_GOOD_SCENE, hashlib.sha256(KNOWN_GOOD_SCENE.encode()).hexdigest()


def _wait_for_artifacts(
    source_code: str,
    conversation_id: str,
    preview_url: str | None = None,
    final_url: str | None = None,
    cli_flags: dict[str, Any] | None = None,
) -> tuple[str, str, str, str]:
    resolved_preview_url, resolved_final_url = (
        (preview_url, final_url)
        if preview_url is not None and final_url is not None
        else _artifact_candidates(source_code, cli_flags)
    )
    scene_url, scene_preview_url = _scene_artifact_candidates(conversation_id)
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
            "GET", resolved_preview_url, "controller preview artifact request"
        )
        final_response = _request_with_boundary_failure(
            "GET", resolved_final_url, "controller final artifact request"
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
            _assert_video_artifact_response(scene_response, "controller scene artifact request")
            _assert_video_artifact_response(
                scene_preview_response, "controller scene preview artifact request"
            )
            _assert_video_artifact_response(
                preview_response, "controller preview artifact request"
            )
            _assert_video_artifact_response(final_response, "controller final artifact request")
            return scene_url, scene_preview_url, resolved_preview_url, resolved_final_url

        time.sleep(1)

    pytest.fail(
        "controller terminal artifact state not reached within timeout; "
        f"scene={last_scene_status}, scene_preview={last_scene_preview_status}, "
        f"preview={last_preview_status}, final={last_final_status}, conversation_id={conversation_id}"
    )


def test_frontend_root_serves_layersense_app_shell() -> None:
    """Serve the LayerSense frontend application shell from the root route."""
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


def test_agent_accepts_scene_payload_and_returns_source() -> None:
    """Accept animation scene payloads and return generated source bytes."""
    health_response = _request_with_boundary_failure(
        "GET",
        urljoin(_agent_base(), "/health"),
        "agent health request",
    )
    _assert_ok(health_response, "agent health request")

    animation = _create_animation("Animate a simple circle moving right.")

    assert "class GeneratedScene" in animation["source_code"]
    assert (
        animation["content_hash"] == hashlib.sha256(animation["source_code"].encode()).hexdigest()
    )


def test_controller_render_completes_for_known_good_scene() -> None:
    """Render a known-good scene through the controller end-to-end path."""
    health_response = _request_with_boundary_failure(
        "GET",
        urljoin(_controller_base(), "/health"),
        "controller health request",
    )
    _assert_ok(health_response, "controller health request")

    unique_scene_name = f"smoke_controller_scene_{uuid.uuid4().hex}.py"
    with _temporary_known_good_scene(unique_scene_name) as (source_code, content_hash):
        cli_flags = {"quality": "m"}
        render_response = _queue_render(
            source_code,
            content_hash,
            "controller-smoke",
            cli_flags,
        )
        job = _wait_for_render_job(render_response["job_id"])
        scene_url, scene_preview_url, preview_url, final_url = _wait_for_artifacts(
            source_code,
            "controller-smoke",
            cli_flags=cli_flags,
        )

    assert job["status"] == "succeeded"
    assert job["preview_url"].startswith("/artifacts/by-hash/")
    assert job["final_url"].startswith("/artifacts/by-hash/")
    assert scene_url.startswith(urljoin(_controller_base(), "/artifacts/scenes/"))
    assert scene_preview_url.endswith("?preview=true")
    assert preview_url.endswith("/preview")
    assert final_url.endswith("/final")


def test_api_chain_generate_to_render_completes() -> None:
    """Complete the generate-to-render API chain across the live stack."""
    animation = _create_animation("Generate and render a simple smoke test animation.")
    render_response = _queue_render(
        animation["source_code"],
        animation["content_hash"],
        animation["conversation_id"],
        {},
    )
    job = _wait_for_render_job(render_response["job_id"])

    if job["status"] == "failed":
        pytest.fail(f"render job failed: {job}")

    scene_url, scene_preview_url, preview_url, final_url = _wait_for_artifacts(
        animation["source_code"],
        animation["conversation_id"],
        preview_url=urljoin(_controller_base(), job["preview_url"]),
        final_url=urljoin(_controller_base(), job["final_url"]),
        cli_flags={},
    )
    assert job["preview_url"].startswith("/artifacts/by-hash/")
    assert job["final_url"].startswith("/artifacts/by-hash/")
    assert scene_url.startswith(urljoin(_controller_base(), "/artifacts/scenes/"))
    assert scene_preview_url.endswith("?preview=true")
    assert preview_url.endswith("/preview")
    assert final_url.endswith("/final")


def test_controller_reuses_completed_render_for_identical_source_and_flags() -> None:
    """Reuse a completed render for identical source, source hash, and CLI flags."""
    cli_flags = {"quality": "m"}
    source_code = f"# cache reuse probe: {uuid.uuid4().hex}\n{KNOWN_GOOD_SCENE}"
    content_hash = hashlib.sha256(source_code.encode()).hexdigest()
    first_conversation_id = f"cache-reuse-first-{uuid.uuid4().hex}"
    second_conversation_id = f"cache-reuse-second-{uuid.uuid4().hex}"

    first_render_response = _queue_render(
        source_code,
        content_hash,
        first_conversation_id,
        cli_flags,
    )
    first_job = _wait_for_render_job(first_render_response["job_id"])
    if first_job["status"] == "failed":
        pytest.fail(f"first render job failed: {first_job}")

    _ = _wait_for_artifacts(
        source_code,
        first_conversation_id,
        preview_url=urljoin(_controller_base(), first_job["preview_url"]),
        final_url=urljoin(_controller_base(), first_job["final_url"]),
        cli_flags=cli_flags,
    )

    second_render_response = _queue_render(
        source_code,
        content_hash,
        second_conversation_id,
        cli_flags,
    )
    second_job = _completed_or_wait_for_render_job(second_render_response)
    if second_job["status"] == "failed":
        pytest.fail(f"second render job failed: {second_job}")

    assert second_job["status"] == "succeeded"
    assert first_job["preview_url"] == second_job["preview_url"]
    assert first_job["final_url"] == second_job["final_url"]
    assert second_job["preview_url"].startswith("/artifacts/by-hash/")
    assert second_job["final_url"].startswith("/artifacts/by-hash/")

    second_scene_url, second_scene_preview_url, second_preview_url, second_final_url = (
        _wait_for_artifacts(
            source_code,
            second_conversation_id,
            preview_url=urljoin(_controller_base(), second_job["preview_url"]),
            final_url=urljoin(_controller_base(), second_job["final_url"]),
            cli_flags=cli_flags,
        )
    )
    assert second_scene_url.endswith(f"/artifacts/scenes/{second_conversation_id}")
    assert second_scene_preview_url.endswith(
        f"/artifacts/scenes/{second_conversation_id}?preview=true"
    )
    assert second_preview_url.endswith("/preview")
    assert second_final_url.endswith("/final")
