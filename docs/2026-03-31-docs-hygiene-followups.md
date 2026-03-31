# Docs Hygiene Follow-Ups

Date: 2026-03-31

Supersedes: `docs/2026-03-28-docs-hygiene-followups.md`

## What Was Audited

- `README.md`
- `docs/ROADMAP.md`
- `docs/2026-03-28-docs-hygiene-followups.md`
- current controller render implementation
- current Manim config files
- historical architecture and milestone-result docs that still shaped contributor expectations

## What Was Patched

- Updated `README.md` to describe the explicit Manim-config-based render flow.
- Documented the split between raw scene renders under `layersense_artifacts/scenes/...` and cache-facing hashed artifacts under `layersense_artifacts/`.
- Documented that controller render requests must reference scene files inside the configured `layersense_scenes` directory.
- Updated `docs/ROADMAP.md` near-term focus to reflect the explicit artifact layout now used by the controller.
- Updated active Manim-config docs to reflect that preview/final config defaults are now packaged inside `layersense_controller`, not stored as repo-root runtime files.
- Marked the original March 7 render-path plan section as historical so it no longer reads like current implementation guidance.
- Added a concrete raw artifact tree example and a concise packaged Manim config contract section to `README.md`.
- Added a clear historical warning to `docs/plans/original_architecture_design.md`.
- Updated `docs/plans/2026-03-22-stock-excalidraw-milestone-result.md` so its next-step notes no longer describe watcher-first validation as the default loop.
- Consolidated the earlier 2026-03-28 docs follow-up report into this file.

## Remaining Stale Or Risky Items

- Several historical plans in `docs/plans/` still describe older artifact lookup behavior based on stdout parsing or generic `GeneratedScene.mp4` discovery. They are now safer because the most misleading sections are relabeled, but they still should not be treated as current implementation docs.

## Needs Code Or Product Decisions

- Decide whether the controller watcher should eventually emit rerenders into the same `layersense_artifacts/scenes/...` layout or a separate artifact class.
- Decide whether raw scene renders should remain durable indefinitely or become a cleanup-managed intermediate layer once stronger caching/retention policies exist.
