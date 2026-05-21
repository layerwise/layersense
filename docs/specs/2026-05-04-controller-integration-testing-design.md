# Controller Integration Testing Design

## Goal

Add a first-class `layersense_controller` integration suite that complements the existing unit tests and matches the repo's current pytest taxonomy without forcing full Docker or live-worker coverage into the default integration loop.

The target outcome is a three-layer controller integration stack:

- `integration A`: FastAPI API-boundary tests with `TestClient`
- `integration B`: Redis-semantic tests with `fakeredis`
- `integration C`: Taskiq task-dispatch tests with `InMemoryBroker`

This pass intentionally defers real Redis, live Taskiq worker, and full compose-backed controller expansion.

## Current Repo Context

- `layersense_agent` already has a mature integration split under `layersense_agent/tests/integration/`.
- `layersense_controller` currently has only unit tests under `layersense_controller/tests/unit/`.
- Root pytest taxonomy already defines `unit`, `integration`, `e2e`, and `ai` in `pyproject.toml`.
- Root commands already include `just test_python_integration` for the shared `integration` marker.
- `tests/test_python_test_taxonomy.py` currently requires at least one integration module for both core Python packages.
- The controller runtime has multiple real seams that do not map well to VCR alone:
  - FastAPI routing and request validation
  - Redis-backed job state and pub/sub wakeups
  - Taskiq task dispatch and payload serialization
  - filesystem-backed cache and artifact lookups

## Problem Statement

The controller does not have the same testing shape as the agent because its most important boundaries are not limited to outbound HTTP. VCR is still useful for HTTP-backed integrations, but it does not validate the main controller contracts:

- render job snapshots persisted in Redis
- long-poll wakeups driven by pub/sub state changes
- Taskiq payload emission from `/render`
- Taskiq task execution and `RenderOptions` deserialization

If the controller integration suite copied the agent pattern too literally, it would over-index on HTTP and under-test the job store and worker boundary.

## Decision

Use a controller-specific three-part `integration` suite while keeping the existing unit suite unchanged:

1. `integration A`: `TestClient(app)` API-boundary tests
2. `integration B`: `fakeredis`-backed `RenderJobStore` tests
3. `integration C`: `InMemoryBroker` Taskiq tests

This keeps `integration` as the single repo taxonomy marker while allowing different backing tools per boundary type.

## Testing Pyramid

### `unit`

Keep the current controller unit tests as the fast inner loop.

- No `fakeredis` in `unit`
- No broker execution in `unit`
- Continue using monkeypatching and narrow fakes where appropriate

### `integration A`: FastAPI API Boundary

Use `fastapi.testclient.TestClient` with the real `layersense_controller.main.app`.

This layer should cover:

- `GET /health`
- `POST /render` validation and path rejection
- cached render short-circuit behavior
- `GET /render-jobs/{job_id}` not-found behavior and wait clamping
- artifact route 404 and path-safety behavior
- controller emission of the expected Taskiq payload from `/render`

This layer should use real temporary scene and artifact directories, but it should not require Redis, a worker, or Manim.

### `integration B`: Redis Semantics With `fakeredis`

Use async `fakeredis` to test `RenderJobStore` directly.

This layer should cover:

- queued job creation
- completed job creation
- version bumps on update
- publish-on-update behavior
- `wait_for_newer_version` immediate-return behavior
- `wait_for_newer_version` wakeup behavior after a version change
- missing-job behavior

This replaces the current hand-written fake Redis confidence with a standard emulator while staying lighter than real Redis.

### `integration C`: Taskiq With `InMemoryBroker`

Use `taskiq.InMemoryBroker` to exercise `run_render_job.kiq(...)` in process.

This layer should cover:

- Taskiq dispatch through `.kiq(...)`
- execution of the registered task rather than direct helper calls only
- payload deserialization into `RenderOptions`
- ordered preview/final state transitions
- failed-task mapping when preview or final rendering raises

This layer should patch render/cache/job-store seams so the task execution stays deterministic and does not invoke real rendering.

This layer is only a good fit while `run_render_job` remains independent of FastAPI dependency injection. If future controller tasks start depending on FastAPI-provided request or app-state dependencies, this test shape will need `taskiq_fastapi.populate_dependency_context(...)` or a different integration boundary.

## Boundary Separation

The most important design constraint is to keep the three integration layers from collapsing into each other.

### What belongs in `integration A`

- HTTP request and response behavior
- request validation
- route-level cache short-circuit behavior
- route-level wait parameter handling
- proof that `/render` emits the expected Taskiq payload

### What does not belong in `integration A`

- direct validation that Taskiq executes the task
- Redis pub/sub semantics
- detailed task state progression after dispatch

### What belongs in `integration C`

- proof that Taskiq dispatch executes the registered task in process
- proof that the task converts serialized payloads into the expected `RenderOptions`
- proof that the task updates job state in the right order

### What does not belong in `integration C`

- HTTP response assertions
- router validation and path rejection coverage

## File Layout

Create these new integration modules:

- `layersense_controller/tests/integration/test_router_api.py`
- `layersense_controller/tests/integration/test_render_jobs_fakeredis.py`
- `layersense_controller/tests/integration/test_render_tasks_taskiq.py`

Support changes:

- add `fakeredis` to the root development dependency group in `pyproject.toml`
- update `README.md` after the suite lands so the controller testing shape is documented accurately

Keep `layersense_controller/tests/conftest.py` minimal unless duplicate fixtures across the new modules become obvious.

## Verification Model

The implementation should verify in this order:

1. targeted module runs for each new integration file
2. `just test_python_integration`
3. `just lint`
4. `just test`

The end goal is for controller integration coverage to become a normal part of the shared repo integration loop rather than an outstanding taxonomy gap.

## Documentation Changes

`README.md` should be updated in the same change to reflect the new controller integration reality:

- controller no longer lacks an integration suite
- controller integration is intentionally broader than VCR because its key boundaries are Redis and Taskiq, not just HTTP
- the repo's integration taxonomy now includes:
  - VCR-backed HTTP tests where appropriate
  - `TestClient` app-boundary tests
  - `fakeredis` semantic integration tests
  - Taskiq `InMemoryBroker` integration tests

## Risks And Tradeoffs

- `fakeredis` is more truthful than a hand-written fake, but it is still not real Redis.
- Taskiq `InMemoryBroker` proves dispatch and task execution in process, but not live worker boot or cross-process delivery.
- Taskiq `InMemoryBroker` coverage becomes less truthful if controller tasks later depend on FastAPI-injected request or app-state dependencies.
- The deeper `/render` enqueue assertion requires careful patching so the test observes the payload at `run_render_job.kiq` without duplicating the entire task layer.
- If the boundary split is not enforced, `integration A` and `integration C` will become redundant and harder to maintain.

## Out Of Scope

- real Redis-backed controller integration
- live Taskiq worker smoke tests
- compose-backed controller expansion beyond existing `e2e`
- real Manim rendering inside integration tests
- introducing `fakeredis` into the `unit` suite

## Implementation Direction

Implement the controller integration pass in four small pieces:

1. add `fakeredis` to dev dependencies
2. add the `TestClient` router integration module
3. add the `fakeredis` job-store integration module
4. add the Taskiq `InMemoryBroker` integration module

Then update `README.md` so the testing taxonomy and controller status stay current.
