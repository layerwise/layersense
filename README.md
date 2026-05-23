# LayerSense

LayerSense aims to bridge the visual creativity of Excalidraw with the precise, mathematical control of Manim, using AI to translate drawings and prompts into runnable animation code.

## Start Here

- Read `docs/ROADMAP.md` for the current project vision, doc map, and milestone status.
- Read `docs/superpowers/specs/2026-03-07-layersense-architecture-design.md` for the canonical system design.

## Current Status

- `layersense_frontend/` contains a stock-Excalidraw React app with prompt input, generate flow, and preview/final render UI.
- `layersense_agent/` accepts animation requests with a structured Excalidraw `scene` payload, normalizes it into a typed internal scene model, and returns generated Manim source plus a source hash.
- `layersense_controller/` queues render jobs, stores ephemeral job state in Redis, persists render rows in SQLite, applies explicit per-request CLI flags, runs Manim renders through a Taskiq worker, and serves object-store artifacts over stable HTTP routes.
- `layersense_persistence/` owns the durable SQLite Project/Scene/Frame/Render schema, Alembic migrations, DTOs, and repository classes for the architecture migration.
- The full end-to-end workflow is partially implemented, and the repo now includes dedicated Python `e2e` tests for the live local stack, but real render reliability issues still remain before it should be treated as production-ready.

## Current Architecture

The project currently targets a simple local-developer architecture:

1. Browser frontend captures a structured Excalidraw `scene` snapshot and prompt.
2. `layersense_agent` normalizes the Excalidraw payload into a typed internal scene model and returns Manim source, embedding background configuration into the scene source when needed.
3. Frontend explicitly queues a render with `layersense_controller`, forwarding `source_code`, `content_hash`, and optional structured `cli_flags`, and receives a `job_id` plus initial job snapshot.
4. Controller writes source to the object store, short-circuits completed render rows whose blobs exist, or enqueues one Taskiq job for preview then final rendering.
5. Frontend long-polls `GET /render-jobs/{job_id}` until preview/final artifacts are available.

The controller watcher code remains in the repo for future manual-edit rerender workflows, but it is not part of the default proof-of-concept browser loop.

Render source and mp4 blobs now live under `./layersense_artifacts/storage/renders/<content_hash>/...`.
The preview/final Manim config defaults are packaged inside `layersense_controller` itself under `src/layersense_controller/resources/`, so local and Docker runs use the same installed config resources instead of repo-root config files.
The render table in SQLite replaces the old JSON cache index. Artifact cache identity includes generated scene source plus normalized controller CLI flags.

## Render Layout

The controller shells out to Manim from a per-render temp workdir with:

- packaged config defaults from `layersense_controller.resources`
- `--config_file <materialized packaged config path>`
- `--media_dir <render_workdir>/<render_id>/media`
- `--output_file preview|final`

Example object-store tree:

```text
layersense_artifacts/
  storage/
    renders/
      <content_hash>/
        source.py
        preview.mp4
        final.mp4
        manim.log
```

The object store is the canonical artifact layout. SQLite render rows map content hashes and scene ids to those canonical keys.

Current browser-facing artifact routes:

- `/artifacts/by-hash/<content_hash>/preview`
- `/artifacts/by-hash/<content_hash>/final`
- `/artifacts/scenes/<scene_uuid>`
- `/artifacts/scenes/<scene_uuid>?preview=true`

## What This Repo Is Not Yet

- Not a stable production Docker deployment target.
- Not a multi-user distributed rendering system.
- Not a stable production deployment target.

Older README sections describing Redis/Celery workers and distributed rendering are intentionally removed because they no longer describe the current implementation path.

## Local Docker Dev Stack

Start the local development stack with:

```bash
just docker
```

This starts:

- `frontend` at `http://localhost:3000`
- `agent` at `http://localhost:8000`
- `controller` at `http://localhost:8001`
- `redis` on the compose network for render jobs and Taskiq transport
- `controller-worker` on the compose network for background preview/final rendering

Run the dedicated `e2e` suite against an already-running local stack with:

```bash
just e2e
```

Run the browser-driven e2e smoke against an already-running local stack with:

```bash
just e2e_browser
```

Run the assistant-friendly reproducible end-to-end path with:

```bash
just test-e2e
```

This starts an ephemeral compose project built from `docker-compose.yml` plus `docker-compose.e2e.yml`. That project contains `frontend`, `agent`, `controller`, `redis`, `controller-worker`, and `e2e-runner` on a shared compose network, and the runner executes the full test suite including live-stack `e2e` tests.

Notes for `just test-e2e`:

- Store `OPENAI_API_KEY` in macOS Keychain under service `layersense-openai-api-key` before running it.
- One way to add or update that entry is:

```bash
security add-generic-password -U -a "$USER" -s "layersense-openai-api-key" -w "<your-openai-api-key>"
```

- `just test-e2e` loads the key automatically via `just _export-secrets`.
- The ephemeral compose project publishes the stack on `3901`, `8900`, and `8901` to avoid colliding with the default local dev stack ports.
- The `e2e-runner` talks to the services over the shared compose network by service name rather than via host-local ports.
- It is meant to give coding assistants a single command that does not depend on them inspecting an already-running local stack.

For containerized Python debugging in VS Code, start the stack with the debug overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up --build
```

That keeps the normal stack unchanged, and additionally exposes:

- `agent` debugpy on `localhost:5678`
- `controller` debugpy on `localhost:5679`

Then use the VS Code launch config `Attach: Full dev stack` to attach to both Python services.

Notes:

- `just e2e` is separate from `just test`.
- It probes the real local service chain at `localhost:3000`, `localhost:8000`, and `localhost:8001`.
- `just e2e_browser` drives the same stack through a real Chromium browser via Python Playwright.
- It is intended to surface real runtime regressions, so a failing `e2e` run can still indicate useful progress if it points at a concrete controller or agent bug.

## Testing Taxonomy

LayerSense uses four semantic Python pytest markers:

- `unit`: fast isolated tests
- `integration`: cassette-backed or other real boundary tests run outside the full live stack
- `e2e`: live-stack end-to-end tests
- `ai`: assistant-authored tests

Current authoritative state:

- `layersense_agent` now has a complete integration layer under `layersense_agent/tests/integration/` and currently reaches `100%` coverage for `layersense_agent/src/**` via integration tests alone.
- The agent integration suite is intentionally split by boundary type:
  - `test_base_api_endpoints.py`: `TestClient(app)` coverage for `/health` and `/info`
  - `test_animation_api_with_mocked_agent_runner.py`: API-boundary tests that patch only `Runner.run` and keep the rest of the FastAPI request path real
  - `test_animation_api.py`: VCR-backed API-boundary tests for the live model path and cassette replay
- `layersense_controller` now has a first integration slice under `layersense_controller/tests/integration/`.
- The controller integration suite is intentionally split by runtime boundary type:
  - `test_router_api.py`: `TestClient(app)` coverage for HTTP-facing controller behavior
  - `test_render_jobs_fakeredis.py`: Redis-like job-store coverage using `fakeredis`
  - `test_render_tasks_taskiq.py`: Taskiq dispatch coverage using `InMemoryBroker`

What we learned from the `layersense_agent` pass:

- `fastapi.testclient.TestClient(app)` is the right default shape for API-boundary integration tests in this repo.
- Splitting mocked-boundary and VCR-backed tests into separate modules keeps cassette churn isolated while preserving broad API coverage.
- Patching only the narrow external seam (`Runner.run`) is enough to exercise nearly all meaningful agent behavior without changing production code.
- Replay mode is practical when cassette-backed tests fail clearly on missing or mismatched recordings, while record mode stays an explicit refresh step.
- `layersense_agent` is a good fit for integration-heavy coverage because most of its behavior is reachable through one HTTP boundary and a small number of external seams.
- `layersense_controller` needs a broader integration toolset than VCR alone because its main boundaries are FastAPI routing, Redis-backed job state, and Taskiq dispatch.

Useful commands:

- `just test`: default repo verification for Python unit tests plus frontend tests
- `just db_migrate`: apply the `layersense_persistence` Alembic migrations to `./layersense_artifacts/db/layersense.sqlite`
- `just db_reset`: remove the local SQLite DB and re-run migrations
- `just test_python`: Python `unit` plus `integration` tests
- `just test_python_unit`: explicit Python `unit` selection
- `just test_python_integration`: Python `integration` tests in replay mode
- `just test_python_integration_coverage`: Python `integration` tests plus per-module runtime coverage gate; every reported module must be at least 95%
- `just test_python_integration_refresh`: Python `integration` tests in record mode
- `just test_python_e2e`: Python `e2e` marker selection
- `just e2e`: black-box live-stack `e2e` tests against an already-running local stack
- `just e2e_browser`: browser-driven live-stack smoke against an already-running local stack
- `just test-e2e`: assistant-friendly ephemeral compose run of the full suite, including `e2e`

The detailed taxonomy rationale and rollout notes live in:

- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-design.md`
- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-rollout.md`

Notes:

- `just test_python_integration` and `just test_python_integration_coverage` now work with the current agent and controller integration suites.
- `just test_python` now includes both backend packages in taxonomy verification because `layersense_controller/tests/integration/test_*.py` exists.
- `just test_python_integration_coverage` is the canonical integration coverage gate for Python changes; keep every changed runtime module at or above 95% integration coverage before handoff.
- Export `OPENAI_API_KEY` in your shell before running `just docker`.
- The current compose stack requires Redis because render job state and Taskiq transport both depend on it.
- Render artifacts are shared between controller API and worker through `./layersense_artifacts/storage`.
- Controller render requests carry `source_code` and `content_hash`; the agent no longer writes shared scene files.

## Controller Outlook

The next backend hardening pass should build on `layersense_controller/tests/integration/` rather than starting from scratch.

Recommended next slice for another coding assistant:

1. Decide whether the next boundary worth covering is real Redis integration or a minimal live-worker smoke layer.
2. If staying in-process, add coverage for behavior changes through the current integration tools rather than relying on unit coverage alone.
3. Treat `watcher.py` as optional unless the watcher flow becomes a first-class product path again.
4. Use the latest integration coverage report to choose between broker wiring, watcher coverage, and a real Redis/live-worker step.

The current coverage report from `just test_python_integration_coverage` is expected to pass the 95% per-module gate; any new runtime module should either be covered by integration tests or intentionally excluded from runtime coverage scope.
