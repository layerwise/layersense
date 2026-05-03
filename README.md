# LayerSense

LayerSense aims to bridge the visual creativity of Excalidraw with the precise, mathematical control of Manim, using AI to translate drawings and prompts into runnable animation code.

## Start Here

- Read `docs/ROADMAP.md` for the current project vision, doc map, and milestone status.
- Read `docs/superpowers/specs/2026-03-07-layersense-architecture-design.md` for the canonical system design.

## Current Status

- `layersense_frontend/` contains a stock-Excalidraw React app with prompt input, generate flow, and preview/final render UI.
- `layersense_agent/` accepts animation requests with a structured Excalidraw `scene` payload, normalizes it into a typed internal scene model, extracts allowlisted render options, and writes generated Manim scene files.
- `layersense_controller/` queues render jobs, stores ephemeral job state in Redis, applies explicit per-request render options, runs Manim renders through a Taskiq worker, and serves cached artifacts over stable HTTP routes.
- The full end-to-end workflow is partially implemented, and the repo now includes dedicated Python `e2e` tests for the live local stack, but real render reliability issues still remain before it should be treated as production-ready.

## Current Architecture

The project currently targets a simple local-developer architecture:

1. Browser frontend captures a structured Excalidraw `scene` snapshot and prompt.
2. `layersense_agent` normalizes the Excalidraw payload into a typed internal scene model, extracts allowlisted render options such as Excalidraw background color, then generates Manim code and writes a scene file.
3. Frontend explicitly queues a render with `layersense_controller`, including structured `render_options`, and receives a `job_id` plus initial job snapshot.
4. Controller short-circuits cached hits or enqueues one Taskiq job for preview then final rendering.
5. Frontend long-polls `GET /render-jobs/{job_id}` until preview/final artifacts are available.

The controller watcher code remains in the repo for future manual-edit rerender workflows, but it is not part of the default proof-of-concept browser loop.

Raw Manim scene renders now live under `./layersense_artifacts/scenes/<project-or-_root>/<preview|final>/...`.
The preview/final Manim config defaults are packaged inside `layersense_controller` itself under `src/layersense_controller/resources/`, so local and Docker runs use the same installed config resources instead of repo-root config files.
The controller now keeps a JSON cache index at `./layersense_artifacts/cache/index.json` and serves browser-facing artifacts through stable routes instead of duplicating top-level hash-named mp4 files. Artifact cache identity now includes both scene file content and normalized render options, so background-color overrides do not collide.

## Render Layout

The controller shells out to Manim with:

- packaged config defaults from `layersense_controller.resources`
- `--config_file <materialized packaged config path>`
- `--media_dir <artifacts_dir>/scenes`
- nested `--output_file` paths based on scene location

Example raw artifact tree:

```text
layersense_artifacts/
  cache/
    index.json
  scenes/
    generated_scenes/
      preview/
        generated_123_preview.mp4
      final/
        generated_123_final.mp4
    _root/
      preview/
        standalone_preview.mp4
```

The `scenes/` subtree is the canonical media layout. The cache index maps content hashes and semantic scene UUIDs to those canonical files.

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
- `layersense_controller` does not yet have a real integration suite, and repo-level Python verification still reflects that gap.

What we learned from the `layersense_agent` pass:

- `fastapi.testclient.TestClient(app)` is the right default shape for API-boundary integration tests in this repo.
- Splitting mocked-boundary and VCR-backed tests into separate modules keeps cassette churn isolated while preserving broad API coverage.
- Patching only the narrow external seam (`Runner.run`) is enough to exercise nearly all meaningful agent behavior without changing production code.
- Replay mode is practical when cassette-backed tests fail clearly on missing or mismatched recordings, while record mode stays an explicit refresh step.
- `layersense_agent` is a good fit for integration-heavy coverage because most of its behavior is reachable through one HTTP boundary and a small number of external seams.

Useful commands:

- `just test`: default repo verification for Python unit tests plus frontend tests
- `just test_python`: Python `unit` plus `integration` tests
- `just test_python_unit`: explicit Python `unit` selection
- `just test_python_integration`: Python `integration` tests in replay mode
- `just test_python_integration_refresh`: Python `integration` tests in record mode
- `just test_python_e2e`: Python `e2e` marker selection
- `just e2e`: black-box live-stack `e2e` tests against an already-running local stack
- `just test-e2e`: assistant-friendly ephemeral compose run of the full suite, including `e2e`

The detailed taxonomy rationale and rollout notes live in:

- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-design.md`
- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-rollout.md`

Notes:

- `just test_python_integration` and `just test_python_integration_coverage` now work with the current agent integration suite.
- `just test_python` is still blocked by `tests/test_python_test_taxonomy.py` until `layersense_controller/tests/integration/test_*.py` exists.
- `just test_python_integration_coverage` currently shows `100%` coverage across `layersense_agent/src/**` and exposes `layersense_controller` as the remaining backend integration gap.
- Export `OPENAI_API_KEY` in your shell before running `just docker`.
- The current compose stack requires Redis because render job state and Taskiq transport both depend on it.
- Shared host-mounted directories are used for scene and artifact exchange:
  - `./layersense_artifacts/code`
  - `./layersense_artifacts`
- Controller render requests must point at scene files inside the configured `layersense_scenes` directory.
- The cache index still uses file-based locking. In local Docker Desktop environments with shared host volumes, cache-index contention remains a known limitation until a Redis-backed cache-lock follow-up lands.

## Controller Outlook

The next backend hardening pass should focus on `layersense_controller/tests/integration/`.

Recommended first slice for another coding assistant:

1. Add at least one real integration module under `layersense_controller/tests/integration/` to unblock repo-level taxonomy verification.
2. Start with `TestClient(app)` coverage for the lowest-friction router behavior:
   - `GET /health`
   - `POST /render` validation and file-path rejection paths
   - `GET /render-jobs/{job_id}` not-found and wait-parameter behavior
   - artifact-route `404` and path-safety checks
3. Then add higher-value controller integration cases around the queue/cache boundary:
   - cached render short-circuiting in `/render`
   - job creation and job-store polling
   - `/artifacts/by-hash/...` and `/artifacts/scenes/...` serving existing cached outputs
4. Only after the API-path layer is stable, expand into worker/render-pipeline integration for `render_tasks.py`, `render.py`, and cache-index mutations.

The current coverage report from `just test_python_integration_coverage` makes the controller priorities clear: `router.py`, `cache.py`, `render.py`, `render_jobs.py`, `render_runtime.py`, and `render_tasks.py` are the main remaining sources of uncovered backend behavior.
