# Docs Hygiene Follow-Ups

Date: 2026-03-28

## Audited

- `README.md`
- `docs/ROADMAP.md`
- `AGENTS.md`
- `justfile`
- `docs/plans/2026-03-28-dev-stack-smoke-tests-design.md`
- `docs/plans/2026-03-28-dev-stack-smoke-tests-implementation-plan.md`
- `docs/plans/2026-03-22-stock-excalidraw-milestone-result.md`
- smoke-related and reliability-related plan docs under `docs/plans/`

## Patched Now

- Clarified in `README.md` that the repo now includes dedicated smoke tests, but the stack still has real render reliability gaps.
- Clarified in `README.md` that `just smoke` is intended to surface real runtime regressions, not merely act as a green-only happy-path check.
- Updated `docs/ROADMAP.md` to point collaborators at `just smoke` as the primary local verification path for the full generate -> render loop.
- Updated `docs/plans/2026-03-28-dev-stack-smoke-tests-design.md` so the controller and API E2E probe descriptions match the implemented websocket-driven terminal-state detection.
- Updated `docs/plans/2026-03-22-stock-excalidraw-milestone-result.md` to reflect that smoke-test infrastructure now exists, while runtime reliability is still an open issue.
- Updated `AGENTS.md` to match the actual `justfile` surface (`just smoke`, `just verify_workspace`) and removed stale Python-formatting guidance that referenced `cargo fmt`.

## Remaining Unresolved Issues

### todo-later: controller runtime reliability

The local smoke suite still exposes a real controller/runtime issue in deployed stacks unless the latest controller fix is rebuilt and redeployed.

Observed failure shape:

- controller emits `render_failed`
- error text: `Could not locate rendered .mp4 output.`
- stderr can still contain `File ready at '/app/media/videos/.../GeneratedScene.mp4'`

Status:

- code-level fix and regression tests exist locally in `layersense_controller/src/layersense_controller/render.py` and `layersense_controller/tests/test_render.py`
- this remains a runtime follow-up until the stack is rebuilt and verified with `just smoke`

### todo-later: agent-generated scene reliability

The API end-to-end smoke path can still fail because generated Manim scenes may be syntactically valid Python but still fail at runtime in Manim.

Observed failure classes in this session:

- `Text(...)` / SVG parse failures during render
- generated scene behavior that is acceptable as code but not robust as a render artifact

This is a product/runtime quality issue, not merely a docs issue.

### historical-keep: older plan docs

Several plan docs remain intentionally historical and should not be treated as current operational truth. They are still useful for rationale:

- `docs/plans/2026-03-16-frontend-stock-excalidraw-implementation-plan.md`
- `docs/plans/2026-03-16-desktop-workspace-layout-design.md`
- `docs/plans/2026-03-07-layersense-implementation-plan.md`

These should be kept, but collaborators should continue to treat `README.md` and `docs/ROADMAP.md` as the canonical entrypoints.

## Recommended Next Doc/Code Follow-Up

1. After the next controller redeploy, rerun `just smoke` and update `README.md` or the milestone-result doc if controller smoke turns green.
2. Once the agent-generated scene runtime quality improves, add a short note describing which smoke checks are now expected to pass consistently.
3. If `layersense_scenes/` continues to play a dual role as editable code and generated artifact store, document that explicitly in a dedicated design note rather than leaving it implicit across README and plans.
