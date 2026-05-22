# ObjectStore + RendersRepository Wiring — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md` (overview is canonical for schema, key layout, and Option C boundaries). Amended 2026-05-21 to (a) split delivery into two PRs (3a `layersense_storage` package; 3b controller wiring), (b) make the `/render` HTTP-contract break explicit, (c) lock the watcher hard-disabled with a startup raise, (d) wire `RenewableLock` (from Step 1) for the in-flight render-dedup mutex, (e) declare the `_default` project shim's wipe boundary at Step 4.
**Step in build order:** 3 of 9 (delivered as **3a → 3b** in that order)
**Depends on:** Step 1 (Redis lock + `RenewableLock` primitive) merged, Step 2 (`layersense_persistence`) merged
**Unblocks:** Step 4 (frontend revamp), Step 5 (agent refinement), Step 6 (project export), Step 8 (S3 backend)

---

## Why this step

This is the load-bearing migration. After this step:

- `layersense_artifacts/cache/index.json` is **deleted**. Render cache identity lives in the `render` table (Step 2).
- All artifact reads/writes go through an `ObjectStore` interface. The default impl is `LocalFSObjectStore`; an S3 impl can be slotted in later (Step 8) without touching callers.
- Generated `.py` scene files are content-addressed in the object store, written by the **controller** after the agent returns raw source bytes. The agent has no ObjectStore awareness — it remains a pure function `(payload) → source bytes`.
- The agent and controller stop sharing a host-mounted scratch dir (`layersense_artifacts/code/` is gone).
- The `cache.py` module is **deleted**. Its functions are absorbed into a new `artifacts.py` (object-store façade) and the `RendersRepository` (semantic mapping).

The visible behavior of the system to the frontend is unchanged in this step: same `/render` and `/render-jobs/{job_id}` contracts, same `/artifacts/by-hash/...` and `/artifacts/scenes/...` routes. The change is internal substrate only — but it is the substrate every later step depends on. Step 4 introduces a new `/scenes/{id}/generate` endpoint and retires the browser→agent direct call.

**Architectural anchor (Option C, decided in Step 4 design discussion):** the agent is a stateless pure function. The controller is the orchestrator and the only writer to the database and the object store. The browser only ever talks to the controller. This step makes the object-store half of that contract real; Step 4 makes the orchestration half real.

---

## Delivery split: 3a then 3b

This step ships as two PRs in order. They are cumulative; nothing in 3b can land before 3a.

**PR 3a — `layersense_storage` package, standalone.**

- New uv workspace member, no consumers wired in yet.
- `ObjectStore` Protocol, `LocalFSObjectStore`, `keys.py`, `errors.py`, `config.py`.
- Full unit + concurrency-integration test coverage at ≥ 95%.
- Zero edits to `layersense_controller`, `layersense_agent`, frontend, docker-compose, README, ROADMAP.
- Acceptance criteria 1–9 of "PR 3a Acceptance" below; controller-wiring criteria deferred to 3b.
- Cassettes: none touched.
- Reviewable in isolation. Mergeable independently. If 3b is blocked or contested, 3a still lands as a stable, unused package.

**PR 3b — controller wiring, contract break, `cache.py` deletion, `_default` shim, watcher disable.**

- Depends on PR 3a merged.
- All file-level changes in `### Modified` and `### Deleted` below.
- The breaking `/render` HTTP-contract change (`scene_path` → `source_code` + `content_hash`) lands here in a single atomic commit alongside the matching frontend, agent, compose, and cassette updates. No transitional dual-shape support.
- The `_default` project shim is created here. **Step 4 wipes it on boundary.** See "_default shim cleanup" below.
- Watcher hard-disabled with `raise NotImplementedError` on startup; tests skipped, not deleted.
- `RenewableLock` from Step 1 is wired around the worker entrypoint for in-flight render dedup. See "Render dedup with heartbeat" below.
- Cassettes refresh in one explicit step; called out in the PR description.

**Why split:** PR 3a is a self-contained library landing. PR 3b is a coordinated breaking change across three services + frontend + compose + cassettes. Reviewing them together makes the diff impossible to reason about; reviewing them separately gives a clean library boundary first, then a focused integration commit.

---

## Scope

### In scope

1. New `layersense_storage` workspace package owning the `ObjectStore` abstraction and the local-FS implementation. **Imported by `layersense_controller` only.** Not imported by the agent — the agent has no storage awareness.
2. Delete `layersense_controller/src/layersense_controller/cache.py` entirely.
3. Replace its functionality:
   - **Content-hash → artifact bytes**: `ObjectStore.get/put/head/delete` keyed by deterministic paths.
   - **Content-hash → scene_uuid mapping, render lifecycle, `current_render_id`**: `RendersRepository` + `ScenesRepository` from `layersense_persistence`.
4. **Migrate the agent to return raw source bytes**, not a host path. The agent stops writing files anywhere — it returns `{ source_code: "<python source as string>", content_hash }` from `POST /api/v1/animation`. `LAYERSENSE_SCENES_DIR` is removed from the agent entirely.
5. **The controller writes the agent's response into the object store.** On receiving raw source from the agent, the controller computes the canonical content hash, writes the bytes via `ObjectStore.put`, stores the resulting key on the `Render` row.
6. Migrate the controller render path: read scene source via `ObjectStore.get`, compute content hash, look up an existing `Render` row by `(content_hash, cli_flags)`, short-circuit on hit, otherwise create a new `Render` row, run Manim, `put` outputs into the object store, update the row.
7. Migrate the controller's two browser-facing artifact routes to read from the object store (streaming where possible).
8. Update compose: `LAYERSENSE_SCENES_DIR` host-mount on `agent` is removed. The `agent` service mounts no shared volume at all (it has nothing to share). The `controller` and `controller-worker` mount only the new storage volume.
9. Update tests: replace `test_cache_index_integration.py` and `test_cache.py` with object-store and renders-repository integration tests. Existing router/render tests get minor edits (no more `index.json` assertions).

### Out of scope

- S3-compatible backend implementation (Step 8). The interface is designed for it; only the local-FS impl is built.
- Project/Scene CRUD endpoints. The `Project` and `Scene` rows still come into existence implicitly here — see "Implicit project/scene creation" below — until Step 4 adds explicit CRUD.
- Frontend changes. The HTTP contract between frontend and controller is preserved.
- Agent refinement / `parent_render_id` chaining. Step 5.
- Project export tarballs. Step 6.

---

## Design

### `layersense_storage` package

New uv workspace member. Boundary-pure, no FastAPI / Taskiq / SQLAlchemy deps.

```
layersense_storage/
  pyproject.toml
  src/layersense_storage/
    __init__.py
    config.py             # StorageSettings (root path)
    object_store.py       # ObjectStore Protocol + LocalFSObjectStore
    keys.py               # canonical key derivation helpers
    errors.py             # ObjectNotFoundError, ObjectStoreError
  tests/
    unit/
      test_local_fs_object_store.py
      test_keys.py
    integration/
      test_local_fs_concurrent_writes.py
```

### `ObjectStore` interface

```python
class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...
    def put_stream(self, key: str, source: BinaryIO, *, content_type: str | None = None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def open(self, key: str) -> BinaryIO: ...           # for FastAPI streaming
    def head(self, key: str) -> ObjectInfo | None: ...  # None if missing; ObjectInfo has size, content_type, etag
    def delete(self, key: str) -> None: ...
    def list_prefix(self, prefix: str) -> Iterator[str]: ...
    def url_for(self, key: str) -> str: ...             # local impl returns absolute filesystem path; S3 impl would presign
```

**Key design points:**

- **Sync API.** Object I/O is local-filesystem today and per-call short. No async benefit; matches `cache.py` callers as-is. The S3 impl in Step 8 will provide an async variant alongside if needed.
- **`put_stream` / `open`** for large mp4 files. Mp4s reach tens of MB; we don't hold them in memory.
- **`url_for` returns a string** that the controller's FastAPI routes can resolve. Local impl returns a filesystem path string; the existing `FileResponse` path handling stays. Step 8's S3 impl returns a presigned HTTP URL — at that point routes flip to `RedirectResponse`. Not now.
- **No batch/transaction primitives.** Atomicity at the `Render` row level lives in SQLite; the object store is the dumb blob layer.
- **`ObjectInfo.etag`** is the SHA-256 hex of contents for the local impl. Cheap, deterministic, and lets callers verify integrity without a separate hash call. (S3 etag semantics are different but compatible at our usage level.)

### Canonical key layout

Stable, content-addressed where it matters, semantic where it helps debuggability:

```
renders/{content_hash}/source.py                  # generated Manim source, immutable per hash
renders/{content_hash}/preview.mp4                # rendered preview, immutable per hash
renders/{content_hash}/final.mp4                  # rendered final, immutable per hash
renders/{content_hash}/manim.log                  # captured stdout/stderr from the render
projects/{project_id}/assets/{asset_id}/{filename}  # reserved for Step 7 (component lib + assets); not used here
```

**Notes:**

- **Everything for a render lives under one `renders/{content_hash}/` prefix.** Source, preview, final, log. Trivially deletable as a unit. Trivially exportable as a unit (Step 6).
- **Renders keyed by `content_hash`, not `render_id`.** Two `Render` rows with identical `content_hash` (e.g., refinement that converged on the same code) point at the same blobs. This is the cache: free deduplication at the storage layer.
- **No `_root` / `generated_scenes` legacy directories.** Those were artifacts of a pre-Project world and disappear with `cache.py`.

`keys.py` exposes pure helpers: `render_source_key(content_hash)`, `render_preview_key(content_hash)`, `render_final_key(content_hash)`, `render_log_key(content_hash)`. Callers never hand-format keys.

### `LocalFSObjectStore`

- Root: `LAYERSENSE_STORAGE_ROOT`, default `./layersense_artifacts/storage`. **New directory, not the existing `layersense_artifacts/scenes/` or `code/` paths** — clean break, no migration of legacy files. Old dirs stay until manually wiped.
- `put` writes to `<temp>` then `os.replace` for atomicity.
- `put_stream` chunks 1 MiB; same temp+replace pattern.
- `get` / `open` raise `ObjectNotFoundError` on missing.
- Concurrent `put` of the same key resolves to last-write-wins at the OS level. Acceptable: keys are content-addressed, so byte content is identical by construction; if two callers write the same key, they wrote the same bytes.

### Schema additions in `layersense_persistence`

Step 2's schema, as normalized against the overview, already includes:

- `render.scene_py_artifact_key` (nullable until agent returns)
- `render.preview_artifact_key`, `render.final_artifact_key`
- `render.log_artifact_key` (set when worker finishes — used here for debug log retention)
- `scene.thumbnail_artifact_key` (set by worker after preview; consumed by Step 4)
- `render.status` enum includes `generating | queued | preview_ready | final_ready | failed`

**No new migrations are needed in this step.** All required columns are in `0001_initial` per the normalized Step 2 plan. If you find a column missing because the Step 2 PR shipped before the normalization landed, add it as a focused `0002_*.py` migration in this PR rather than back-editing `0001`.

### Implicit project/scene creation

Until Step 4 introduces explicit project/scene CRUD, the controller's `POST /render` needs project and scene rows to attach the `Render` to. Strategy:

- Frontend continues to send `conversation_id` (existing field).
- Controller treats `conversation_id` as a **scene identifier shim** for now: on `POST /render`, look up `Scene WHERE id = conversation_id`. If absent, create a `Scene` under a **default `Project` named `"_default"`** (auto-created on first use; idempotent via `UPSERT slug='_default'`).
- The Scene's `name` is the conversation_id; `order_index` is the next int; `excalidraw_scene_json` and `prompt` are left empty until Step 4 makes them first-class. The agent does not yet know about scene_id.

This is deliberately ugly. It is a 30-line shim that lets Step 3 ship without dragging Step 4's CRUD into the same PR. The shim disappears in Step 4.

**Push-back surfaced explicitly:** an alternative is to introduce a real `POST /scenes` endpoint in this PR and have the frontend call it before `/render`. That doubles the PR size and forces frontend changes I committed to deferring to Step 4. The shim is the right call given the build order; it lives for one step.

#### `_default` shim cleanup (Step 4 boundary)

The shim is born in PR 3b and is **wiped, not migrated, at the Step 4 boundary**.

- **Death plan:** Step 4's first commit is a focused migration `0003_drop_default_project_shim.py` that:
  - Deletes the `project WHERE slug='_default'` row.
  - Relies on `ON DELETE CASCADE` (declared in Step 2's `0001_initial`) to remove all dependent `scene`, `frame`, and `render` rows.
  - Calls `ObjectStore.list_prefix("renders/")` and `delete()` for every key produced by `_default`-attributed renders. The Step 4 PR adds a `RendersRepository.list_keys_for_project(project_id)` helper specifically for this wipe.
  - Logs a one-line summary: "wiped N renders / M blobs from _default shim".
- **No data preservation.** The `_default` shim only ever holds throwaway content from the Step 3 transition window (you, single-user, dev stage, between PR 3b and Step 4 landing). Any render you actually care about is re-generated against a real Project in Step 4's CRUD-driven flow.
- **Anti-leak guard in Step 4:** acceptance criteria for Step 4 include `SELECT COUNT(*) FROM project WHERE slug='_default'` returning 0 after `just db_reset && just docker && (Step 4 boot)`. Any creation path that would resurrect the shim is removed.
- **PR 3b TODO marker:** the shim's call site in `router.py` is decorated with `# TODO(step-4): remove. See docs/plans/2026-05-21-frontend-revamp-and-project-scene-crud-plan.md §"_default shim wipe".` so grep finds it on Step 4 kickoff.

### Agent ↔ Controller contract change (**BREAKING**)

This is a breaking HTTP-contract change to **both** `POST /api/v1/animation` (agent) and `POST /render` (controller), shipped atomically in **PR 3b**. There is no transitional dual-shape support; the old and new shapes do not coexist for even one commit.

**Today:**

```
browser → agent: POST /api/v1/animation { excalidraw_scene, prompt }
  agent → writes ./layersense_artifacts/code/generated_<uuid>.py
  agent → returns { conversation_id, scene_path: "./layersense_artifacts/code/generated_<uuid>.py" }

browser → controller: POST /render { scene_path, conversation_id, cli_flags? }
  controller → reads scene_path from the shared host-mounted disk
```

**After PR 3b:**

```
browser → agent: POST /api/v1/animation { excalidraw_scene, prompt }       (request shape unchanged; response changes)
  agent → returns { conversation_id, source_code: "<python source>", content_hash }
  agent → has zero filesystem touches; does not import layersense_storage

browser → controller: POST /render { conversation_id, source_code, content_hash, cli_flags? }
  controller → ObjectStore.put(render_source_key(content_hash), source_code.encode())
  controller → creates Render row, dispatches Taskiq job

worker → ObjectStore.get(render_source_key) → /tmp/layersense-renders/<render_id>/scene.py → manim
worker → ObjectStore.put_stream(render_preview_key, ...), then render_final_key
```

**What this means for clients:**

- Any caller still sending `scene_path` to `POST /render` after PR 3b lands gets `HTTP 422 Unprocessable Entity` from FastAPI's pydantic validation. There is no compatibility shim.
- The agent response key `scene_path` is gone. Any caller still reading it gets `KeyError` / `undefined`.
- The frontend is updated in the same PR 3b to forward the new agent response fields straight through to the new `/render` request shape. No browser-side logic interprets the source bytes.
- `tests/e2e/test_dev_stack_e2e.py` is updated in the same PR 3b. No staging or canary window.

**Why no dual-shape support:** single-user dev stage; there are no external clients to migrate; the only "client" is the frontend in this same monorepo and the e2e test suite. A dual-shape phase would double the surface for one PR's worth of benefit (zero — no client is on the old shape after merge). Reviewer-visible cost of the break is exactly: bad pydantic payloads fail loudly, and `git bisect` across this commit needs a `just docker` restart. Acceptable.

**Notes on the new contract:**

- The agent's response now contains **raw Python source as a string**, not a key. Manim files are tiny (typically 1–10 KB); HTTP transport is fine.
- The browser passes the source bytes verbatim from the agent's response into `POST /render`. It does not interpret or modify them. (In Step 4 this changes again: the browser stops talking to the agent at all, the controller orchestrates both calls server-side. Step 3 keeps today's two-call browser flow to limit blast radius.)
- The controller is the **only** writer to the ObjectStore. The agent does not import `layersense_storage`.
- The shared host-mounted `layersense_artifacts/code/` volume is removed from `docker-compose.yml`. The agent service has no mounted volumes after this step.
- The controller still needs to materialize the source as a real file on disk for the Manim CLI subprocess (Manim does not read from stdin). It does so to a per-render temp dir under `LAYERSENSE_RENDER_WORKDIR` (default `/tmp/layersense-renders/<render_id>/`), cleaned up after the render finishes. This is ephemeral, not shared, and not the object store.

### Render dedup with heartbeat (`RenewableLock`)

The render is the long critical section in this system. A Manim render can take 30s for a preview and several minutes for a final. A flat-TTL Redis mutex is the wrong shape: too short and the lock self-releases mid-render (two workers double-encode the same content_hash and race on `put_stream`); too long and a crashed worker holds the lock until the TTL drains, blocking legitimate retries.

PR 3b wires `RenewableLock` (introduced in Step 1) around the worker entrypoint:

```python
# inside the Taskiq render task body, pseudo-code
lock_key = f"layersense:lock:render:{effective_hash}"
async with RenewableLock(
    redis,
    key=lock_key,
    ttl_ms=settings.render_lock_ttl_ms,                # 30_000
    heartbeat_interval_ms=settings.render_lock_heartbeat_interval_ms,  # 10_000
    acquire_timeout_ms=settings.render_lock_acquire_timeout_ms,        # 5_000
) as lock:
    # heartbeat task is now extending TTL every 10s
    materialize_scene_source_for_manim(...)
    run_manim_preview(...)
    object_store.put_stream(render_preview_key(effective_hash), ...)
    update_render_row(status="preview_ready", ...)
    run_manim_final(...)
    object_store.put_stream(render_final_key(effective_hash), ...)
    update_render_row(status="final_ready", ...)
```

**Behavior:**

- If a second worker picks up an identical-hash render while the first is still in flight, `RenewableLock.__aenter__` waits up to `acquire_timeout_ms` (5s). It then raises `LockAcquisitionError`. The dispatching code catches that and short-circuits the second job: it attaches to the first job's `job_id` via `RendersRepository.find_in_flight_by_hash(effective_hash)` and returns that snapshot, no duplicate work.
- If the first worker crashes (kill, OOM, container restart): heartbeat task stops; TTL drains within ~`ttl_ms + heartbeat_interval_ms` worst case (40s); next caller acquires the lock and re-renders.
- If the heartbeat detects the lock has been stolen (token mismatch — should not happen with correct TTL/interval math, but guarded), the worker raises `LockLost` and the Render row is marked `failed` with reason `lock_lost`. This is observable and recoverable, not silent.

**Configuration** (module constants on `RenderControllerSettings`, per user preference):

- `render_lock_ttl_ms: int = 30_000`
- `render_lock_heartbeat_interval_ms: int = 10_000`
- `render_lock_acquire_timeout_ms: int = 5_000`

The Step 1 invariant `heartbeat_interval_ms < ttl_ms / 2` is satisfied with 3x margin.
- `scene_path` is **removed** from both the agent response and the controller request. This is a breaking change — explicitly intended — and the frontend is updated in lockstep within this PR.

### Render path, end to end after this step

```
1. POST /render { conversation_id, source_code, content_hash, cli_flags? }
2. controller normalizes cli_flags → canonical JSON
3. controller computes effective hash = sha256(content_hash + canonical_cli_flags_json)
4. RendersRepository.find_by_content_hash(effective_hash):
     - hit AND preview+final keys point at extant blobs (object_store.head)
       → create new Render row pointing at the SAME artifact keys (cache reuse),
         set scene.current_render_id, return { job_id: synthetic, status: final_ready, urls }
     - hit but blobs missing (drift)
       → fall through, re-render
     - miss
       → object_store.put(render_source_key(effective_hash), source_code.encode())
       → create Render row (status=queued, scene_py_artifact_key=...), enqueue Taskiq job
5. Taskiq worker:
     - object_store.get(scene_py_artifact_key) → write to /tmp/layersense-renders/<render_id>/scene.py
     - run Manim preview → object_store.put_stream(render_preview_key(effective_hash), ...)
     - update Render row (status=preview_ready, preview_artifact_key=...)
     - run Manim final → object_store.put_stream(render_final_key(...), ...)
     - update Render row (status=final_ready, final_artifact_key=..., log_artifact_key=...)
     - publish Redis pubsub on render-job channel (existing mechanism)
     - clean up /tmp workdir
6. Frontend long-polls GET /render-jobs/{job_id} (unchanged)
7. Frontend hits /artifacts/by-hash/{content_hash}/preview (controller streams from object_store)
```

The `cache_index` Redis lock from Step 1 is **deleted** in this PR — there is nothing left to lock around once `cache.py` is gone. In-flight render dedup is handled by `RenewableLock` keyed `layersense:lock:render:{effective_hash}` around the Taskiq task body, per the "Render dedup with heartbeat" section above. Even if dedup ever fails (e.g., lock acquisition timeout coincides with row-creation race), the worst case is two workers producing byte-identical blobs at the same content-addressed key — no corruption, just wasted CPU.

---

## File-level changes

### New

- `layersense_storage/pyproject.toml`, `src/layersense_storage/{__init__,config,object_store,keys,errors}.py`
- `layersense_storage/tests/unit/test_local_fs_object_store.py`
- `layersense_storage/tests/unit/test_keys.py`
- `layersense_storage/tests/integration/test_local_fs_concurrent_writes.py`
- `layersense_controller/src/layersense_controller/artifacts.py` — thin façade combining `ObjectStore` + `RendersRepository` + `ScenesRepository` for the controller's use cases (`store_render_outputs`, `lookup_render_by_hash`, `materialize_scene_source_for_manim`).

### Modified

- `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py` — drop `LAYERSENSE_SCENES_DIR` and all filesystem writes; return `{ conversation_id, source_code, content_hash }`. The agent computes `content_hash = sha256(source_code.encode()).hexdigest()` itself; this is its only "hashing" responsibility.
- `layersense_agent/src/layersense_agent/main.py` and config — drop `LAYERSENSE_SCENES_DIR`. **No new settings added** to the agent in this step. (The `controller_base_url` mention from earlier drafts is gone — Step 4 is where the controller becomes the orchestrator, and even there it's the *controller* that gets an `agent_base_url`, not the reverse.)
- `layersense_controller/src/layersense_controller/router.py` — accept `source_code` + `content_hash` instead of `scene_path`; consult `RendersRepository` + `artifacts.py` instead of `cache.py`; on cache miss, write source bytes to ObjectStore via `render_source_key`.
- `layersense_controller/src/layersense_controller/render.py`, `render_tasks.py`, `render_runtime.py` — operate on object-store keys + temp workdir, not host paths.
- `layersense_controller/src/layersense_controller/config.py` — drop `scenes_dir`; add `storage_root` (default `./layersense_artifacts/storage`), `render_workdir` (default `/tmp/layersense-renders`).
- `layersense_controller/src/layersense_controller/watcher.py` — **hard-disable.** On module import or startup hook, raise `NotImplementedError("watcher disabled in Step 3; redesign in Step 7 as project-aware")`. Any code path that previously instantiated the watcher (lifespan startup, CLI subcommand, tests) is updated to skip-or-assert-raises. Watcher unit/integration tests are **marked `pytest.skip` with a reason string pointing at Step 7**, not deleted. The file is not deleted because the project-aware rewrite in Step 7 will reuse the FS-event scaffolding.
- `layersense_frontend/src/api.ts` and `App.tsx` — pass `source_code` + `content_hash` through to `POST /render`. Small, mechanical.
- `docker-compose.yml` — drop `LAYERSENSE_SCENES_DIR` and the shared `code/` mount. The `agent` service has no mounted volumes. `controller` and `controller-worker` mount only `./layersense_artifacts/storage/`.
- `README.md` — rewrite "Render Layout" and "Current Architecture" sections to reflect object store + DB; remove `cache/index.json` references and the `scenes/<project>/<preview|final>/...` example tree.
- `docs/ROADMAP.md` — update "Current Status" entries.

### Deleted

- `layersense_controller/src/layersense_controller/cache.py`
- `layersense_controller/tests/unit/test_cache.py`
- `layersense_controller/tests/integration/test_cache_index_integration.py`
- The Step 1 cache-index lock module entry (`layersense:lock:cache_index` is unused after this; the `locks.py` module stays — it gains the `layersense:lock:render:{hash}` callsite).

---

## Test plan

### `layersense_storage`

**unit:**
- `put` + `get` roundtrip; `head` reports correct size and etag (= sha256).
- `head` on missing key returns `None`.
- `get` on missing raises `ObjectNotFoundError`.
- `put_stream` with a large in-memory `BytesIO`; verify chunked write produces identical bytes.
- `delete` removes; `head` then returns `None`; `get` raises.
- `list_prefix` returns sorted, deduplicated keys; respects prefix boundaries.
- `keys.py` helpers produce stable, escape-safe paths; reject keys with `..` or absolute components.
- Atomic write: simulate crash mid-`put` (write then no rename) — final state is *no* file at the key (temp file is cleaned in `finally`).

**integration:**
- Two threads `put`-ing the same key with identical bytes — final file has identical bytes; no half-written state observable from a third reader.
- Two threads `put`-ing different keys — both succeed; no cross-talk.

### `layersense_controller`

**unit:**
- `artifacts.materialize_scene_source_for_manim` writes to a temp workdir, returns the path, cleans up via context manager.
- `artifacts.store_render_outputs` puts preview/final/log into the object store and updates the `Render` row in one logical operation.

**integration (using `fakeredis` + in-memory SQLite + `LocalFSObjectStore` rooted at `tmp_path`):**
- `POST /render` happy path: request body carries `source_code` + `content_hash` (as the browser-side flow forwards from the agent's response in this step); controller writes source to ObjectStore at `renders/{content_hash}/source.py`, renders (Taskiq InMemoryBroker), eventually reaches `final_ready`; `/artifacts/by-hash/...` serves the bytes that were `put` by the worker.
- `POST /render` cache-hit path: a previous Render with the same `effective_hash` exists; controller short-circuits, no Taskiq dispatch, response status is `final_ready` immediately.
- `POST /render` cache-drift path: Render row exists but blobs are missing (object store wiped); controller re-renders rather than returning broken URLs.
- `POST /render` with the legacy `scene_path` payload returns HTTP 422 (verifies the breaking-change criterion 12).
- `/artifacts/scenes/{scene_uuid}` resolves through `ScenesRepository.current_render_id → Render → preview/final key → object_store.open`.
- Two simultaneous identical-hash renders are deduped by the `layersense:lock:render:{hash}` `RenewableLock`; only one Taskiq task body runs to completion (verified by counting `manim` invocations via a fake `subprocess.run`).
- `RenewableLock` heartbeat keeps the lock alive past initial `ttl_ms` for a simulated long-running render — `redis.pttl(lock_key)` stays positive throughout (criterion 18).
- Worker crash mid-render (simulated via task cancellation) releases the lock within `ttl_ms + heartbeat_interval_ms`; a subsequent retry acquires successfully.
- `GET /artifacts/by-hash/{hash}/preview` returns 404 when no Render with that hash exists.
- Importing `layersense_controller.watcher` (or hitting the disabled-watcher startup path) raises `NotImplementedError` with a Step-7 pointer (criterion 16).
- First `POST /render` with no prior project creates `project WHERE slug='_default'`; second call reuses it (criterion 20).

### `layersense_agent`

**unit + integration:**
- `POST /api/v1/animation` returns `{ conversation_id, source_code, content_hash }`; `content_hash` matches `sha256(source_code.encode()).hexdigest()`. Existing VCR-backed test gets its assertions updated.
- The agent does not import `layersense_storage` (verified by grep).
- The agent does not write to disk under any code path (verified by patching `pathlib.Path.write_*` and `open` to raise; the test suite passes anyway).
- No assertions on `LAYERSENSE_SCENES_DIR` or `scene_path` remain anywhere.

### Existing tests

- `layersense_controller/tests/integration/test_router_api.py` — minor edits to send the new `/render` payload.
- `layersense_controller/tests/integration/test_render_jobs_fakeredis.py` — unaffected.
- `layersense_controller/tests/integration/test_render_tasks_taskiq.py` — minor edits; the worker now consumes object-store keys.
- `layersense_agent/tests/integration/test_animation_api.py` — assertion updates; cassettes likely need a refresh because the response shape changed.

### `e2e`

- `tests/e2e/test_dev_stack_e2e.py` — adjust to the new `/render` payload shape, but otherwise the live-stack flow is identical.

---

## Acceptance criteria

### PR 3a (`layersense_storage` package, standalone)

1. `layersense_storage/` exists as a uv workspace member; `uv sync` resolves cleanly.
2. `uv run --package layersense-storage pytest -m unit` passes.
3. `uv run --package layersense-storage pytest -m integration` passes (concurrent-writes test).
4. Coverage for `layersense_storage/src/**` ≥ 95% from unit + integration.
5. `grep -rn "layersense_storage" layersense_controller/src layersense_agent/src` returns no matches — 3a is unused by other packages, by design.
6. `keys.py` helpers reject keys containing `..` or absolute components (verified by test).
7. `LocalFSObjectStore.put` is atomic under crash simulation (verified by test).
8. `just lint` passes.
9. README and ROADMAP are unchanged in 3a.

### PR 3b (controller wiring, contract break, `cache.py` deletion)

10. `grep -rn "cache.py\|index.json\|LAYERSENSE_SCENES_DIR\|scenes_dir\|scene_path" layersense_controller/src layersense_agent/src layersense_frontend/src` returns no matches.
11. `layersense_controller/src/layersense_controller/cache.py` does not exist.
12. `POST /render` with the old `scene_path`-shaped payload returns `HTTP 422` (verified by an integration test that intentionally sends the old shape).
13. `POST /api/v1/animation` response includes `source_code` and `content_hash`, does not include `scene_path` (verified by an integration test).
14. The agent does not import `layersense_storage` (AST/grep check).
15. The agent does not write to disk under any code path (verified by patching `pathlib.Path.write_*` and `builtins.open` in write mode to raise; the test suite passes anyway).
16. `layersense_controller/src/layersense_controller/watcher.py` raises `NotImplementedError` on startup with a message pointing at Step 7 (verified by test).
17. Two simultaneous identical-hash renders are deduped by `RenewableLock` keyed `layersense:lock:render:{effective_hash}`; only one `manim` subprocess invocation occurs (verified by a `subprocess.run` spy in an integration test).
18. `RenewableLock` heartbeat extends TTL during a simulated long render (verified by an integration test that holds the lock past initial `ttl_ms` and observes the key still present).
19. `RenderControllerSettings` exposes `render_lock_ttl_ms`, `render_lock_heartbeat_interval_ms`, `render_lock_acquire_timeout_ms` as module-level defaults (per user preference, not as env-only fields).
20. A `_default` project row exists after first `POST /render` with no prior project; subsequent calls reuse it (idempotency verified).
21. `uv run --all-packages pytest -m unit` passes.
22. `uv run --all-packages pytest -m integration` passes.
23. `just e2e` passes against the local Docker stack.
24. `just test-e2e` passes (the assistant-friendly ephemeral compose run).
25. Coverage for `layersense_controller/src/**` does not regress; the `artifacts.py` façade is ≥ 90% covered.
26. `just lint` passes.
27. `docker-compose.yml` no longer mounts `./layersense_artifacts/code` on `agent` or `controller`. Only the storage volume is mounted.
28. After a fresh `just db_reset && just docker`, the system handles `generate → render → preview → final` end-to-end and writes blobs under `layersense_artifacts/storage/renders/{hash}/{preview,final}.mp4`.
29. README and ROADMAP no longer reference `cache/index.json`, `LAYERSENSE_SCENES_DIR`, or the legacy `scenes/<project>/<preview|final>/` tree.
30. `layersense_persistence` is the only writer to the `render` and `scene` tables. Verified by AST/grep: no other package imports `layersense_persistence.models`.

---

## Migration notes

- **No data migration script.** Single user, dev-stage. After this PR lands, run `just db_reset` (from Step 2's justfile addition) and `rm -rf layersense_artifacts/cache layersense_artifacts/code layersense_artifacts/scenes`. The new `layersense_artifacts/storage/` tree is created on first `put`.
- **Old artifacts are not preserved.** They were never durable in the first place (cache index drift bug, ephemeral generated files). Re-render anything you care about.
- This is acceptable specifically because answers (1) and (4) — single-user, single-developer, you — make it acceptable. State this in the PR description.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Watcher flow breaks because `scenes_dir` is gone | Watcher is **hard-disabled** in PR 3b: startup raises `NotImplementedError` with a Step-7 pointer. Watcher tests are `pytest.skip`-ped, not deleted. Project-aware redesign lands in Step 7. |
| Manim CLI requires a real on-disk path; per-render temp workdir adds a new failure surface | The `materialize_scene_source_for_manim` context manager owns workdir lifecycle with `tempfile.TemporaryDirectory`. Existing render-runtime test coverage catches mishandling. |
| Two `Render` rows pointing at the same blob keys; deletion of one row would orphan the other | Phrase deletion at the `RendersRepository` level as "delete row only", never "delete blob". Object store cleanup is explicit GC, not row-driven. Out of scope here; not implemented in PR 3b. |
| Taskiq worker container does not see the same object-store volume as the API container | Compose mounts `./layersense_artifacts/storage/` on `controller` and `controller-worker`. The agent has no storage mount (by design — agent has no storage awareness). Verified by acceptance criterion 27 + the e2e test. |
| `_default` project shim leaks into Step 4's design | Wipe migration `0003_drop_default_project_shim.py` lands as Step 4's first commit per `_default shim cleanup` section. PR 3b leaves a `# TODO(step-4)` grep anchor at the shim's call site. |
| `RenewableLock` heartbeat fires too slowly under scheduler pressure; lock TTL drains | Defaults give 3x margin (`heartbeat_interval_ms=10_000` vs `ttl_ms=30_000`). `RenewableLock.__aexit__` is CAS-safe — a TTL-drained lock cannot be released by a foreign holder. Worst case: two workers double-render identical content into the same content-addressed key. No corruption. |
| Cassette-backed agent tests churn because response shape changed | One-time cassette refresh via `just test_python_integration_refresh`. Expected; called out in PR 3b description. |

---

## Estimated shape

Two PRs (3a → 3b) per the "Delivery split" section above.

**PR 3a — `layersense_storage` package:**
- ~400 LOC src + ~400 LOC tests.
- No edits to other packages, frontend, compose, or docs.
- Self-contained library landing. Reviewable in isolation.

**PR 3b — controller wiring + breaking contract + watcher disable + `_default` shim + `RenewableLock` callsite:**
- `layersense_controller` edits: ~350 LOC delta (delete `cache.py`, add `artifacts.py`, edit `router.py` / `render.py` / `render_tasks.py` / `render_runtime.py` / `config.py`, wire `RenewableLock`, hard-disable watcher).
- `layersense_agent` edits: ~80 LOC delta.
- Frontend edits: ~30 LOC mechanical.
- Test edits across both backend packages: ~400 LOC delta plus cassette refresh.
- Docs: ~50 lines across README + ROADMAP.
- Total: ~1100 LOC delta. Coordinated breaking change; one atomic commit for the contract flip.

---

## Assumptions

1. Step 2 lands first or in lockstep. This plan assumes `layersense_persistence` exists with the schema as written.
2. Step 1 lands before this. Both `redis_lock` and the new `RenewableLock` primitive are reused — `RenewableLock` is the heartbeat-renewed mutex around the worker entrypoint per `Render dedup with heartbeat`.
3. `LAYERSENSE_STORAGE_ROOT` defaulting to `./layersense_artifacts/storage/` is fine. Confirmed.
4. The `_default` project shim is acceptable for one step. It exists only because Step 4 hasn't introduced explicit project/scene CRUD yet, and is wiped (not migrated) by Step 4's first commit per `_default shim cleanup`.
5. Watcher is **hard-disabled** (raise on startup) rather than maintained through this transition. It comes back in Step 7 as part of the agent-tier-2 design.
6. Cassette refresh on agent VCR tests is acceptable. The response shape changes (`source_code` instead of `scene_path`).
7. The agent returns raw source as a string in HTTP JSON. Manim files are 1–10 KB; HTTP transport is trivial. Confirmed (Option C, C1a).
8. The browser still talks to both agent and controller in this step. Step 4 retires the browser→agent direct call by introducing `POST /scenes/{id}/generate` on the controller as the single entry point. Holding the browser→agent call here keeps the PR scoped.
9. The `/render` HTTP-contract break is a hard cutover with no dual-shape support — see `Agent ↔ Controller contract change (BREAKING)`. Single-user dev stage; no external clients to migrate.
10. `RenewableLock` config (`render_lock_ttl_ms`, `render_lock_heartbeat_interval_ms`, `render_lock_acquire_timeout_ms`) lives as module-level defaults on `RenderControllerSettings`, per user preference for module constants over env-only fields. Tunable via env if needed; not required for default operation.

→ Correct any of these or I proceed to Step 4 (frontend revamp + explicit project/scene CRUD + Option C orchestration), which removes the `_default` shim **and** moves the agent call server-side so the browser only talks to the controller.
