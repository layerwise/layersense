# Redis-Backed Render Lock — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md`.
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
- New module `layersense_controller/src/layersense_controller/locks.py` exposing two typed lock primitives:
  - `redis_lock` / `redis_lock_sync` — short-lived TTL-only mutex (used by `cache.py` now; by any short critical section later).
  - `RenewableLock` — long-lived async lock with background heartbeat renewal, designed for tasks that legitimately exceed the safety TTL (Manim renders can take minutes). **Required by Step 3's render-dedup lock**; included here so Step 3 has the primitive ready and the locking pattern lives in one module.
- Keep all current `cache.py` behavior byte-identical from the outside: same function signatures, same `index.json` layout, same routes.
- Tests using `fakeredis` for both primitives plus an integration test that exercises `store_cached_artifacts` under contention.

**Out of scope:**

- Replacing `index.json` with a SQLite table. That is Step 3.
- Adding the actual `content_hash`-keyed render-dedup lock around the worker entrypoint. That is Step 3 — Step 3 wires `RenewableLock` (introduced here) into the render task. Step 1 only ships the primitive plus its tests.
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

# Module constants — not settings fields (design decision #15)
CACHE_LOCK_TTL_MS = 30_000
CACHE_LOCK_ACQUIRE_TIMEOUT_MS = 10_000
CACHE_LOCK_POLL_INTERVAL_MS = 50
RENDER_LOCK_TTL_MS = 30_000
RENDER_LOCK_HEARTBEAT_INTERVAL_MS = 10_000
RENDER_LOCK_ACQUIRE_TIMEOUT_MS = 5_000

class LockAcquisitionError(RuntimeError):
    """Raised when a lock cannot be acquired within the acquisition timeout."""

@asynccontextmanager
async def redis_lock(
    redis: Redis,
    *,
    key: str,
    ttl_ms: int = CACHE_LOCK_TTL_MS,
    acquire_timeout_ms: int = CACHE_LOCK_ACQUIRE_TIMEOUT_MS,
    poll_interval_ms: int = CACHE_LOCK_POLL_INTERVAL_MS,
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

### `RenewableLock` — heartbeat-renewed long-lived mutex

Manim renders can run for minutes. A flat TTL is the wrong shape: too short and the lock self-releases mid-render (allowing duplicate work); too long and a crashed worker holds the lock until the TTL expires (blocking legitimate retries).

The standard pattern: short TTL + background heartbeat that re-extends the TTL while the holder is alive. Death of the holder stops the heartbeat; the TTL then drains naturally within seconds.

```python
# layersense_controller/src/layersense_controller/locks.py

class RenewableLock:
    """Long-lived async Redis lock with background heartbeat renewal.

    Use for critical sections that can legitimately exceed `ttl_ms` (e.g.,
    minute-scale Manim renders). Heartbeat re-extends TTL every
    `heartbeat_interval_ms`. On holder death (cancellation, crash), the
    heartbeat task stops and TTL drains within ~heartbeat_interval_ms +
    network jitter, releasing the lock for the next caller.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        key: str,
        ttl_ms: int = RENDER_LOCK_TTL_MS,
        heartbeat_interval_ms: int = RENDER_LOCK_HEARTBEAT_INTERVAL_MS,
        acquire_timeout_ms: int = RENDER_LOCK_ACQUIRE_TIMEOUT_MS,
    ) -> None: ...

    async def __aenter__(self) -> "RenewableLock": ...
    async def __aexit__(self, *exc_info: object) -> None: ...
```

**Key design points:**

- **Acquire** uses the same `SET NX PX <ttl_ms>` + per-acquisition uuid token as `redis_lock`. Same Lua CAS release.
- **Heartbeat** is an `asyncio.Task` started in `__aenter__`. Every `heartbeat_interval_ms` it runs a Lua script: "if value == token then PEXPIRE key ttl_ms". Atomic. If the token has changed (TTL drained, someone else took over), the heartbeat detects it and the lock is treated as lost — the body keeps running, but `__aexit__` will not delete a foreign token. The body itself is expected to be cancelled by the caller in that case via a sibling watchdog (see Step 3).
- **Invariant**: `heartbeat_interval_ms < ttl_ms / 2`. Defaults 10s / 30s give a 3x safety margin against scheduler hiccups.
- **No watchdog cancellation here.** `RenewableLock` only reports lock status; Step 3 layers the worker-cancellation policy on top. Keeping the primitive narrow keeps it testable.
- **`acquire_timeout_ms` default 5s** because dedup callers should fail fast — if another worker is already rendering this exact `content_hash`, the right behavior is to attach to that existing render's `job_id`, not to wait.

### Sync ↔ async at the `cache.py` boundary

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

Reuse `layersense_controller.config.settings.redis_url`. No new env vars and no TTL settings fields.

Lock TTLs and polling/acquisition timeouts are module-level constants in `locks.py`, tunable only by code change (design decision #15).

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

- `layersense_controller/src/layersense_controller/locks.py` — `redis_lock`, `redis_lock_sync`, `RenewableLock`, `LockAcquisitionError`, internal Lua scripts (release CAS + heartbeat CAS) as module constants.
- `layersense_controller/tests/unit/test_locks.py` — primitive behavior with `fakeredis` for all three primitives.
- `layersense_controller/tests/integration/test_cache_lock_redis.py` — `cache.py` callsites under contention with `fakeredis`.

### Modified files

- `layersense_controller/src/layersense_controller/cache.py`
  - Delete `_cache_lock_path()` and the `fcntl`-based `_cache_lock()`.
  - Replace its callsites with `redis_lock_sync(client, key="layersense:lock:cache_index", ...)`.
  - Lazy-construct the sync redis client at first use (mirror the existing `broker.create_redis_client` pattern but sync).
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
- `RenewableLock` happy path: acquires, heartbeat extends TTL past initial `ttl_ms` while held, releases on `__aexit__`.
- `RenewableLock` heartbeat survives one missed beat (transient `fakeredis` error injection) without losing the lock.
- `RenewableLock` reports `lock_lost=True` when a foreign holder takes the key after TTL drain (verifies CAS detects token change).
- `RenewableLock` cancellation: cancelling the body cancels the heartbeat task cleanly (no orphan tasks).
- Invariant guard: constructing `RenewableLock` with `heartbeat_interval_ms >= ttl_ms / 2` raises `ValueError`.

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
3. `uv run --package layersense-controller pytest -m unit -k locks` passes, including `RenewableLock` heartbeat-renewal and lock-loss-detection tests.
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
| Lock TTL too short for an unexpectedly slow cache write | 30s default is generous; module constant in `locks.py`, tunable only by code change (design decision #15). If it ever bites, raise it in code. Step 3 obsoletes the lock entirely within weeks. |
| `fakeredis` does not support `SET NX PX` or Lua eval correctly | `fakeredis>=2` supports both. Verify by running `test_locks.py` first; if any gap, fall back to a real Redis container for that one suite via `pytest-docker`. Unlikely. |

---

## Estimated shape

Single small PR. ~250–400 LOC across `locks.py` (now includes `RenewableLock`) and `cache.py` edits, ~400 LOC of tests, two doc touches. No schema changes, no API changes, no behavior change visible to the frontend. `RenewableLock` is unused by `cache.py` and is exercised only by its own unit tests; it lights up as a real callsite in Step 3.

---

## Assumptions

1. `fakeredis>=2` is acceptable as the test boundary. It is the standard repo pattern (already used in `test_render_jobs_fakeredis.py`).
2. `redis-py`'s sync API is acceptable inside `cache.py`. It is a transitive dep of `redis.asyncio` already, so no new external dep is added.
3. Lock TTL/acquisition/poll settings are plain module constants in `locks.py`, tunable only by code change (design decision #15), not `RenderControllerSettings` fields or env-backed config.
4. This step lands **before or in parallel with** the persistence-package step. Both touch disjoint files (`locks.py` + `cache.py` here; new package there), so order does not matter — but this one is a smaller, faster bug fix and may as well ship first.

→ Correct any of these or I proceed to Step 3 (`ObjectStore` + `cache.py` deletion + `RendersRepository` wiring), which depends on **both** Step 1 and Step 2 being merged.

**Amendment (2026-05-22):** TTL values changed from settings fields to module constants per design decision #15 and audit finding 1.1.
