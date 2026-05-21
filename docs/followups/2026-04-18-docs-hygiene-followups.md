# 2026-04-18 Docs Hygiene Follow-Ups

## What Was Audited

- `README.md`
- `docs/ROADMAP.md`
- `AGENTS.md`
- `docs/2026-03-31-docs-hygiene-followups.md`
- `docs/2026-04-06-docs-hygiene-followups.md`
- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-design.md`
- `docs/superpowers/specs/2026-04-18-python-testing-taxonomy-rollout.md`
- `justfile`
- `pyproject.toml`

## Verification Run

- `just verify_workspace`: passed
- `just lint`: failed because `black --check` wants to reformat `tests/e2e/test_dev_stack_e2e.py`
- `just test`: failed during collection because `tests/test_dev_stack_config.py` still imports the deleted path `tests/smoke/test_dev_stack_smoke.py`

## What Was Patched

- Updated `README.md` to:
  - point at the current canonical architecture doc path under `docs/superpowers/specs/`
  - replace stale "smoke tests" wording in the `just test-e2e` section with live-stack `e2e` wording
  - add a concise Python testing taxonomy and command reference aligned with the current `justfile`
- Updated `docs/ROADMAP.md` to:
  - add the April 18 testing taxonomy docs to the docs map
  - clarify when to use `just e2e` versus `just test-e2e`
- Updated `AGENTS.md` so the documented root `justfile` command surface now includes:
  - `test_python`
  - `test_python_unit`
  - `test_python_integration`
  - `test_python_integration_refresh`
  - `test_python_e2e`
  - `test-e2e`
- Fixed stale path references in the prior docs hygiene reports so they point at current `docs/` locations.
- Added historical framing to the April 18 testing taxonomy design and rollout docs so they do not read like the fastest source of current command truth.

## Historical Docs Kept As Historical

- older implementation and design specs under `docs/superpowers/specs/` that still discuss `smoke` terminology or old path layouts as part of their historical implementation context

These were not bulk-rewritten in this pass because they are planning artifacts, not the current onboarding entrypoints.

## Remaining Stale Or Risky Items

- Several historical specs still mention `smoke` as the old live-stack term. That is acceptable as historical context, but those files should not be treated as canonical contributor docs.
- Some older specs still mention `docs/plans/...` in examples or historical notes. They are lower-risk now that `README.md` and `docs/ROADMAP.md` point contributors at the canonical current paths.
- The documented verification commands are not all green on the rebased branch right now because of code/worktree drift:
  - `just test` is blocked by a stale import in `tests/test_dev_stack_config.py`
  - `just lint` is blocked by an existing formatting issue in `tests/e2e/test_dev_stack_e2e.py`

## Needs Code Or Product Decisions

- Decide whether `just test-e2e` should be documented as expected to fail with dummy provider keys, or whether the live-stack smoke/e2e coverage should split more explicitly between provider-free and provider-backed assertions.
- Fix the rebased test/lint regressions so the documented contributor verification loop is trustworthy again.
