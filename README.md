# LayerSense

LayerSense aims to bridge the visual creativity of Excalidraw with the precise, mathematical control of Manim, using AI to translate drawings and prompts into runnable animation code.

## Start Here

- Read `docs/ROADMAP.md` for the current project vision, doc map, and milestone status.
- Read `docs/plans/2026-03-07-layersense-architecture-design.md` for the canonical system design.

## Current Status

- `layersense_frontend/` contains a stock-Excalidraw React app with prompt input, generate flow, and preview/final render UI.
- `layersense_agent/` accepts animation requests with a structured Excalidraw `scene` payload and writes generated Manim scene files.
- `layersense_controller/` can watch scenes, queue renders, render Manim outputs with explicit config files, cache artifacts, and broadcast render events.
- The full end-to-end workflow is partially implemented, and the repo now includes dedicated smoke tests, but real render reliability issues still remain before it should be treated as production-ready.

## Current Architecture

The project currently targets a simple local-developer architecture:

1. Browser frontend captures a structured Excalidraw `scene` snapshot and prompt.
2. `layersense_agent` generates Manim code and writes a scene file.
3. Frontend explicitly queues a render with `layersense_controller`.
4. Controller renders preview/final artifacts and serves them over HTTP.
5. Frontend listens for render events over WebSocket and updates the player.

The controller watcher code remains in the repo for future manual-edit rerender workflows, but it is not part of the default proof-of-concept browser loop.

Raw Manim scene renders now live under `./layersense_artifacts/scenes/<project-or-_root>/<preview|final>/...`.
The preview/final Manim config defaults are packaged inside `layersense_controller` itself under `src/layersense_controller/resources/`, so local and Docker runs use the same installed config resources instead of repo-root config files.
Controller-served browser artifacts remain the cache-facing hashed files at `./layersense_artifacts/<hash>_preview.mp4` and `./layersense_artifacts/<hash>_final.mp4`.

## Render Layout

The controller shells out to Manim with:

- packaged config defaults from `layersense_controller.resources`
- `--config_file <materialized packaged config path>`
- `--media_dir <artifacts_dir>/scenes`
- nested `--output_file` paths based on scene location

Example raw artifact tree:

```text
layersense_artifacts/
  scenes/
    generated_scenes/
      preview/
        generated_123_preview.mp4
      final/
        generated_123_final.mp4
    _root/
      preview/
        standalone_preview.mp4
  abc123_preview.mp4
  abc123_final.mp4
```

The `scenes/` subtree is the raw Manim-owned layout. The top-level hashed files are the controller-facing cache artifacts served back to the browser.

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

Run the dedicated smoke suite against an already-running local stack with:

```bash
just smoke
```

For containerized Python debugging in VS Code, start the stack with the debug overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up --build
```

That keeps the normal stack unchanged, and additionally exposes:

- `agent` debugpy on `localhost:5678`
- `controller` debugpy on `localhost:5679`

Then use the VS Code launch config `Attach: Full dev stack` to attach to both Python services.

Notes:

- `just smoke` is separate from `just test`.
- It probes the real local service chain at `localhost:3000`, `localhost:8000`, and `localhost:8001`.
- It is intended to surface real runtime regressions, so a failing smoke run can still indicate useful progress if it points at a concrete controller or agent bug.

Notes:

- Export `OPENAI_API_KEY` in your shell before running `just docker`.
- Export `CODESTRAL_API_KEY` in your shell before running `just docker`
- The current compose stack intentionally omits Redis because the implemented local flow does not use it.
- Shared host-mounted directories are used for scene and artifact exchange:
  - `./layersense_artifacts/code`
  - `./layersense_artifacts`
- Controller render requests must point at scene files inside the configured `layersense_scenes` directory.
