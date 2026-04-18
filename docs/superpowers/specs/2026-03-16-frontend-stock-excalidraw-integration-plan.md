# Frontend Stock Excalidraw Integration Plan

> This plan replaces any need to patch Excalidraw source code for the AI canvas workflow.

## Goal

Implement a production-ready frontend interaction flow where users draw in stock Excalidraw, submit a prompt, trigger generation, and receive preview/final render updates over WebSocket.

## Status

This milestone is largely implemented in `layersense_frontend/`, but the full end-to-end flow is not yet considered fully proven under default startup tooling. Treat this document as the intended integration contract for the frontend milestone, not proof that every runtime path is already reliable.

## Non-Goals

- No Excalidraw source code patching/forking.
- No custom in-Excalidraw "AI magic" button hacks.
- No backend API redesign beyond small compatibility shims if needed.

## Product Flow (User Journey)

1. User draws on the Excalidraw canvas.
2. User enters a prompt.
3. User clicks a frontend-owned `Generate` button.
4. Frontend reads current scene from Excalidraw API and calls agent endpoint.
5. Agent returns `conversation_id` + `scene_path`.
6. Frontend calls controller `/render` with `scene_path` and `conversation_id`.
7. Frontend listens to controller WebSocket for render events:
   - `artifact_ready` (cached preview+final)
   - `preview_ready`
   - `render_ready`
   - `render_failed`
8. Frontend updates player and status UI accordingly.

## Frontend Architecture

## 1) Component Boundaries

- `App` (orchestrator): owns prompt input, generation action, status state, and selected media URLs.
- `Canvas` component: wraps stock `<Excalidraw />`, exposes scene snapshot getter to parent.
- `VideoPlayer` component: renders preview/final/error state.
- `useRenderEvents` hook: manages WebSocket lifecycle and event parsing.
- `api.ts`: typed HTTP functions for agent + controller requests.

## 2) State Model

Use a simple explicit state machine in frontend state:

- `idle`
- `submitting_to_agent`
- `queueing_render`
- `waiting_for_preview`
- `waiting_for_final`
- `complete`
- `error`

State transitions are driven by API responses and WebSocket events only.

## 3) Excalidraw Integration Contract

Use stock Excalidraw APIs only:

- Capture API instance via `excalidrawAPI` callback.
- On `Generate`, read current scene data from API (elements/appState/files) and normalize payload.
- Optional `onChange` may be used for live dirty-state indication, but generation should rely on explicit snapshot-at-click.

This avoids race conditions from continuously streaming canvas changes while preserving deterministic generation payloads.

## API Contracts (Frontend Perspective)

## Agent Request

- `POST http://localhost:8000/api/v1/animation`
- Payload (frontend):
  - `prompt: string`
  - `scene: object` (Excalidraw JSON payload)
  - optional `conversation_id` when continuing same session
- Expected response:
  - `conversation_id: string`
  - `scene_path: string`

## Render Queue Request

- `POST http://localhost:8001/render`
- Payload:
  - `scene_path: string`
  - `conversation_id: string`
- Expected response:
  - `{ "status": "cached" }` or `{ "status": "queued" }`

## WebSocket Events

- `ws://localhost:8001/ws`
- Event envelope minimum:
  - `type: string`
  - `conversation_id: string`
- Supported event types:
  - `artifact_ready` with `preview_url` + `final_url`
  - `preview_ready` with `url`
  - `render_ready` with `url`
  - `render_failed` with `error` and optional `stderr`

Frontend must ignore events for other `conversation_id`s.

## Error Handling Plan

- Agent request failure: transition to `error`, show retry CTA, preserve prompt/canvas.
- Render queue failure: transition to `error`, show backend message.
- WebSocket disconnect before completion: reconnect strategy is still deferred; current implementation opens the socket eagerly and does not yet provide the full reconnect UX described here.
- `render_failed`: display concise error; richer `stderr` surfacing remains future work.

## UX Behavior Decisions

- Disable `Generate` while `submitting_to_agent` and `queueing_render`.
- Keep canvas interactive while rendering (user can continue drawing).
- Generation starts from click-time snapshot only.
- If user clicks `Generate` again, start a new `conversation_id` flow and replace active render subscription context.

## Testing Strategy

## Unit Tests

- `api.ts`: request/response mapping and error mapping.
- `useRenderEvents`: event parsing, conversation filtering, state callbacks.
- Canvas adapter: snapshot extraction from Excalidraw API.

## Component Tests

- App happy path: generate -> queued -> preview_ready -> render_ready.
- Cached path: `artifact_ready` sets both URLs immediately.
- Error path: agent fail and render_failed.

## Integration Smoke

- Run full stack using the currently documented manual startup flow (or future compose wiring), open frontend, generate from sample scene, verify preview then final playback.

## Implementation Sequence

1. Define frontend API client (`api.ts`) and response typing.
2. Implement `Canvas` with stock Excalidraw API capture + snapshot getter.
3. Implement App orchestration for prompt + generate flow.
4. Implement WebSocket hook and conversation filtering.
5. Implement VideoPlayer states and URL switching logic.
6. Add focused tests for state transitions and event handling.
7. Wire into Docker/frontend runtime flow (Task 14+).

Note: the original Docker-first assumption in this sequence is stale relative to the current repo. Runtime validation currently depends on manual service startup unless/until `docker-compose.yml` is brought back in sync with the implementation.

## Finalized Decisions

1. Generate click always starts a new conversation for this milestone.
2. Cancel render action is deferred.
3. Preview does not autoplay; playback starts on user interaction.

## Acceptance Criteria

- Frontend uses unmodified Excalidraw package.
- Clicking Generate sends correct scene+prompt payload to agent.
- Frontend successfully triggers controller render and receives events via WebSocket.
- Preview and final videos are displayed at the correct event times.
- Errors are visible and recoverable without page reload.

## Reality Check

The UI contract and most frontend code paths are implemented, but the overall claim "frontend flow is working" should currently be read as "implemented and test-covered in the frontend" rather than "fully validated across the live stack in all startup configurations."
