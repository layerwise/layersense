# 2026-04-06 Docs Hygiene Follow-Ups

## Audited

- `README.md`
- `docs/ROADMAP.md`
- `docs/2026-03-31-docs-hygiene-followups.md`
- `justfile`
- active smoke and verification commands already exercised during implementation:
  - `just lint`
  - `just test`
  - `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke -q`

## Patched Now

- Updated `README.md` to describe the implemented artifact model:
  - canonical media under `layersense_artifacts/scenes/...`
  - cache metadata under `layersense_artifacts/cache/index.json`
  - browser-facing routes under `/artifacts/by-hash/...` and `/artifacts/scenes/...`
- Updated `docs/ROADMAP.md` to stop describing top-level hashed mp4 files as the current browser/cache surface.
- Updated `docs/2026-03-31-docs-hygiene-followups.md` to reflect the indexed cache model.

## Historical Docs Left As Historical Context

- `docs/plans/2026-03-07-layersense-implementation-plan.md`
- `docs/plans/2026-03-29-manim-config-artifact-layout-implementation-plan.md`
- `docs/plans/2026-03-07-layersense-architecture-design.md`

These documents still mention the older top-level `<hash>_preview.mp4` / `<hash>_final.mp4` cache model in places. They appear to be historical design or implementation planning artifacts rather than the active source of truth, so they were not rewritten in this hygiene pass.

## Remaining Risks / TODO-Later

- If older plan docs continue to be referenced as current implementation truth, they should be relabeled more explicitly as historical or superseded.
- The non-generated/manual scene UUID story is intentionally provisional. Active docs should eventually describe the explicit reference UUID mechanism once that exists.
