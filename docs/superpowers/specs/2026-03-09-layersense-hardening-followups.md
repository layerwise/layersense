# LayerSense Hardening Follow-Ups

Related implementation plan: `docs/plans/2026-03-07-layersense-implementation-plan.md`

## Context

During Task 4 (`layersense_controller` cache module) quality review, we identified hardening items that are intentionally deferred to keep implementation aligned with the current milestone scope.

Current Task 4 status remains accepted as-is.

## Deferred Hardening Items

### 1) Validate `content_hash` before path construction

- **Current behavior:** `preview_artifact()` and `final_artifact()` interpolate `content_hash` directly into filename strings.
- **Risk:** If an untrusted or malformed value reaches these functions, path traversal or invalid-path behavior could occur.
- **Hardening goal:** Only allow lowercase 64-char SHA-256 hex values (`^[a-f0-9]{64}$`) before constructing artifact paths.
- **Suggested approach:**
  - Add a small validator function in `layersense_controller/cache.py`.
  - Raise `ValueError` on invalid input.
  - Keep function signatures unchanged.

### 2) Expand cache behavior tests

- **Current coverage:**
  - `is_cached(...) -> (False, False)`
  - `is_cached(...) -> (True, False)`
- **Missing cases:**
  - `is_cached(...) -> (False, True)`
  - `is_cached(...) -> (True, True)`
  - explicit tests for `preview_artifact()` and `final_artifact()` path construction
- **Hardening goal:** Full cache-state matrix coverage plus path construction assertions.

### 3) Optional streaming hash implementation

- **Current behavior:** `hash_file()` reads the full file into memory via `read_bytes()`.
- **Risk:** Memory pressure for very large scene files (low risk for current scope, but avoidable).
- **Hardening goal (optional):** Switch to chunked hashing for scalability while preserving output parity.
- **Suggested approach:** read in fixed chunks (e.g. 64 KiB), update digest incrementally.

## Priority and Timing

- **Priority:** Medium
- **Recommended milestone:** After Task 16 integration smoke test, before broadening to multi-user or remote deployment.

## Acceptance Criteria for Hardening Pass

1. Invalid `content_hash` inputs are rejected deterministically.
2. Cache tests cover all four `(preview_exists, final_exists)` combinations.
3. Path builder helpers are explicitly tested.
4. (Optional) streaming hash implementation produces identical digest outputs to previous implementation for representative files.
5. Existing integration flow remains unchanged for valid hashes.

## Out of Scope (for now)

- Multi-tenant artifact isolation
- Content-addressed storage abstraction
- Security policy engine for path access
