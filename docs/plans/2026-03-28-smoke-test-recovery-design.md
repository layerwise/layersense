# Smoke Test Recovery Design

## Goal

Restore the local developer smoke path for two concrete failures discovered during end-to-end testing:

1. frontend -> agent request contract mismatch
2. controller queued render path not reaching an observable terminal state

This design intentionally targets the current local Docker developer flow, not a broader production architecture pass.

## Scope

- Make Excalidraw `scene` the canonical animation request payload.
- Define a compatible Pydantic request model for the agent API.
- Preserve the current agent response contract: `conversation_id`, `scene_path`.
- Fix the controller queued render path so successful renders populate artifacts and emit websocket events, and failures emit an explicit `render_failed` event.
- Add regression tests for both paths.

## Non-Goals

- No shared schema package between frontend and backend.
- No broader API redesign.
- No multi-user or production deployment work.
- No renderer feature expansion beyond restoring the smoke path.

## Design

### 1. Agent Request Contract

The canonical animation request becomes:

- `prompt: str`
- `scene: ExcalidrawSceneSnapshot`

`ExcalidrawSceneSnapshot` will be represented in the agent as a permissive Pydantic model with the current frontend envelope:

- `elements`
- `appState`
- `files`

The model should validate the envelope while avoiding over-modeling Excalidraw internals. `extra="ignore"` may be used where helpful to tolerate upstream noise and retain a stable contract.

The agent endpoint will serialize the validated `scene` model into JSON internally and append that JSON to the user prompt before invoking the LLM runner. This keeps the browser payload structured while preserving the existing internal prompt-building approach.

### 2. Frontend Alignment

The frontend already treats `scene` as the source of truth. The implementation should keep that flow and update only the TypeScript types or request helpers needed to align with the agent contract and improve error behavior if validation fails.

No browser-side stringification layer should be introduced.

### 3. Controller Queued Render Path

The controller issue is treated as a pipeline observability and completion problem: `/render` returns `queued`, but the system does not reliably produce artifacts or terminal websocket events.

The queued path should guarantee one observable terminal outcome for a valid request:

- cached artifacts -> broadcast `artifact_ready`
- uncached success -> broadcast `preview_ready` and `render_ready`
- uncached failure -> broadcast `render_failed`

The implementation should preserve the current `/render`, `/ws`, and `/artifacts/{filename}` API shapes.

### 4. Error Handling and Diagnostics

The controller should log enough information to make the queued pipeline diagnosable in real startup conditions:

- render start with `scene_path` and `conversation_id`
- preview render success and artifact target
- final render success and artifact target
- failure path with exception details

The failure path should not silently drop exceptions outside the current `RenderError` handling. Unexpected exceptions should still result in an observable error outcome for the client.

## Testing Strategy

### Agent

- Add or update tests proving `POST /api/v1/animation` accepts `prompt` + `scene`.
- Verify the scene payload is serialized into the downstream prompt input.
- Keep response assertions on `conversation_id` and `scene_path`.

### Frontend

- Add or update request helper tests proving `createAnimation()` posts the canonical `scene` payload.
- Keep the test focused on request shape, not implementation details.

### Controller

- Add regression coverage for cached render requests.
- Add regression coverage for uncached queued success, asserting terminal websocket events and artifact behavior.
- Add regression coverage for uncached queued failure, asserting `render_failed` emission.

## Risks

- Excalidraw payload shape may evolve; permissive modeling avoids turning that into a frequent backend break.
- Controller background task behavior can hide exceptions; broader exception handling must not swallow useful context.
- Logging should aid debugging without turning the happy path noisy.

## Success Criteria

- Browser Generate no longer fails with a 422 due to request shape mismatch.
- Agent accepts the canonical `scene` payload and returns a scene path.
- A valid `/render` request reaches an observable terminal state.
- Local smoke test reaches preview/final artifact delivery or an explicit failure event.
