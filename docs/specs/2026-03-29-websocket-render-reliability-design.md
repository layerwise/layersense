# Websocket Render Reliability Design

## Goal

Make the local proof-of-concept loop reliable for the intended path: `frontend -> agent -> controller /render -> websocket -> artifact playback`.

## Decisions

1. The frontend is the authoritative trigger for render enqueueing in the default local dev flow.
2. The watcher code stays in the repo, but it must not be part of the default proof-of-concept render path.
3. The frontend should hold a persistent websocket connection instead of recreating it on `conversationId` changes.
4. Artifact URLs used by the browser must resolve against the controller origin, not the frontend origin.

## Why

The current stack has two main reliability problems.

- The controller watcher auto-enqueues renders for generated scene writes while the frontend also explicitly calls `/render`, creating duplicate jobs and duplicate websocket events.
- The frontend websocket hook rebuilds the socket when `conversationId` changes, which creates a race where fast cached events can be dropped before the new socket is active.

These issues make the proof-of-concept loop nondeterministic even when the core controller render pipeline works.

## Design

### Render Triggering

- Keep watcher implementation code intact.
- Stop starting the watcher automatically in the default controller app lifecycle.
- Preserve watcher as a deferred/manual-edit feature for later product work.

### Websocket Handling

- Open one websocket connection for the frontend hook lifecycle.
- Track the latest active `conversationId` without reconnecting.
- Filter incoming events using the current active conversation id in the message handler.

### Artifact URLs

- Normalize controller event URLs to controller-qualified URLs before giving them to the video player.
- This ensures browser playback targets `localhost:8001` where artifacts are actually served.

## Testing Strategy

- Add frontend regression tests first for persistent websocket behavior and artifact URL normalization.
- Keep controller tests focused on existing router/render behavior unless a code change requires more coverage.
- Verify the full repo with `just lint` and `just test` after focused tests pass.

## Non-Goals

- Do not remove watcher code.
- Do not implement the future manual-edit auto-rerender product path in this pass.
- Do not redesign websocket routing to be per-conversation subscriptions in this pass.
