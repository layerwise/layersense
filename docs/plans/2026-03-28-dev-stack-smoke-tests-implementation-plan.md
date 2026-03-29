# Dev Stack Smoke Tests Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-class Python smoke tests for the running local developer stack and expose them via `just smoke` without folding them into the default test suite.

**Architecture:** The smoke suite lives under `tests/smoke/` and runs as black-box pytest probes against the already-running frontend, agent, and controller on localhost. It covers both shallow reachability and the deeper agent/controller/end-to-end API paths that previously failed in ad-hoc testing.

**Tech Stack:** Python, pytest, requests, just, FastAPI services, Docker Compose

---

### Task 1: Create smoke test skeleton and marker plumbing

**Files:**
- Create: `tests/smoke/test_dev_stack_smoke.py`
- Modify: `pyproject.toml`

**Step 1: Write the failing test skeleton**

Add a tiny smoke test module with one marked test:

```python
import pytest


@pytest.mark.smoke
def test_placeholder() -> None:
    assert False
```

Add pytest marker config in `pyproject.toml`, for example under `tool.pytest.ini_options`:

```toml
markers = [
    "smoke: black-box smoke tests against a running local stack",
]
```

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -v`

Expected: FAIL on the placeholder assertion, with no unknown-marker warning.

**Step 3: Write minimal implementation**

Replace the placeholder with a real frontend-root smoke test only after confirming the red failure.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -v`

Expected: PASS for the first real smoke test.

**Step 5: Commit**

Do not commit unless asked.

### Task 2: Add frontend app-shell smoke probe

**Files:**
- Modify: `tests/smoke/test_dev_stack_smoke.py`

**Step 1: Write the failing test**

Add a marked test that requests `http://localhost:3000/` and asserts:
- status code is `200`
- response content type looks like HTML
- returned HTML contains expected app-shell markers such as `LayerSense Studio`

Use clear assertion messages that identify the frontend boundary.

**Step 2: Run test to verify behavior**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py::test_frontend_root_serves_layersense_app_shell -v`

Expected: PASS when the running stack is healthy; fail with boundary-specific messaging otherwise.

**Step 3: Refactor only if needed**

If repeated base URLs or request helpers appear, extract the smallest helper that improves readability.

### Task 3: Add agent deep smoke probe

**Files:**
- Modify: `tests/smoke/test_dev_stack_smoke.py`

**Step 1: Write the failing test**

Add a marked test that:
- requests `http://localhost:8000/health`
- posts canonical payload to `http://localhost:8000/api/v1/animation`

Canonical payload:

```python
{
    "prompt": "Animate a simple circle moving right.",
    "scene": {"elements": [], "appState": {}, "files": {}},
}
```

Assert:
- health endpoint succeeds
- animation request succeeds
- response includes `conversation_id`
- response includes `scene_path`
- returned scene path exists on disk

**Step 2: Run the focused test**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py::test_agent_accepts_scene_payload_and_writes_scene_file -v`

Expected: PASS if the live agent contract and generation path are healthy.

**Step 3: Keep diagnostics strong**

If the request fails, ensure assertion text names the agent boundary and includes status/body details.

### Task 4: Add controller deep smoke probe

**Files:**
- Modify: `tests/smoke/test_dev_stack_smoke.py`

**Step 1: Write the failing test**

Add a marked test that:
- requests `http://localhost:8001/health`
- uses a known-good scene path
- posts to `http://localhost:8001/render`
- accepts `queued` or `cached`
- polls for observable terminal state by checking artifact URLs or files until preview/final outputs are available

If possible, build the known-good scene path via a small helper shared with the agent deep probe or a dedicated local fixture scene.

**Step 2: Run the focused test**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py::test_controller_render_reaches_terminal_artifact_state -v`

Expected: PASS if the controller queueing and render completion path are healthy.

**Step 3: Use condition-based polling**

Implement bounded polling with a short interval and a clear timeout message. Do not use arbitrary long sleeps.

### Task 5: Add end-to-end API smoke probe

**Files:**
- Modify: `tests/smoke/test_dev_stack_smoke.py`

**Step 1: Write the failing test**

Add a marked end-to-end test that chains:
1. agent animation creation
2. controller render queue request
3. polling for preview/final artifact readiness

Assert the full API chain reaches a terminal success state.

**Step 2: Run the focused test**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py::test_api_chain_generate_to_render_completes -v`

Expected: PASS if the stack is healthy end-to-end.

**Step 3: Keep it black-box**

Do not automate the browser for this first version. Stay at the HTTP/API boundary.

### Task 6: Add `just smoke`

**Files:**
- Modify: `justfile`

**Step 1: Write the failing contract for the recipe**

Add a `smoke` recipe stub that intentionally fails, for example:

```just
smoke:
    false
```

**Step 2: Run the recipe to verify it fails**

Run: `just smoke`

Expected: FAIL.

**Step 3: Replace with the real implementation**

Use a dedicated recipe that runs only the smoke suite, for example:

```just
smoke:
    uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke
```

Prefer explicit path plus marker even if redundant; it documents intent and guards collection scope.

**Step 4: Run the recipe to verify it passes**

Run: `just smoke`

Expected: PASS against a healthy running stack.

### Task 7: Document smoke-test usage

**Files:**
- Modify: `README.md`

**Step 1: Add minimal usage docs**

Document that:
- `just smoke` targets an already-running local stack
- it is separate from `just test`
- it probes the real local service chain at `localhost:3000`, `localhost:8000`, and `localhost:8001`

**Step 2: Keep docs minimal**

Do not add a long testing guide. Add only the minimum operational guidance needed.

### Task 8: Verify the full smoke-test integration

**Files:**
- Verify only

**Step 1: Run the smoke suite directly**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -v`

Expected: PASS.

**Step 2: Run the recipe**

Run: `just smoke`

Expected: PASS.

**Step 3: Run required repo verification**

Run: `just lint`

Expected: exit `0`.

**Step 4: Run required repo verification**

Run: `just test`

Expected: existing suite still passes and does not accidentally run the smoke tests.
