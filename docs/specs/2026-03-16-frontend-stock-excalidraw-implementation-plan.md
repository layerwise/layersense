# Frontend Stock Excalidraw Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a stock-Excalidraw frontend flow that snapshots canvas state on Generate, requests scene generation, queues render, and displays preview/final videos from controller events.

**Architecture:** Keep Excalidraw unmodified and own orchestration in React app code. Use a typed API layer for HTTP calls, a WebSocket hook for controller events, and an explicit UI state model in `App`. Generate always starts a new conversation for this milestone; cancel is deferred; preview waits for user click.

**Tech Stack:** React 19, TypeScript, Vite, `@excalidraw/excalidraw`, native `fetch`, browser `WebSocket`.

**Status:** Mostly implemented. Keep this document as a task-level historical plan and gap-analysis aid rather than a literal checklist of remaining work.

---

### Task 1: Add frontend API client and shared types

**Files:**
- Create: `layersense_frontend/src/types.ts`
- Create: `layersense_frontend/src/api.ts`
- Test: `layersense_frontend/src/api.test.ts` (Vitest)
- Modify: `layersense_frontend/package.json`

**Step 1: Write the failing test**

Add `layersense_frontend/src/api.test.ts` with tests for:
- `createAnimation(...)` sends `POST /api/v1/animation` and parses `conversation_id`, `scene_path`
- `queueRender(...)` sends `POST /render` and parses `{status}`
- both map non-2xx responses to thrown errors

**Step 2: Run test to verify it fails**

Run: `cd layersense_frontend && bun run test -- api.test.ts`
Expected: FAIL because test runner and `api.ts` do not exist yet.

**Step 3: Write minimal implementation**

Create `layersense_frontend/src/types.ts`:
- `AnimationRequest`, `AnimationResponse`
- `RenderQueueRequest`, `RenderQueueResponse`
- `RenderEvent` union (`artifact_ready`, `preview_ready`, `render_ready`, `render_failed`)

Create `layersense_frontend/src/api.ts`:
- `AGENT_BASE = "http://localhost:8000"`
- `CONTROLLER_BASE = "http://localhost:8001"`
- `createAnimation(payload)` via `fetch` to `${AGENT_BASE}/api/v1/animation`
- `queueRender(payload)` via `fetch` to `${CONTROLLER_BASE}/render`
- throw informative error on non-2xx

**Step 4: Run test to verify it passes**

Run: `cd layersense_frontend && bun run test -- api.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add layersense_frontend/src/types.ts layersense_frontend/src/api.ts layersense_frontend/src/api.test.ts layersense_frontend/package.json
git commit -m "feat(frontend): add typed API client for agent and controller"
```

---

### Task 2: Implement stock Excalidraw Canvas adapter

**Files:**
- Create: `layersense_frontend/src/components/Canvas.tsx`
- Create: `layersense_frontend/src/components/Canvas.test.tsx`
- Modify: `layersense_frontend/src/types.ts`

**Step 1: Write the failing test**

Add tests for `Canvas`:
- renders Excalidraw container
- exposes snapshot callback/value that includes current scene structure
- does not require patched Excalidraw APIs

Use module mocking for Excalidraw component if necessary.

**Step 2: Run test to verify it fails**

Run: `cd layersense_frontend && bun run test -- Canvas.test.tsx`
Expected: FAIL because component does not exist.

**Step 3: Write minimal implementation**

Create `Canvas.tsx`:
- Render `<Excalidraw />` from `@excalidraw/excalidraw`
- Capture API instance through `excalidrawAPI`
- Expose `getSceneSnapshot()` (via callback prop or ref) returning elements/appState/files from stock API
- Keep behavior deterministic: snapshot only when caller asks

**Step 4: Run test to verify it passes**

Run: `cd layersense_frontend && bun run test -- Canvas.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add layersense_frontend/src/components/Canvas.tsx layersense_frontend/src/components/Canvas.test.tsx layersense_frontend/src/types.ts
git commit -m "feat(frontend): add stock Excalidraw canvas adapter"
```

---

### Task 3: Implement render-event WebSocket hook

**Files:**
- Create: `layersense_frontend/src/hooks/useRenderEvents.ts`
- Create: `layersense_frontend/src/hooks/useRenderEvents.test.ts`
- Modify: `layersense_frontend/src/types.ts`

**Step 1: Write the failing test**

Add tests for hook behavior:
- connects to `ws://localhost:8001/ws`
- parses event messages
- ignores messages with different `conversation_id`
- emits callbacks for `artifact_ready`, `preview_ready`, `render_ready`, `render_failed`

**Step 2: Run test to verify it fails**

Run: `cd layersense_frontend && bun run test -- useRenderEvents.test.ts`
Expected: FAIL because hook does not exist.

**Step 3: Write minimal implementation**

Create hook with:
- params: active `conversationId` and event handlers
- single WebSocket connection lifecycle
- JSON parse with guard clauses
- conversation filter
- cleanup on unmount

**Step 4: Run test to verify it passes**

Run: `cd layersense_frontend && bun run test -- useRenderEvents.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add layersense_frontend/src/hooks/useRenderEvents.ts layersense_frontend/src/hooks/useRenderEvents.test.ts layersense_frontend/src/types.ts
git commit -m "feat(frontend): add websocket hook for render events"
```

---

### Task 4: Implement VideoPlayer component with click-to-play preview/final

**Files:**
- Create: `layersense_frontend/src/components/VideoPlayer.tsx`
- Create: `layersense_frontend/src/components/VideoPlayer.test.tsx`

**Step 1: Write the failing test**

Test component states:
- no media yet
- preview available (render video element but do not autoplay)
- final available (prefer final source)
- error state message visible

**Step 2: Run test to verify it fails**

Run: `cd layersense_frontend && bun run test -- VideoPlayer.test.tsx`
Expected: FAIL because component does not exist.

**Step 3: Write minimal implementation**

Create `VideoPlayer.tsx`:
- props: `previewUrl`, `finalUrl`, `error`, `status`
- choose source priority: `finalUrl ?? previewUrl`
- set `controls`, avoid autoplay
- display concise status and errors

**Step 4: Run test to verify it passes**

Run: `cd layersense_frontend && bun run test -- VideoPlayer.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add layersense_frontend/src/components/VideoPlayer.tsx layersense_frontend/src/components/VideoPlayer.test.tsx
git commit -m "feat(frontend): add video player for preview and final renders"
```

---

### Task 5: Replace Vite starter `App.tsx` with orchestration flow

**Files:**
- Modify: `layersense_frontend/src/App.tsx`
- Modify: `layersense_frontend/src/App.css`
- Create: `layersense_frontend/src/App.test.tsx`
- Modify: `layersense_frontend/src/main.tsx` (only if provider/test wiring needed)

**Step 1: Write the failing test**

Add integration-style app tests:
- Generate button disabled during submit/queue phases
- clicking Generate calls API with prompt + snapshot scene
- new conversation each click (current milestone decision)
- cached path updates media immediately
- queued path waits for websocket events to set preview/final
- render_failed shows error

**Step 2: Run test to verify it fails**

Run: `cd layersense_frontend && bun run test -- App.test.tsx`
Expected: FAIL with missing orchestration.

**Step 3: Write minimal implementation**

Replace starter app with:
- prompt textarea
- Generate button
- `Canvas` integration
- API calls (`createAnimation` then `queueRender`)
- explicit UI status enum
- `useRenderEvents` for event-driven updates
- `VideoPlayer` rendering

Apply UX decisions:
- Generate always starts new conversation
- no cancel action
- video does not autoplay

**Step 4: Run test to verify it passes**

Run: `cd layersense_frontend && bun run test -- App.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add layersense_frontend/src/App.tsx layersense_frontend/src/App.css layersense_frontend/src/App.test.tsx layersense_frontend/src/main.tsx
git commit -m "feat(frontend): orchestrate generate and render event flow"
```

---

### Task 6: Add frontend test tooling if missing (Vitest + RTL)

**Files:**
- Modify: `layersense_frontend/package.json`
- Create/Modify: `layersense_frontend/vitest.config.ts` (or `vite.config.ts` test section)
- Create: `layersense_frontend/src/test/setup.ts`

**Step 1: Write failing smoke test command step**

Run: `cd layersense_frontend && bun run test`
Expected: FAIL if test tooling is not configured.

**Step 2: Configure minimal test stack**

Add deps and scripts as needed:
- `vitest`
- `@testing-library/react`
- `@testing-library/jest-dom`
- `jsdom`

Add `test` script and setup file.

**Step 3: Re-run tests**

Run: `cd layersense_frontend && bun run test`
Expected: PASS for implemented tests.

---

### Task 7: Verify build and project-wide checks

**Files:**
- Modify only if fixes required from verification.

**Step 1: Frontend build verification**

Run: `cd layersense_frontend && bun run build`
Expected: PASS.

**Step 2: Frontend local run verification**

Run: `cd layersense_frontend && bun run dev -- --host 0.0.0.0`
Expected: Vite serves app.

Note: if validating browser requests against current backend CORS settings, prefer serving the frontend on port `3000` instead of Vite's default `5173`.

---

### Task 8: Documentation update and handoff

**Files:**
- Modify: `README.md` (frontend usage section)
- Modify: `docs/plans/2026-03-16-frontend-stock-excalidraw-integration-plan.md` (mark decisions finalized)

---

## Final Verification Checklist

Run in order before declaring complete:

1. `cd layersense_frontend && bun run test`
2. `cd layersense_frontend && bun run build`
3. `just lint`
4. `just test`

Expected: all green.

## Stale Assumptions In This Plan

- The plan assumes a straightforward Docker-first runtime path; current repo startup is still more manual.
- The plan predates the later desktop layout pass, including the now-collapsible sidebar.
- The plan should not be used as proof that the live full-stack workflow is already fully validated.

## Notes for Implementer

- Keep Excalidraw unpatched.
- Do not introduce regenerate/cancel functionality in this milestone.
- Keep API/event typing explicit; avoid `any` in event parsing paths.
- Prefer small commits per task as listed.
