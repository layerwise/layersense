# Dev Stack Smoke Tests Design

## Goal

Turn the current ad-hoc local stack probes into first-class smoke tests that can be run with `just smoke` against an already-running developer stack.

## Scope

- Add a dedicated Python smoke-test module under `tests/smoke/`.
- Mark the smoke tests with `pytest.mark.smoke`.
- Keep smoke execution separate from `just test`.
- Probe real deep application paths for frontend, agent, controller, and end-to-end API flow.
- Make failures diagnostic enough to show which service boundary broke.

## Non-Goals

- Do not start or stop Docker from the smoke tests.
- Do not add browser-driven Excalidraw automation in the first version.
- Do not fold smoke tests into the default unit/integration test suite.

## Placement

- Smoke tests live in `tests/smoke/test_dev_stack_smoke.py`.
- They are also marked with `@pytest.mark.smoke` for semantic filtering and future flexibility.
- `just smoke` runs the smoke suite by explicit path so root `testpaths` can stay optimized for the default suite.

## Execution Model

- `just smoke` assumes the developer stack is already running on:
  - `http://localhost:3000`
  - `http://localhost:8000`
  - `http://localhost:8001`
- The tests are black-box probes against those endpoints.
- The suite remains opt-in because it depends on external running services and valid local runtime configuration.

## Smoke Coverage

### 1. Frontend App Shell Probe

- `GET /` on the frontend
- Assert HTTP success
- Assert expected app-shell markers in the returned HTML so the suite proves the actual frontend is serving, not just any 200 response

### 2. Agent Deep Probe

- Hit shallow `/health` first for quick diagnostics
- Then `POST /api/v1/animation` with a real canonical payload:
  - `prompt`
  - structured Excalidraw `scene`
- Assert:
  - success status
  - `conversation_id`
  - `scene_path`
  - generated scene file exists

This probe is intended to catch contract regressions like the earlier `422` failure.

### 3. Controller Deep Probe

- Hit `/health` first for quick diagnostics
- Use a known-good scene path
- `POST /render` with a real payload
- Assert `queued` or `cached`
- Wait for observable terminal state via controller WebSocket events, then verify artifact URLs when success events are emitted

This probe is intended to catch queueing paths that never produce artifacts or visible outcomes.

### 4. End-to-End API Probe

- Chain the real backend flow:
  1. create scene through agent
  2. queue render through controller
  3. wait for controller terminal WebSocket events and verify artifact URLs on success
- Keep this API-driven instead of browser-driven for the first version to reduce flakiness while still covering the deep failure paths that mattered in practice

## Test Design Principles

- Prefer one file unless helpers clearly reduce duplication.
- Prefer condition-based polling with a bounded timeout over fixed sleeps.
- Use clear assertion messages naming the failing boundary.
- Keep the suite lightweight and diagnostic, not exhaustive.
- Preserve real payload shapes so the smoke suite catches contract drift.

## Pytest Integration

- Add a `smoke` marker declaration in `pyproject.toml`.
- Keep default `testpaths` unchanged.
- Run smoke tests by explicit path from `just smoke`, not via the default `just test` flow.

## Justfile Integration

- Add `smoke` recipe to the root `justfile`.
- Recipe runs the dedicated smoke suite only.
- Keep it independent from `test`, `check`, and other default QA commands.

## Failure Reporting

- Failures should indicate whether the issue is:
  - frontend reachability/app shell
  - agent contract/generation
  - controller queueing
  - controller terminal render state
  - end-to-end API chaining

## Success Criteria

- `just smoke` runs only the dedicated smoke suite.
- The suite catches shallow service outages and the deeper request/render regressions we already encountered.
- The suite is stable enough for regular local use against a running Docker stack.
