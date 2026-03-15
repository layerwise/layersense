# Controller Watcher Hardening Follow-Ups

Related implementation plan: `docs/plans/2026-03-07-layersense-implementation-plan.md` (Task 8)

## Context

Task 8 (`watcher.py` + `main.py`) is accepted and spec-compliant.
During quality review, we identified runtime-hardening items that are intentionally deferred to keep the milestone focused.

## Deferred Hardening Items

### 1) Handle non-2xx responses from `/render`

- **Current behavior:** watcher posts to controller and only logs transport-level exceptions.
- **Gap:** HTTP 4xx/5xx responses do not raise automatically in `httpx.post(...)` and can fail silently.
- **Hardening goal:** call `response.raise_for_status()` (or explicit status checks) and log failures with status code + short response detail.

### 2) Duplicate file-event suppression

- **Current behavior:** both create and modify events trigger posts immediately.
- **Gap:** editors/filesystems can emit bursts; duplicate render requests may be enqueued before cache state updates.
- **Hardening goal:** add short-window dedupe/debounce or in-flight request suppression keyed by scene path/content hash.

### 3) Test robustness to non-default port config

- **Current behavior:** some watcher tests assume default port values in assertions.
- **Gap:** tests are less resilient if environment-driven port changes during test execution.
- **Hardening goal:** derive expected URL from settings or monkeypatch settings explicitly in tests.

## Priority and Timing

- **Priority:** Medium
- **Recommended milestone:** After Task 16 smoke test, before wider use across mixed editor/file-system environments.

## Acceptance Criteria for Hardening Pass

1. Watcher logs and surfaces non-2xx controller responses.
2. Rapid duplicate file events do not enqueue duplicate render requests.
3. Watcher tests are deterministic across custom `LAYERSENSE_PORT` values.
4. Existing Task 8 behavior remains unchanged for happy-path flows.
