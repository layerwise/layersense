# Redis-Backed Render Lock — Implementation Plan

**Status:** Proposed
**Step in build order:** 1 of 9 (parallelizable with the persistence package, Step 2)
**Depends on:** nothing — disjoint from the persistence package
**Unblocks:** removes the documented `cache/index.json` file-lock contention bug on Docker shared volumes

---

## Why this step

`README.md` explicitly flags this as a known limitation:

> The cache index still uses file-based locking. In local Docker Desktop environments with shared host volumes, cache-index contention remains a known limitation until a Redis-backed cache-lock follow-up lands.

The current implementation lives in `layersense_controller/src/layersense_controller/cache.py` and uses `fcntl.flock` on `layersense_artifacts/cache/index.lock`. Two concrete problems:

1. **`fcntl.flock` semantics on shared Docker Desktop volumes are unreliable** across the host↔VM boundary. The lock can appear acquired on both sides simultaneously.
2. **The lock guards `index.json` writes**, but the actual contention concern is broader: two render workers can independently start the *same render* for the same `content_hash` because there is no cross-process render-level lock — only a write-time lock on the index file.

Redis is already deployed for render-job state and Taskiq transport (`layersense_controller/src/layersense_controller/broker.py`). Using it for distributed locking is free, correct, and removes the file-lock entirely.

This step is deliberately scoped to **only the lock primitive and its current callsites in `cache.py`**. It does not introduce render-deduplication based on `content_hash` (that lands naturally in Step 3 when `RendersRepository` replaces `index.json`).

---

## Scope

**In scope:**

- Replace the `fcntl.flock`-based `_cache_lock()` context manager in `layersense_controller/src/layersense_controller/cache.py` with a Redis `SET NX PX`-based distributed lock.
- New module `layersense_controller/src/layersense_controller/locks.py` exposing a small, typed lock primitive.
- Keep all current `cache.py` behavior byte-identical from the outside: same function signatures, same `index.json` layout, same routes.
- Tests using `fakeredis` for the lock primitive plus an integration test that exercises `store_cached_artifacts` under contention.

**Out of scope:**

- Replacing `index.json` with a SQLite table. That is Step 3.
- Adding a `content_hash`-keyed render-dedup lock around the worker entrypoint. That is a small follow-up after Step 3, where the right place to lock is obvious.
- Touching the `render_jobs` Redis client wiring. The new lock module reuses the existing client factory (`broker.create_redis_client`) — no new connection pool, no new config.
- Changing `watcher.py` or any agent code.

---

## Design

### Lock primitive

A minimal async context manager. No Redlock, no multi-node consensus — single Redis instance is the only deployment shape and that is fine for single-user.

```python
# layersense_controller/src/layersense_controller/locks.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from redis.asyncio import Redis

class LockAcquisitionError(RuntimeError):
    """Raised when a lock cannot be acquired within the configured timeout."""

@asynccontextmanager
async def redis_lock(
    redis: Redis,
    *,
    key: str,
    ttl_ms: int = 30_000,
    acquire_timeout_ms: int = 10_000,
    poll_interval_ms: int = 50,
) -> AsyncIterator[None]:
    """Acquire a Redis-backed mutex on `key` with a TTL safety net.

    Uses SET NX PX for atomic acquire with auto-expiry.
    Releases via a Lua CAS to avoid releasing a lock another holder now owns.
    """
    ...
```

**Key design points, with rationale:**

- **`SET NX PX <ttl>` for acquire.** Atomic. Standard Redis lock pattern. No race.
- **Per-acquisition token (uuid4).** Stored as the value at `key`. Release uses a Lua script that deletes only if the value still matches — prevents releasing a lock another caller has taken over after our TTL expired.
- **TTL safety net (default 30s).** If the controller crashes mid-cache-write, the lock self-releases. Cache writes are sub-second, so 30s is generous.
- **Bounded acquire timeout (default 10s).** Caller waits at most this long. Realistic cache contention windows are milliseconds; 10s is a paranoia ceiling.
- **Poll every 50ms while waiting.** Could use `BLPOP` semantics with a sentinel list, but that adds machinery for no measurable gain at our scale. Polling is fine.
- **Async-only API.** The controller is FastAPI + Taskiq, both async. `cache.py` is currently sync — see migration note below.

### Sync ↔ async at the `cache.py` boundary

`cache.py:_cache_lock()` is currently a sync `@contextmanager`. Its callers (`store_cached_artifacts`, etc.) are also sync. Two paths:

**Option A: keep callers sync, give them a sync lock wrapper.**
A thin sync wrapper that creates a short-lived sync `redis.Redis` client (not async) and uses `SET NX PX` directly. Simpler change to callers; uses `redis-py`'s sync API which is already a transitive dep.

**Option B: convert callers to async.**
Larger blast radius; requires touching every call site of `store_cached_artifacts` and friends. The controller is already async at the HTTP boundary, so most paths can absorb this — but some are inside Taskiq tasks with their own async/sync boundary.

**Recommendation: Option A.** Keep `cache.py` sync. The lock module exposes both a sync (`redis_lock_sync`) and async (`redis_lock`) variant, sharing a Lua release script and key conventions. This isolates the change. Step 3 deletes `cache.py` outright, so any Option-A awkwardness has a known sunset.

Both variants live in `locks.py`. The async one is the canonical implementation; the sync one is a thin shim using the sync `redis.Redis` client.

### Key naming

```
layersense:lock:cache_index            # global cache-index write lock (replaces fcntl.flock)
```

Namespaced so future locks (`layersense:lock:render:<content_hash>` in Step 3+, etc.) do not collide. No prefix collision with existing `render_jobs` keys (which use `render_job:` already).

### Configuration

Reuse `layersense_controller.config.settings.redis_url`. No new env vars.

Optional: add `cache_lock_ttl_ms: int = 30_000` and `cache_lock_acquire_timeout_ms: int = 10_000` to `RenderControllerSettings` so they are explicitly tunable. These are public-enough that hard-coding them invites a "where does this come from" hunt later.

### Failure modes

| Scenario | Behavior |
|---|---|
| Redis unreachable during acquire | `LockAcquisitionError` raised; cache write is aborted; render job is *not* corrupted (the index update simply did not happen, equivalent to crashing before write today). Caller logs and propagates. |
| Lock holder crashes mid-write | TTL expires after 30s; next caller acquires. Worst case: 30s stall on subsequent cache writes. |
| TTL expires while holder still working | Holder's release CAS fails silently (someone else now owns the lock). The slow holder's index write proceeds without the lock. **This is the one real risk.** Mitigation: 30s TTL is ~100x the realistic cache-write duration; if exceeded, something is fundamentally wrong and a stale lock is a smaller problem than a stuck system. Step 3 obsoletes the index entirely. |
| Redis restarts and loses the key | All locks effectively released. Acceptable; no durable invariant depends on lock persistence. |

---

## File-level changes

### New files

- `layersense_controller/src/layersense_controller/locks.py` — `redis_lock`, `redis_lock_sync`, `LockAcquisitionError`, internal Lua release script constant.
- `layersense_controller/tests/unit/test_locks.py` — primitive behavior with `fakeredis`.
- `layersense_controller/tests/integration/test_cache_lock_redis.py` — `cache.py` callsites under contention with `fakeredis`.

### Modified files

- `layersense_controller/src/layersense_controller/cache.py`
  - Delete `_cache_lock_path()` and the `fcntl`-based `_cache_lock()`.
  - Replace its callsites with `redis_lock_sync(client, key="layersense:lock:cache_index", ...)`.
  - Lazy-construct the sync redis client at first use (mirror the existing `broker.create_redis_client` pattern but sync).
- `layersense_controller/src/layersense_controller/config.py`
  - Add `cache_lock_ttl_ms` and `cache_lock_acquire_timeout_ms` fields with defaults.
- `README.md`
  - Strike the "cache-index contention remains a known limitation" sentence.
  - Add one line under "Notes" documenting that cache-index writes now coordinate via Redis.
- `docs/ROADMAP.md`
  - One-line entry under near-term focus.

### Deleted artifacts

- `layersense_artifacts/cache/index.lock` — runtime artifact, removed by `just db_reset`-style hygiene; not committed. Add to `.gitignore` if not already (it already lives in an ignored dir).

---

## Test plan

Following `.agents/skills/write-python-tests/SKILL.md`. All new tests use `fakeredis` — no live Redis required for `unit` or `integration` runs.

### Unit (`tests/unit/test_locks.py`)

- `redis_lock` acquires when the key is unset, sets the key with the expected token, releases via Lua CAS.
- `redis_lock` blocks when the key is held, then proceeds when it is released.
- `redis_lock` raises `LockAcquisitionError` when `acquire_timeout_ms` elapses.
- TTL-expired lock can be re-acquired by a fresh caller.
- Release CAS does not delete a key now owned by a different token (simulates TTL-expired holder).
- Same coverage for `redis_lock_sync`, parametrized to share assertions.

### Integration (`tests/integration/test_cache_lock_redis.py`)

- `store_cached_artifacts` happy path against `fakeredis` — verifies the swap is transparent.
- Two concurrent threads calling `store_cached_artifacts` on the same `content_hash` produce a consistent `index.json` (no last-write-wins corruption); both records are merged correctly under the lock.
- `store_cached_artifacts` raises `LockAcquisitionError` when a foreign holder occupies the lock for longer than `acquire_timeout_ms`. Test uses a low timeout (e.g., 200ms) for speed.

### Existing tests

- `layersense_controller/tests/integration/test_router_api.py`, `test_render_jobs_fakeredis.py`, `test_render_tasks_taskiq.py` — must continue to pass with no edits, because the lock change is internal to `cache.py`. If any of them implicitly tested `index.lock` filesystem behavior, that test gets removed (none should — verify during implementation).

### What is **not** tested at this layer

- Real Redis. Covered by `just e2e` and `just test-e2e`, which already run the local stack with real Redis. No new e2e test required; existing render-flow e2e exercises the cache path.
- Multi-process correctness on macOS Docker Desktop. The whole point of switching to Redis is that Redis correctness is well-known and does not need rediscovery here.

---

## Acceptance criteria

A reviewer can verify each directly:

1. `grep -rn "fcntl" layersense_controller/src/` returns no matches.
2. `grep -rn "index.lock" layersense_controller/src/` returns no matches; `index.lock` no longer appears at runtime under `layersense_artifacts/cache/`.
3. `uv run --package layersense-controller pytest -m unit -k locks` passes.
4. `uv run --package layersense-controller pytest -m integration -k cache_lock` passes.
5. Full `just test_python` passes with no edits to existing controller test modules (other than possibly removing tests that asserted on the old file lock — call out in the PR description if any).
6. `just e2e` passes against the local Docker stack (Redis already present in compose).
7. README's "known limitation" sentence about cache-index contention is removed.
8. Coverage delta for `layersense_controller/src/**` does not drop. The new `locks.py` is ≥ 95% covered by `test_locks.py`.
9. `just lint` passes.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Sync `redis.Redis` client introduces a new connection lifecycle in `cache.py` | Use a module-level lazy singleton, mirroring `broker.py` patterns. Single-user, low connection count — no pool tuning needed. |
| Tests that depend on the old file-lock break silently | Acceptance criterion 5 forces inspection. Any removal is called out in PR description. |
| Lock TTL too short for an unexpectedly slow cache write | 30s default is generous; tunable via config. If it ever bites, raise it. Step 3 obsoletes the lock entirely within weeks. |
| `fakeredis` does not support `SET NX PX` or Lua eval correctly | `fakeredis>=2` supports both. Verify by running `test_locks.py` first; if any gap, fall back to a real Redis container for that one suite via `pytest-docker`. Unlikely. |

---

## Estimated shape

Single small PR. ~150–250 LOC across `locks.py` and `cache.py` edits, ~250 LOC of tests, two doc touches. No schema changes, no API changes, no behavior change visible to the frontend.

---

## Assumptions

1. `fakeredis>=2` is acceptable as the test boundary. It is the standard repo pattern (already used in `test_render_jobs_fakeredis.py`).
2. `redis-py`'s sync API is acceptable inside `cache.py`. It is a transitive dep of `redis.asyncio` already, so no new external dep is added.
3. Adding `cache_lock_ttl_ms` and `cache_lock_acquire_timeout_ms` to `RenderControllerSettings` is preferable to hard-coding constants. Push back if you want them as plain module constants instead.
4. This step lands **before or in parallel with** the persistence-package step. Both touch disjoint files (`locks.py` + `cache.py` here; new package there), so order does not matter — but this one is a smaller, faster bug fix and may as well ship first.

→ Correct any of these or I proceed to Step 3 (`ObjectStore` + `cache.py` deletion + `RendersRepository` wiring), which depends on **both** Step 1 and Step 2 being merged.
