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
- `just test_python` still runs only unit tests despite some older docs historically describing unit+integration behavior. Current-facing docs were updated to match the actual `justfile`; changing the recipe itself is a separate product/tooling choice.
- The cache index still relies on `fcntl.flock`, which may remain unreliable on some Docker Desktop shared-volume setups until a follow-up lock redesign lands.

## Follow-Up Work Needing Code Or Product Decisions

- Decide whether `just test_python` should remain unit-only or be restored to unit+integration coverage.
- Decide whether historical websocket-era specs should be relabeled more aggressively as archived/historical in a separate docs pass.
- Decide whether cache-index locking should move off filesystem locks now that Redis is part of the active stack.
