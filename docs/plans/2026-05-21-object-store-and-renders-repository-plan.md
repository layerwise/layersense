# ObjectStore + RendersRepository Wiring — Implementation Plan

**Status:** Proposed
**Step in build order:** 3 of 9
**Depends on:** Step 1 (Redis lock) merged, Step 2 (`layersense_persistence`) merged
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

Step 2's schema is mostly sufficient. This step adds:

- **`render.scene_py_artifact_key`** is already present in Step 2's schema. Confirmed.
- **`render.preview_artifact_key`, `final_artifact_key`** already present. Confirmed.
- **One small migration `0002_add_render_log_key.py`**: add `render.log_artifact_key TEXT` so the captured Manim stdout/stderr is addressable. Useful for failure debugging — today `cache.py` has no equivalent and that hurts.

If Step 2's migration `0001` has not yet been finalized when this lands, fold the column into `0001` instead of shipping `0002`. Either is fine.

### Implicit project/scene creation

Until Step 4 introduces explicit project/scene CRUD, the controller's `POST /render` needs project and scene rows to attach the `Render` to. Strategy:

- Frontend continues to send `conversation_id` (existing field).
- Controller treats `conversation_id` as a **scene identifier shim** for now: on `POST /render`, look up `Scene WHERE id = conversation_id`. If absent, create a `Scene` under a **default `Project` named `"_default"`** (auto-created on first use; idempotent via `UPSERT slug='_default'`).
- The Scene's `name` is the conversation_id; `order_index` is the next int; `excalidraw_scene_json` and `prompt` are left empty until Step 4 makes them first-class. The agent does not yet know about scene_id.

This is deliberately ugly. It is a 30-line shim that lets Step 3 ship without dragging Step 4's CRUD into the same PR. The shim disappears in Step 4.

**Push-back surfaced explicitly:** an alternative is to introduce a real `POST /scenes` endpoint in this PR and have the frontend call it before `/render`. That doubles the PR size and forces frontend changes I committed to deferring to Step 4. The shim is the right call given the build order; it lives for one step.

### Agent ↔ Controller contract change

Today:

```
browser → agent: POST /api/v1/animation { excalidraw_scene, prompt }
  agent → writes ./layersense_artifacts/code/generated_<uuid>.py
  agent → returns { conversation_id, scene_path: "./layersense_artifacts/code/generated_<uuid>.py" }

browser → controller: POST /render { scene_path, conversation_id, cli_flags? }
  controller → reads scene_path from the shared host-mounted disk
```

After this step:

```
browser → agent: POST /api/v1/animation { excalidraw_scene, prompt }       (unchanged callers; new response)
  agent → returns { conversation_id, source_code: "<python source>", content_hash }
  agent → has zero filesystem touches; does not import layersense_storage

browser → controller: POST /render { conversation_id, source_code, content_hash, cli_flags? }
  controller → ObjectStore.put(render_source_key(content_hash), source_code.encode())
  controller → creates Render row, dispatches Taskiq job

worker → ObjectStore.get(render_source_key) → /tmp/layersense-renders/<render_id>/scene.py → manim
worker → ObjectStore.put_stream(render_preview_key, ...), then render_final_key
```

**Notes on this contract:**

- The agent's response now contains **raw Python source as a string**, not a key. Manim files are tiny (typically 1–10 KB); HTTP transport is fine.
- The browser passes the source bytes verbatim from the agent's response into `POST /render`. It does not interpret or modify them. (In Step 4 this changes again: the browser stops talking to the agent at all, the controller orchestrates both calls server-side. Step 3 keeps today's two-call browser flow to limit blast radius.)
- The controller is the **only** writer to the ObjectStore. The agent does not import `layersense_storage`.
- The shared host-mounted `layersense_artifacts/code/` volume is removed from `docker-compose.yml`. The agent service has no mounted volumes after this step.
- The controller still needs to materialize the source as a real file on disk for the Manim CLI subprocess (Manim does not read from stdin). It does so to a per-render temp dir under `LAYERSENSE_RENDER_WORKDIR` (default `/tmp/layersense-renders/<render_id>/`), cleaned up after the render finishes. This is ephemeral, not shared, and not the object store.
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

The `cache_index` Redis lock from Step 1 is **deleted** in this PR — there is nothing left to lock around once `cache.py` is gone. The render-dedup concern is naturally handled: the SQLite `UNIQUE(content_hash)` semantics are not enforced (multiple Render rows may share a content_hash), but the `find_by_content_hash` short-circuit in step 4 above means redundant work is avoided. Two simultaneous identical renders may both proceed once and produce byte-identical blobs at the same key — last-write-wins on identical content, no corruption.

If you want strict dedup of in-flight renders, add a Redis lock keyed `layersense:lock:render:{effective_hash}` around the Taskiq task body. **Recommended**, and cheap given Step 1 already shipped the primitive. Add it.

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
- `layersense_controller/src/layersense_controller/watcher.py` — left alone for now (the watcher path is documented as deferred; if it breaks because `scenes_dir` is gone, mark it `# disabled until project-aware watcher` and skip its tests).
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
- `POST /render` happy path: agent has pre-populated `scene_source_key`; controller renders (Taskiq InMemoryBroker), eventually reaches `final_ready`; `/artifacts/by-hash/...` serves the bytes that were `put` by the worker.
- `POST /render` cache-hit path: a previous Render with the same `effective_hash` exists; controller short-circuits, no Taskiq dispatch, response status is `final_ready` immediately.
- `POST /render` cache-drift path: Render row exists but blobs are missing (object store wiped); controller re-renders rather than returning broken URLs.
- `/artifacts/scenes/{scene_uuid}` resolves through `ScenesRepository.current_render_id → Render → preview/final key → object_store.open`.
- Two simultaneous identical-hash renders are deduped by the `layersense:lock:render:{hash}` Redis lock; only one Taskiq task body runs to completion (verified by counting `manim` invocations via a fake `subprocess.run`).
- `GET /artifacts/by-hash/{hash}/preview` returns 404 when no Render with that hash exists.

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

1. `grep -rn "cache.py\|index.json\|LAYERSENSE_SCENES_DIR\|scenes_dir" layersense_controller/src layersense_agent/src` returns no matches.
2. `layersense_controller/src/layersense_controller/cache.py` does not exist.
3. `uv run --all-packages pytest -m unit` passes.
4. `uv run --all-packages pytest -m integration` passes.
5. `just e2e` passes against the local Docker stack.
6. `just test-e2e` passes (the assistant-friendly ephemeral compose run).
7. Coverage for `layersense_storage/src/**` ≥ 95% from unit + integration.
8. Coverage for `layersense_controller/src/**` does not regress; the `artifacts.py` façade is ≥ 90% covered.
9. `just lint` passes.
10. `docker-compose.yml` no longer mounts `./layersense_artifacts/code` on `agent` or `controller`. Only the storage volume is mounted.
11. After a fresh `just db_reset && just docker`, the system handles `generate → render → preview → final` end-to-end and writes blobs under `layersense_artifacts/storage/renders/{hash}/{preview,final}.mp4`.
12. README and ROADMAP no longer reference `cache/index.json`, `LAYERSENSE_SCENES_DIR`, or the legacy `scenes/<project>/<preview|final>/` tree.
13. `layersense_persistence` is the only writer to the `render` and `scene` tables. Verified by AST/grep: no other package imports `layersense_persistence.models`.

---

## Migration notes

- **No data migration script.** Single user, dev-stage. After this PR lands, run `just db_reset` (from Step 2's justfile addition) and `rm -rf layersense_artifacts/cache layersense_artifacts/code layersense_artifacts/scenes`. The new `layersense_artifacts/storage/` tree is created on first `put`.
- **Old artifacts are not preserved.** They were never durable in the first place (cache index drift bug, ephemeral generated files). Re-render anything you care about.
- This is acceptable specifically because answers (1) and (4) — single-user, single-developer, you — make it acceptable. State this in the PR description.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Watcher flow breaks because `scenes_dir` is gone | Watcher is documented as deferred. Add a clear `NotImplementedError` raise on watcher startup with a pointer to "watcher needs project-aware redesign in Step 7". Tests for watcher are skipped, not deleted. |
| Manim CLI requires a real on-disk path; per-render temp workdir adds a new failure surface | The `materialize_scene_source_for_manim` context manager owns workdir lifecycle with `tempfile.TemporaryDirectory`. Existing render-runtime test coverage catches mishandling. |
| Two `Render` rows pointing at the same blob keys; deletion of one row would orphan the other | Phrase deletion at the `RendersRepository` level as "delete row only", never "delete blob". Object store cleanup is explicit GC, not row-driven. Out of scope here; not implemented in this PR. |
| Taskiq worker container does not see the same object-store volume as the API container | Compose mounts `./layersense_artifacts/storage/` on `controller`, `controller-worker`, and `agent`. Verified by acceptance criterion 10 + the e2e test. |
| Implicit `_default` project shim leaks into Step 4's design | Step 4's first task is "delete the shim, replace with explicit project CRUD". Document this at the shim's call site with a TODO referencing Step 4. |
| Cassette-backed agent tests churn because response shape changed | One-time cassette refresh via `just test_python_integration_refresh`. Expected; called out in PR description. |

---

## Estimated shape

Larger PR than Steps 1 or 2 — this is the substrate change.

- `layersense_storage` new package: ~400 LOC src + ~400 LOC tests.
- `layersense_controller` edits: ~300 LOC delta (delete cache.py, add artifacts.py, edit router/render/render_tasks/render_runtime/config).
- `layersense_agent` edits: ~80 LOC delta.
- Test edits across both backend packages: ~300 LOC delta plus cassette refresh.
- Docs: ~50 lines across README + ROADMAP.

Total: roughly 1500 LOC delta, mostly mechanical once the design lands. One PR or split into two (storage package alone, then wiring) is acceptable. Recommend one PR for review coherence.

---

## Assumptions

1. Step 2 lands first or in lockstep. This plan assumes `layersense_persistence` exists with the schema as written.
2. Step 1 lands before this. The Redis lock primitive is reused for `layersense:lock:render:{hash}`.
3. `LAYERSENSE_STORAGE_ROOT` defaulting to `./layersense_artifacts/storage/` is fine. Confirmed.
4. The `_default` project shim is acceptable for one step. It exists only because Step 4 hasn't introduced explicit project/scene CRUD yet.
5. Watcher gets disabled (raise on startup) rather than maintained through this transition. It comes back in Step 7 as part of the agent-tier-2 design.
6. Cassette refresh on agent VCR tests is acceptable. The response shape changes (`source_code` instead of `scene_path`).
7. The agent returns raw source as a string in HTTP JSON. Manim files are 1–10 KB; HTTP transport is trivial. Confirmed (Option C, C1a).
8. The browser still talks to both agent and controller in this step. Step 4 retires the browser→agent direct call by introducing `POST /scenes/{id}/generate` on the controller as the single entry point. Holding the browser→agent call here keeps the PR scoped.

→ Correct any of these or I proceed to Step 4 (frontend revamp + explicit project/scene CRUD + Option C orchestration), which removes the `_default` shim **and** moves the agent call server-side so the browser only talks to the controller.
