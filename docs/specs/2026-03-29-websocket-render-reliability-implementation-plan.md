# Websocket Render Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the default local dev loop reliable by removing duplicate render triggers from the proof-of-concept path, keeping a persistent frontend websocket, and fixing artifact playback URLs.

**Architecture:** The frontend remains the only default `/render` trigger. The watcher code remains in place but is not auto-started in the controller lifespan. The frontend keeps one websocket connection alive across conversation changes and converts controller-relative artifact URLs into controller-qualified browser URLs.

**Tech Stack:** FastAPI, React, Vitest, pytest, Vite, WebSocket API

---

### Task 1: Frontend websocket regression tests

**Files:**
- Modify: `layersense_frontend/src/hooks/useRenderEvents.test.ts`
- Modify: `layersense_frontend/src/App.test.tsx`

**Step 1: Write the failing test**

- Add a hook test proving the websocket instance is not recreated when `conversationId` changes.
- Add an app test proving artifact URLs rendered in the video player use the controller base URL instead of bare `/artifacts/...`.

**Step 2: Run test to verify it fails**

Run: `bun run --cwd layersense_frontend test -- --run useRenderEvents.test.ts App.test.tsx`

Expected:
- websocket persistence test fails because the hook currently creates a new `WebSocket` on conversation changes
- artifact URL normalization test fails because the app currently renders relative URLs unchanged

**Step 3: Write minimal implementation**

- Update the hook to keep a persistent socket while still filtering by the latest active conversation.
- Update the app to normalize controller event URLs before storing preview/final URLs.

**Step 4: Run test to verify it passes**

Run: `bun run --cwd layersense_frontend test -- --run useRenderEvents.test.ts App.test.tsx`

Expected: PASS

### Task 2: Disable watcher auto-start in default controller flow

**Files:**
- Modify: `layersense_controller/src/layersense_controller/main.py`
- Test: `layersense_controller/tests/test_router.py`

**Step 1: Write the failing test**

- Add a controller app lifecycle test proving the default app does not start the watcher automatically.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`

Expected: FAIL because the current lifespan always starts the watcher

**Step 3: Write minimal implementation**

- Stop auto-starting the watcher in the default lifespan while leaving watcher code untouched.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`

Expected: PASS

### Task 3: Verify focused suites and repo docs alignment

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

**Step 1: Add doc updates if needed**

- Clarify that the default proof-of-concept path is frontend-triggered render queueing.
- Keep watcher framed as a deferred/manual-edit flow rather than the default loop.

**Step 2: Run focused tests**

Run: `bun run --cwd layersense_frontend test -- --run useRenderEvents.test.ts App.test.tsx`

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py layersense_controller/tests/test_websocket_manager.py layersense_controller/tests/test_render.py`

Expected: PASS

**Step 3: Run repo verification**

Run: `just lint`

Run: `just test`

Expected: PASS
