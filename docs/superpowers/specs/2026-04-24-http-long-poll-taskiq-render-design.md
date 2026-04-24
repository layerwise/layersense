# HTTP Long-Poll Taskiq Render Design

## Goal

Replace the frontend-to-controller WebSocket render-update path with an HTTP long-polling contract backed by Redis job state and a Taskiq worker, while preserving the current preview-first render UX and existing artifact/cache behavior.

## Decisions

1. `POST /render` remains the frontend entrypoint for render requests.
2. `POST /render` returns a new `job_id` and an initial job snapshot.
3. The frontend polls `GET /render-jobs/{job_id}` using true long-polling.
4. Render job lifecycle state is stored only in Redis.
5. Artifact files and the existing cache index remain the durable source of preview/final outputs.
6. Cached render hits short-circuit in the controller, but still create a completed job record so the frontend always uses the same `job_id` polling contract.
7. The worker runs one Taskiq task per render job and performs preview then final rendering sequentially.
8. The frontend-visible job model exposes phased progress, including preview availability before final completion.
9. The current watcher-driven manual-edit rerender path stays deferred and out of the runtime path.
10. The active WebSocket API is removed from the stack in this migration.
11. Long-poll wake-ups use explicit Redis pub/sub notifications tied to job version changes.
12. Page refresh recovery for in-flight jobs remains out of scope; `job_id` is the only public polling handle in this pass.

## Current Repo Context

- The current proof-of-concept browser loop is `frontend -> agent -> controller /render -> websocket -> artifact playback`.
- `layersense_controller.router` currently validates render requests, performs cache fast-path checks, starts a FastAPI background task, and broadcasts preview/final/failure events over `/ws`.
- `layersense_controller.render` already contains the sequential preview-then-final render pipeline and canonical artifact path logic.
- `layersense_frontend` currently depends on a persistent `useRenderEvents` WebSocket hook and applies event payloads directly into the UI state machine.
- The live stack `e2e` coverage in `tests/e2e/test_dev_stack_e2e.py` currently waits for terminal WebSocket events before checking artifact routes.
- The local compose stack currently omits Redis because the implemented path no longer uses it.

## Why

The repo wants to move away from transport-coupled browser updates and toward an explicit job model.

The current WebSocket path has a few structural downsides:

- It couples frontend state progression to a live socket connection instead of an explicit render-job resource.
- It makes black-box tests depend on event sequencing and socket behavior instead of polling a stable HTTP contract.
- It keeps render execution tied to the API process through FastAPI background tasks.
- It leaves no explicit broker-backed queue boundary for render work.

Moving to Redis + Taskiq + long-polling creates a clearer split:

- controller owns the HTTP contract and cache fast-path decisions
- worker owns render execution
- Redis owns ephemeral job lifecycle state
- artifact files and cache index remain the durable output source

## Recommended Approach

Adopt a controller-owned job store and Taskiq worker design.

- `POST /render` validates input, checks cache, creates a Redis-backed job record, and either marks it complete immediately or enqueues one Taskiq task.
- `GET /render-jobs/{job_id}` blocks until the job version changes or a timeout is reached, then returns the current job snapshot.
- A dedicated Taskiq worker service executes the existing preview->final pipeline in one task and updates Redis after each meaningful transition.

The long-poll design depends on explicit Redis notifications rather than request-handler busy waiting.

This is the smallest complete migration because it reuses the existing controller cache and render seams instead of redistributing responsibilities across new services.

## Architecture

### Service Topology

The local and `e2e` compose stacks should add two new services:

- `redis`: shared broker/state store for job state and Taskiq transport
- `controller-worker`: a dedicated Taskiq worker process using the `layersense_controller` package

### Runtime Dependencies

This migration introduces new hard runtime dependencies and they should be specified directly in `layersense_controller/pyproject.toml` rather than relying on workspace-root transitive availability.

The controller package should explicitly add:

- `fastapi`
- `uvicorn`
- `redis` with asyncio support
- `taskiq`
- a Redis-backed Taskiq broker package

The exact package names can be finalized during implementation, but the design requires:

- async Redis commands for API reads/writes
- Redis pub/sub support for long-poll wake-ups
- Redis-backed task enqueueing for the worker

### Runtime Configuration

`layersense_controller.config.Settings` should add explicit settings for the new runtime surface:

- Redis connection URL
- render-job TTL in Redis
- maximum allowed long-poll wait time
- default long-poll wait time if the client does not provide one

The API process and the worker should both consume the same Redis configuration.

The compose files should provide these settings explicitly for local dev and `e2e` runs.

The runtime flow becomes:

1. frontend posts prompt and scene payload to agent
2. agent writes generated scene file
3. frontend posts `scene_path` and `conversation_id` to controller `POST /render`
4. controller creates a render job and, on cache miss, enqueues a Taskiq task
5. frontend long-polls controller `GET /render-jobs/{job_id}`
6. worker renders preview then final and updates Redis job state
7. frontend updates the player from polled preview/final URLs

### Ownership Boundaries

- `layersense_controller.router`
  - remove `/ws`
  - keep `POST /render`
  - add `GET /render-jobs/{job_id}`
- new controller job-state module
  - Redis key layout
  - job serialization/deserialization
  - version increments
  - long-poll wait behavior
- new controller task-dispatch module
  - enqueue Taskiq render tasks from the API process
- new worker entrypoint/module in `layersense_controller`
  - execute preview then final rendering
  - persist phase transitions to Redis
- frontend API/hook layer
  - replace WebSocket subscription logic with long-polling

The watcher code remains in the repository but must stay out of the new runtime path.

## HTTP Contract

### `POST /render`

Request body remains:

```json
{
  "scene_path": "/layersense_artifacts/code/generated_<uuid>.py",
  "conversation_id": "<conversation-id>"
}
```

Response becomes job-oriented:

```json
{
  "job_id": "<uuid>",
  "job": {
    "job_id": "<uuid>",
    "conversation_id": "<conversation-id>",
    "status": "queued",
    "version": 1,
    "preview_url": null,
    "final_url": null,
    "error": null,
    "stderr": null
  }
}
```

Cache-hit behavior:

- controller still performs the cache fast-path synchronously
- controller creates a completed job record
- response includes `job_id` plus a completed snapshot with preview/final URLs
- no worker task is enqueued for fully cached hits

Cache-miss behavior:

- controller creates a queued job record
- controller enqueues one Taskiq task
- response includes `job_id` plus queued snapshot

### `GET /render-jobs/{job_id}`

Query parameters:

- `after_version`: optional integer version last seen by the client
- `wait_seconds`: optional long-poll timeout, bounded server-side

Recommended request shape:

`GET /render-jobs/{job_id}?after_version=3&wait_seconds=20`

Behavior:

- return `404` if `job_id` is unknown
- if current version is newer than `after_version`, return immediately
- otherwise block until the job version changes or timeout is reached
- if timeout is reached with no change, return the current snapshot with `200`

The endpoint is true long-polling rather than client-side interval polling.

### Long-Poll Wake-Up Mechanism

The API process must not implement long-polling as a tight Redis polling loop inside the request handler.

Use explicit Redis pub/sub for job wake-ups:

1. worker writes the updated job snapshot to Redis
2. worker increments the monotonic `version`
3. worker publishes a small notification message for that `job_id`
4. `GET /render-jobs/{job_id}` reads the current snapshot first
5. if `version` is already newer than `after_version`, the request returns immediately
6. otherwise the handler waits on the Redis pub/sub notification channel with a timeout
7. after wake-up or timeout, the handler re-reads and returns the current snapshot

Design constraints:

- do not depend on Redis keyspace notifications
- do not busy-wait in the request handler
- use async Redis client support in the API process
- treat pub/sub notifications as a wake-up signal only; the source of truth remains the Redis job snapshot

Whether the implementation uses one shared subscription manager or per-request short-lived subscriptions can be decided during implementation, but the spec requires pub/sub-based wake-ups rather than sleep-loop polling.

## Job State Model

The public job snapshot should expose:

- `job_id`
- `conversation_id`
- `status`
- `version`
- `preview_url | null`
- `final_url | null`
- `error | null`
- `stderr | null`

Recommended statuses:

- `queued`
- `preview_rendering`
- `waiting_for_final`
- `final_rendering`
- `succeeded`
- `failed`

Semantics:

- `queued`: job exists, worker has not started preview work
- `preview_rendering`: worker is actively rendering preview and no preview artifact is available yet
- `waiting_for_final`: preview exists, `preview_url` is available, final is not done yet
- `final_rendering`: worker is actively rendering final after preview availability has already been recorded
- `succeeded`: final exists, preview/final URLs are available
- `failed`: render pipeline failed, `error` is required, `stderr` included when available

Every meaningful state transition increments a monotonic integer `version`.

Preview availability must always produce its own version increment even if the job remains non-terminal.

The worker must publish a Redis notification after every state transition that increments `version`.

## Render Pipeline

The worker should reuse the existing sequential controller render logic rather than splitting preview/final into separate tasks.

Worker flow:

1. mark job `preview_rendering`
2. render preview if needed
3. store/update preview artifact metadata in the cache index
4. mark job `waiting_for_final` with `preview_url`
5. mark job `final_rendering`
6. render final if needed
7. store/update final artifact metadata in the cache index
8. mark job `succeeded` with preview/final URLs
9. on failure, mark job `failed` with `error` and `stderr`

This preserves the existing preview-first user experience while moving execution out of the API process.

## Cache Behavior

Existing cache rules remain intact:

- artifact durability stays in the artifact tree and cache index
- scene UUID mapping rules stay aligned with current generated-scene and non-generated-scene behavior
- stable artifact routes remain:
  - `/artifacts/by-hash/<content_hash>/preview`
  - `/artifacts/by-hash/<content_hash>/final`
  - `/artifacts/scenes/<scene_uuid>`
  - `/artifacts/scenes/<scene_uuid>?preview=true`

Only job lifecycle state moves to Redis.

Redis does not become the durable artifact registry.

## Frontend Behavior

The frontend should replace `useRenderEvents` with a long-poll hook.

Expected UI progression:

1. submit animation request to agent
2. queue render with controller
3. receive `job_id` and initial job snapshot
4. long-poll job status until preview is available
5. update preview player as soon as `preview_url` is present
6. continue long-polling until terminal state
7. update final player when `final_url` is present or show error on failure

The current app-level UX states can remain approximately the same:

- `queueing_render`
- `waiting_for_preview`
- `waiting_for_final`
- `complete`
- `error`

The main behavioral change is that progression is driven by polled job snapshots instead of pushed socket events.

This design does not attempt to recover in-flight jobs after a page refresh. If the browser loses the current `job_id`, it cannot resume polling that job in this migration.

## Error Handling

### Synchronous request errors

`POST /render` keeps the current synchronous validation behavior:

- `404` when the scene file is missing or is not a file
- `400` when the scene path is outside the configured `scenes_dir`

Redis or enqueue failures should fail fast at the API boundary instead of returning a fake queued job.

### Job-level failures

Worker failures are modeled as terminal job state, not transport errors.

Failure snapshot shape:

```json
{
  "job_id": "<uuid>",
  "conversation_id": "<conversation-id>",
  "status": "failed",
  "version": 5,
  "preview_url": "/artifacts/by-hash/<hash>/preview",
  "final_url": null,
  "error": "manim exited with code 1",
  "stderr": "..."
}
```

If preview completed before the failure, the job snapshot should preserve `preview_url`.

## Testing Strategy

### Controller unit tests

- replace WebSocket broadcast assertions with job snapshot assertions
- add coverage for:
  - cached-complete `POST /render` responses
  - queued `POST /render` responses
  - `GET /render-jobs/{job_id}` immediate return on newer version
  - `GET /render-jobs/{job_id}` timeout with no version change
  - worker-written preview-available intermediate states
  - worker failure snapshots
  - pub/sub-driven long-poll wake-up behavior without busy waiting
- keep existing artifact route and cache behavior tests

New assistant-authored Python tests must continue to use `unit` plus `ai` markers.

### Worker-focused tests

- test one-task preview->final state progression in order
- test preview-first availability before final completion
- test failure persistence of `error` and `stderr`

### Frontend tests

- replace `useRenderEvents` tests with polling-hook tests
- update `types.ts` and API tests for the new `POST /render` response contract with `job_id` plus job snapshot
- verify `App` transitions from queueing to preview wait to final wait to complete
- verify preview is shown before final completion
- verify failed job snapshots drive the error UI

### End-to-end tests

- remove WebSocket client usage entirely
- queue render via `POST /render`
- update `e2e` helper functions so `_queue_render` extracts `job_id` from the new response body
- replace the websocket terminal-event helper with HTTP polling helpers built around `GET /render-jobs/{job_id}`
- poll `GET /render-jobs/{job_id}` until terminal state
- keep artifact-route assertions once preview/final are available

### Verification

Required verification for the migration:

- focused Python unit tests for controller job state and worker behavior
- focused frontend tests for the polling hook and app flow
- `just lint`
- `just test`
- `just test-e2e` once compose changes are in place

## Documentation Changes

Update current-facing docs in the same rollout:

- `README.md`
  - replace WebSocket architecture language with HTTP long-polling + Redis/Taskiq worker language
  - update compose stack description to include Redis and worker
  - update `e2e` notes away from websocket terminology
- `docs/ROADMAP.md`
  - update current runtime-flow references that still describe `controller -> websocket`
- `AGENTS.md`
  - align runtime flow guidance with long-polling and worker-backed renders
- any current docs mentioning `/ws` as part of the active path

Historical specs that describe the old WebSocket implementation can remain as historical documents, but current-behavior docs must be updated.

The rollout should also document the new settings surface for Redis and long-poll timing.

## Risks And Tradeoffs

- Redis-backed long-poll state adds operational complexity compared with the current in-process background task path.
- Removing WebSockets now keeps the active path simpler, but it requires coordinated frontend, backend, `e2e`, and doc updates in one pass.
- Long-poll endpoints need careful timeout/version semantics to avoid request storms or ambiguous no-change responses.
- The watcher code staying in repo but out of runtime means docs must be explicit about it being deferred to avoid future drift.
- In-flight job recovery after page refresh remains unsolved in this pass because the contract is intentionally keyed only by `job_id`.

## Non-Goals

- Do not revive or redesign manual-edit watcher-triggered rerender in this migration.
- Do not persist job history durably outside Redis.
- Do not split preview and final into separate worker tasks.
- Do not preserve `/ws` for compatibility.
- Do not redesign stable artifact routes.
- Do not add `conversation_id`-based job lookup or recovery endpoints in this migration.
