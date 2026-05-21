# Docs Hygiene Follow-Ups

## Audited

- `README.md`
- `docs/ROADMAP.md`
- `AGENTS.md`
- `justfile`
- `docker-compose.yml`
- `docker-compose.e2e.yml`
- `scripts/run_e2e.sh`
- `tests/e2e/test_dev_stack_e2e.py`

## Patched

- Replaced current-behavior websocket references in `README.md`, `docs/ROADMAP.md`, and `AGENTS.md` with the Redis-backed long-poll render-job flow.
- Updated compose/e2e stack descriptions to include `redis` and `controller-worker`.
- Added the current known limitation that cache-index locking still uses filesystem locks over shared volumes.
- Removed stale `LAYERSENSE_E2E_CONTROLLER_WS_URL` guidance from `scripts/run_e2e.sh`.

## Remaining Historical Or Risky Items

- Several historical specs under `docs/superpowers/specs/` still describe websocket behavior. They are intentionally left as historical context and should not be treated as current runtime docs.
- `just test_python` now delegates to both unit and integration commands, but still fails repo-wide because `tests/test_python_test_taxonomy.py` requires a `layersense_controller/tests/integration/test_*.py` module and the controller integration suite has not been built yet.
- The cache index still relies on `fcntl.flock`, which may remain unreliable on some Docker Desktop shared-volume setups until a follow-up lock redesign lands.

## 2026-05-03 Addendum

### Audited

- `README.md`
- `docs/ROADMAP.md`
- `justfile`
- `tests/test_python_test_taxonomy.py`
- `layersense_agent/tests/integration/*.py`
- `layersense_agent/tests/cassettes/*`
- `layersense_controller/src/layersense_controller/router.py`

### Patched

- Updated `README.md` to reflect the current `layersense_agent` integration layout instead of the older single-file example.
- Documented that `layersense_agent` now reaches `100%` coverage across `layersense_agent/src/**` via integration tests alone.
- Added a summary of what the agent pass taught us: prefer `TestClient(app)` at the API boundary, split mocked-seam and VCR-backed tests, and keep production code authoritative.
- Added a concrete controller handoff/outlook to both `README.md` and `docs/ROADMAP.md` so another coding assistant can continue from the current backend testing milestone.

### Remaining Historical Or Risky Items

- `README.md` and `ROADMAP.md` are now current for the agent milestone, but the historical April taxonomy docs still describe the rollout as conservative and agent-only. They are intentionally left as historical notes.
- `layersense_controller/tests/conftest.py` already establishes a cassette directory, but there are still no controller integration modules using it.
- `layersense_agent/tests/integration/test_base_api_endpoints.py` is missing the `ai` marker even though it is assistant-authored; docs were updated, but the code issue remains outside this docs-only pass.

### Follow-Up Work Needing Code Or Product Decisions

- Build the first real controller integration module under `layersense_controller/tests/integration/` to unblock `just test_python` and align repo-level taxonomy enforcement with the actual suite.
- Decide whether controller integration coverage should remain VCR-centric, or whether local Redis/Taskiq/filesystem-backed tests should also count as first-class `integration` coverage.
- Consider adding fail-fast replay-mode cassette checks in shared VCR test infrastructure so missing recordings fail before a VCR-marked test body runs.

## Follow-Up Work Needing Code Or Product Decisions

- Decide whether `just test_python` should remain unit-only or be restored to unit+integration coverage.
- Decide whether historical websocket-era specs should be relabeled more aggressively as archived/historical in a separate docs pass.
- Decide whether cache-index locking should move off filesystem locks now that Redis is part of the active stack.
