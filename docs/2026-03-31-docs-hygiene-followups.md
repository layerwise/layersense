# Docs Hygiene Follow-Ups

## What Was Audited

- `README.md`
- `docs/ROADMAP.md`
- current controller render implementation
- current Manim config files

## What Was Patched

- Updated `README.md` to describe the explicit Manim-config-based render flow.
- Documented the split between raw scene renders under `layersense_artifacts/scenes/...` and cache-facing hashed artifacts under `layersense_artifacts/`.
- Documented that controller render requests must reference scene files inside the configured `layersense_scenes` directory.
- Updated `docs/ROADMAP.md` near-term focus to reflect the explicit artifact layout now used by the controller.

## Remaining Stale Or Risky Items

- Several historical plans in `docs/plans/` still describe older artifact lookup behavior based on stdout parsing or generic `GeneratedScene.mp4` discovery.
- No dedicated doc yet explains the exact Manim config contract (`manim-preview.cfg`, `manim-final.cfg`, `--media_dir`, nested `--output_file`) in one place.
- `README.md` still describes the local stack at a high level; it does not yet include a concrete example of the new raw artifact tree.

## Needs Code Or Product Decisions

- Decide whether the controller watcher should eventually emit rerenders into the same `layersense_artifacts/scenes/...` layout or a separate artifact class.
- Decide whether raw scene renders should remain durable indefinitely or become a cleanup-managed intermediate layer once stronger caching/retention policies exist.
