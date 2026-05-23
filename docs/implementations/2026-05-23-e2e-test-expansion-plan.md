# E2E Test Expansion Plan

Date: 2026-05-23

## Context

Step 3 changed the live generate/render contract from shared `scene_path` files and `cache.py` to:

1. frontend → agent: `POST /api/v1/animation` with prompt + Excalidraw scene
2. agent → frontend: `{ conversation_id, source_code, content_hash }`
3. frontend → controller: `POST /render` with `{ conversation_id, source_code, content_hash, cli_flags? }`
4. controller/worker: source and render blobs live under ObjectStore keys `renders/{content_hash}/...`; render identity is `sha256(source_bytes + canonical(cli_flags_json))`
5. frontend long-polls `GET /render-jobs/{job_id}` and plays `/artifacts/by-hash/...` URLs

Current `tests/e2e/test_dev_stack_e2e.py` is a good live-stack API smoke suite, but it is still mostly HTTP-level. It proves the backend chain works, not that the browser-visible workflow works.

This plan adds a small e2e layer around the highest-risk cross-service/browser surfaces introduced by the contract split and ObjectStore/SQLite reuse path.

---

## Goals

- Prove the real frontend can drive the new raw-source generate → render → poll → video flow.
- Prove live long-poll transitions are browser-observable, not just mocked in Vitest.
- Prove completed render reuse works through the live stack after the cache-index deletion.
- Keep e2e count small; avoid turning e2e into schema/unit coverage.

## Non-goals

- Do not e2e-test object-store key formatting, SQLite row internals, or hash canonicalization.
- Do not e2e-test every 4xx/404 branch.
- Do not require Playwright for all e2e tests if API-level e2e is sufficient.
- Do not introduce legacy `scene_path` dual-shape support.

---

## Current coverage

`tests/e2e/test_dev_stack_e2e.py` currently covers:

1. `GET /` serves the frontend shell.
2. Agent health + `POST /api/v1/animation` returns `source_code` and source-only `content_hash`.
3. Controller health + known-good raw-source `POST /render` reaches terminal success and artifacts are available.
4. Full API chain `agent → controller → render job poll → artifact routes` succeeds.

That coverage is valuable and should remain. The gap is that no e2e test clicks through the real React app or observes browser video state.

---

## Test additions

### 1. Browser happy-path smoke

**Priority:** P0

**Surface:** frontend in a real browser, backed by the live local stack.

**Why:** `App.tsx`, `api.ts`, `useRenderJob`, and `VideoPlayer` are currently e2e-untested. The Step 3 contract break touched both frontend and backend; HTTP e2e can pass while the browser flow is broken.

**Suggested file:** `tests/e2e/test_browser_flow_e2e.py` if using pytest + Playwright, or `layersense_frontend/e2e/generate-render.spec.ts` if using Playwright Test.

**Flow:**

1. Open `LAYERSENSE_E2E_FRONTEND_BASE` defaulting to `http://localhost:3000`.
2. Fill the prompt textarea.
3. Click `Generate`.
4. Wait for render output video.
5. Wait until the video `src` points at a controller artifact URL.

**Assertions:**

- Generate button becomes disabled during submit/queue.
- A video element appears.
- Final video `src` starts with `http://localhost:8001/artifacts/by-hash/` or the configured controller base.
- No visible error text is shown.

**Notes:**

- Use the existing minimal Excalidraw default canvas if practical.
- If live LLM output is too slow/flaky, keep this as an e2e against the same running services but allow a deterministic agent fixture only if the stack already supports it. Do not add a hidden test-only API unless explicitly accepted.

---

### 2. Browser long-poll transition smoke

**Priority:** P1

**Surface:** frontend polling and video source switching.

**Why:** `useRenderJob` polling is central to UX and currently only unit-tested with mocks. The live job store, long-poll parameters, and browser state transitions can drift independently.

**Flow:**

1. Drive the browser happy path.
2. Observe the UI before preview, after preview, and after final.

**Assertions:**

- UI enters a waiting-for-preview state after queueing.
- Preview URL eventually appears before final URL when the job emits preview first.
- Video `src` updates from preview route to final route without a page refresh.
- Final state remains stable after one extra poll interval.

**Implementation note:**

This can be folded into Test 1 if the happy-path test already observes both transitions reliably. Keep it separate only if the transition assertions make the happy path too brittle.

---

### 3. Live render reuse / cache-hit smoke

**Priority:** P1

**Surface:** controller API + worker/ObjectStore/SQLite. Browser optional.

**Why:** deleting `cache.py` moved reuse into `Render` rows plus ObjectStore `head()` checks. Current live e2e proves a fresh render but not the short-circuit path.

**Suggested location:** existing `tests/e2e/test_dev_stack_e2e.py` as an API-level e2e.

**Flow:**

1. Submit known-good `source_code`, matching source-only `content_hash`, and fixed `cli_flags`.
2. Wait for success and record `preview_url`/`final_url`.
3. Submit the exact same source/hash/flags with a new `conversation_id`.
4. Read the returned job snapshot.

**Assertions:**

- Second response status is already `succeeded` or reaches terminal success without a full render wait.
- Second `preview_url` and `final_url` match the same by-hash routes as the first render.
- `/artifacts/scenes/{second_conversation_id}` resolves successfully.

**Anti-flake rule:**

Do not assert exact wall-clock duration unless necessary. Prefer asserting immediate completed snapshot shape if the implementation returns one on cache hit.

---

### 4. Browser-visible error path

**Priority:** P2

**Surface:** frontend error display and recovery.

**Why:** errors are currently covered by mocked Vitest. A live browser failure can differ because `api.ts` parses FastAPI errors and `App.tsx` normalizes thrown values.

**Preferred trigger:** deterministic controller 422 from a hash mismatch, but only if the browser can be made to send one without test-only hooks. Otherwise keep this as API/integration coverage and skip browser e2e for now.

**Assertions:**

- Error message is visible.
- No video is displayed.
- Generate button becomes enabled again.
- A subsequent valid request can proceed.

**Recommendation:**

Do not add backend-only invalid payload e2e. Existing unit/integration coverage is enough for raw 422 behavior. Add this only when there is a clean browser-level trigger.

---

### 5. Scene artifact route smoke

**Priority:** P2

**Surface:** `/artifacts/scenes/{conversation_id}` and `?preview=true` backed by `ScenesRepository.current_render_id`.

**Why:** by-hash routes are already exercised. Scene routes are backed by the new SQLite linkage and may remain user-facing until Step 4 removes `_default` shim behavior.

**Suggested location:** existing API e2e helper after a successful render.

**Assertions:**

- `/artifacts/scenes/{conversation_id}?preview=true` returns `200`, `video/mp4`, non-empty body.
- `/artifacts/scenes/{conversation_id}` returns `200`, `video/mp4`, non-empty body.
- Both continue to work after the job reaches final success.

**Lifecycle note:**

If Step 4 replaces `_default`/conversation-id routing with project/scene ids, update or delete this test in that same PR rather than preserving compatibility.

---

## Explicitly not e2e

Keep these in unit/integration tests:

- `POST /render` hash mismatch returns 422.
- Legacy `scene_path` payload returns 422.
- ObjectStore key helpers and atomic writes.
- SQLite row fields and repository behavior.
- CLI flag canonicalization and hash computation.
- Missing artifact 404s.
- Redis job-store long-poll edge cases.
- Worker failure branches unless the browser can trigger them cleanly.

---

## Proposed implementation sequence

### PR A: API e2e expansion, no browser harness

1. Add live cache-hit/reuse e2e to `tests/e2e/test_dev_stack_e2e.py`.
2. Strengthen existing artifact checks to assert `Content-Type` contains `video/mp4` and body is non-empty.
3. Add explicit scene-route assertions if not already covered by helper behavior.

**Verification:**

- `just e2e`
- `just test-e2e` if Docker time budget allows
- usual gates: `just lint`, `just test`, `just test_python_integration_coverage`

### PR B: Browser e2e harness

1. Add a Playwright e2e entrypoint.
2. Add browser happy-path smoke.
3. Add long-poll transition assertions if stable enough.
4. Wire a `just e2e_browser` or include browser test in `just e2e` only if runtime remains acceptable.

**Verification:**

- existing `just e2e`
- new browser e2e command
- usual gates

### PR C: Optional browser error path

Add only after there is a clean, deterministic frontend-visible failure trigger.

---

## Acceptance criteria

1. Existing `tests/e2e/test_dev_stack_e2e.py` still passes against the already-running local stack via `just e2e`.
2. A second identical known-good render proves the reuse path and returns the same by-hash artifact URLs.
3. Artifact responses asserted by e2e check status, media type, and non-empty body.
4. At least one browser-driven test proves clicking Generate results in a final playable video URL.
5. Browser e2e does not require direct agent/controller calls from the test body except for setup/cleanup helpers.
6. No e2e test asserts internal SQLite table contents or object-store file paths.
7. README/justfile documents any new browser e2e command.
8. `just lint`, `just test`, `just test_python_integration_coverage`, and `just e2e` pass before handoff.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Browser e2e is slow/flaky because live LLM generation is slow | Start with API-level reuse e2e; add browser happy path only if stack latency is acceptable, or introduce an explicit deterministic agent fixture after design approval. |
| Preview/final timing makes transition assertions flaky | Fold transition checks into happy path opportunistically; do not require observing preview if render is too fast. |
| Step 4 will replace `_default` and current scene routing | Mark scene-route test as Step-3-only and update/delete it in Step 4. |
| E2E suite grows too broad | Keep schema/error/cache internals in unit/integration; e2e only for browser-observable or cross-container behavior. |
| Cache-hit test accidentally reuses stale artifacts from previous runs | Use unique source text or fixed known-good source plus controlled cleanup. Prefer asserting behavior within the same test after a fresh first render. |
