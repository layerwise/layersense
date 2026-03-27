# LayerSense

LayerSense aims to bridge the visual creativity of Excalidraw with the precise, mathematical control of Manim, using AI to translate drawings and prompts into runnable animation code.

## Start Here

- Read `docs/ROADMAP.md` for the current project vision, doc map, and milestone status.
- Read `docs/plans/2026-03-07-layersense-architecture-design.md` for the canonical system design.

## Current Status

- `layersense_frontend/` contains a stock-Excalidraw React app with prompt input, generate flow, and preview/final render UI.
- `layersense_agent/` can accept animation requests and write generated Manim scene files.
- `layersense_controller/` can watch scenes, queue renders, cache artifacts, and broadcast render events.
- The full end-to-end workflow is partially implemented but still needs reliability validation and hardening before it should be treated as production-ready.

## Current Architecture

The project currently targets a simple local-developer architecture:

1. Browser frontend captures an Excalidraw scene snapshot and prompt.
2. `layersense_agent` generates Manim code and writes a scene file.
3. `layersense_controller` watches for scene file changes.
4. Controller renders preview/final artifacts and serves them over HTTP.
5. Frontend listens for render events over WebSocket and updates the player.

## What This Repo Is Not Yet

- Not a fully wired Docker-first stack.
- Not a multi-user distributed rendering system.
- Not a stable production deployment target.

Older README sections describing Redis/Celery workers and distributed rendering are intentionally removed because they no longer describe the current implementation path.
