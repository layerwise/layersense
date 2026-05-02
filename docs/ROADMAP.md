# LayerSense Roadmap

LayerSense aims to bridge the visual creativity of Excalidraw with the precise, mathematical control of Manim, using AI as the translator between sketches, prompts, and runnable animation code.

This file is the docs entrypoint for collaborators. It gives a fast overview of the vision, current project state, and where to read next depending on what you need.

## Current Status

- The project is still early-stage, but the core architecture is now documented and partially implemented.
- The backend services (`layersense_agent`, `layersense_controller`) and a stock-Excalidraw frontend exist in the repo.
- The frontend interaction milestone is largely complete, and the agent now normalizes Excalidraw payloads into a typed internal scene contract, but the full end-to-end stack still needs reliability validation and hardening.

## Suggested Reading Order

1. Start with the architecture design to understand the intended product and system shape.
2. Read the end-to-end implementation plan to see the original build sequence across services.
3. Read the frontend integration and implementation plans to understand the current UI/app milestone.
4. Read the milestone result and hardening follow-ups to understand what is done, what is stale, and what should happen next.

## Docs Map

## Core Vision and Architecture

- `docs/superpowers/specs/2026-03-07-layersense-architecture-design.md`
  - Canonical vision and system design for LayerSense.
  - Read this first to understand the user journey, service boundaries, render flow, and major open questions.

- `docs/superpowers/specs/2026-03-07-layersense-implementation-plan.md`
  - Original end-to-end build plan spanning agent, controller, watcher, frontend, Docker, and live-stack `e2e` testing.
  - Best reference for how the full stack is intended to fit together, even where implementation has diverged.

## Frontend Milestone

- `docs/superpowers/specs/2026-03-16-frontend-stock-excalidraw-integration-plan.md`
  - Historical integration-level plan for using unmodified Excalidraw in the frontend.
  - Useful for milestone rationale, but parts of the active runtime contract have since moved from WebSocket events to HTTP render-job polling.

- `docs/superpowers/specs/2026-04-24-http-long-poll-taskiq-render-design.md`
  - Current design for the controller render-job contract.
  - Best reference for the active `POST /render` plus `GET /render-jobs/{job_id}` flow.

- `docs/superpowers/plans/2026-04-24-http-long-poll-taskiq-render.md`
  - Current implementation plan for the Redis-backed long-poll render migration.
  - Read this when working on controller worker behavior, polling UX, or compose/e2e alignment.

- `docs/superpowers/specs/2026-03-16-frontend-stock-excalidraw-implementation-plan.md`
  - Task-by-task implementation plan for the frontend milestone.
  - Useful when comparing what was planned versus what was actually shipped in the React app.

- `docs/superpowers/specs/2026-03-16-desktop-workspace-layout-design.md`
  - Historical design note for the desktop workspace layout pass.
  - Keep for rationale only; current UI behavior has evolved beyond this first-pass layout spec.

- `docs/superpowers/specs/2026-03-22-stock-excalidraw-milestone-result.md`
  - Summary of what the frontend stock-Excalidraw milestone achieved, plus an audit of completed and stale work.
  - Best quick catch-up document for someone joining after the recent frontend push.

## Hardening and Reliability Follow-Ups

- `docs/superpowers/specs/2026-03-09-controller-watcher-hardening-followups.md`
  - Deferred reliability work for the watcher/controller boundary.
  - Covers non-2xx handling, duplicate event suppression, and test robustness for environment-driven config.

- `docs/superpowers/specs/2026-03-09-layersense-hardening-followups.md`
  - Deferred hardening work for artifact cache behavior.
  - Covers content-hash validation, fuller cache-state test coverage, and optional streaming hash improvements.

## Testing Workflow

- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-design.md`
  - Canonical testing taxonomy rationale for `unit`, `integration`, `e2e`, and `ai`.
  - Best reference for how Python test categories are intended to differ.

- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-rollout.md`
  - Rollout plan for the current testing command surface and marker taxonomy.
  - Useful when reconciling README/`justfile` guidance with the historical April rollout work.

## How To Navigate Based On Task

- **You need product context:** start with `docs/superpowers/specs/2026-03-07-layersense-architecture-design.md`
- **You need full-stack implementation context:** read `docs/superpowers/specs/2026-03-07-layersense-implementation-plan.md`
- **You need frontend context:** read both `docs/superpowers/specs/2026-03-16-frontend-stock-excalidraw-integration-plan.md` and `docs/superpowers/specs/2026-03-16-frontend-stock-excalidraw-implementation-plan.md`
- **You need current Excalidraw payload hardening context:** read `docs/superpowers/specs/2026-04-24-excalidraw-model-specificity-design.md` and `docs/superpowers/plans/2026-04-24-excalidraw-model-specificity-implementation-plan.md`
- **You need current render-job flow context:** read `docs/superpowers/specs/2026-04-24-http-long-poll-taskiq-render-design.md` and `docs/superpowers/plans/2026-04-24-http-long-poll-taskiq-render.md`
- **You need current milestone status:** read `docs/superpowers/specs/2026-03-22-stock-excalidraw-milestone-result.md`
- **You are fixing reliability issues:** read the two `2026-03-09-*hardening-followups.md` files
- **You are working on test layout or commands:** read the two `2026-04-18-python-testing-taxonomy-*.md` docs
- **You are hardening the Excalidraw payload flow:** read `docs/superpowers/specs/2026-04-24-excalidraw-model-specificity-design.md`, `docs/superpowers/specs/2026-04-24-excalidraw-prompt-bypassing-design.md`, and the matching files under `docs/superpowers/plans/`

## Near-Term Focus

The likely next phase is not another UI-only pass, but a full-stack reliability phase:

- prove the full generate -> render -> preview/final loop in real service startup conditions
- use `just e2e` for host-driven live-stack verification and `just test-e2e` for reproducible assistant-driven full-suite verification
- keep the default proof-of-concept path frontend-triggered (`frontend -> /render -> controller job -> long-poll -> artifact playback`), while treating watcher-driven rerender as deferred follow-up work
- keep deterministic render fields, starting with Excalidraw `viewBackgroundColor`, out of the freeform prompt and in explicit render-option contracts
- keep Manim output layout explicit and storage-oriented under `layersense_artifacts/scenes/<project-or-_root>/<preview|final>/...`, with cache identity stored in `layersense_artifacts/cache/index.json` and browser access exposed through `/artifacts/by-hash/...` and `/artifacts/scenes/...` routes
- keep render-job state ephemeral in Redis and execute preview/final work in a dedicated controller Taskiq worker
- keep preview/final Manim config defaults package-owned inside `layersense_controller`, so Docker and local runs resolve the same installed config resources
- harden watcher/controller interactions and cache behavior
- improve failure-path handling and developer startup/testing ergonomics
- keep documentation aligned as the implementation catches up with the architecture
