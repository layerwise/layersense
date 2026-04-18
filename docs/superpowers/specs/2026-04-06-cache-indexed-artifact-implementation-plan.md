# Cache-Indexed Artifact Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace duplicate hash-named render cache files with an index-backed cache that points at canonical artifacts under `layersense_artifacts/scenes`, while adding stable hash and scene-UUID artifact routes.

**Architecture:** Keep Manim outputs as the only real media files, add a JSON cache index under `layersense_artifacts/cache/index.json`, and make the controller resolve both content-hash and scene-UUID URLs through that index. Preserve the existing preview/final incremental render flow, but stop copying rendered files to the artifact root.

**Tech Stack:** Python, FastAPI, Pydantic settings, pathlib, JSON persistence, pytest, requests/websocket smoke tests

---

### Task 1: Add cache index model and failing tests

**Files:**
- Modify: `layersense_controller/tests/test_cache.py`
- Create: `layersense_controller/src/layersense_controller/cache.py`

**Step 1: Write the failing tests**

Add tests for:

```python
def test_lookup_cache_miss_returns_no_artifacts(): ...

def test_store_and_lookup_cached_artifacts_round_trip(): ...

def test_scene_uuid_maps_to_latest_content_hash(): ...

def test_lookup_ignores_missing_indexed_files(): ...

def test_lookup_rejects_paths_outside_scenes_root(): ...
```

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_cache.py -v`

Expected: FAIL because the new cache index helpers do not exist yet.

**Step 3: Write minimal implementation**

Refactor `layersense_controller/src/layersense_controller/cache.py` to:

- keep `hash_file(path)`
- add a small typed record model or typed dict for cached artifacts
- add helpers to load and persist `layersense_artifacts/cache/index.json`
- add `lookup_cached_artifacts(content_hash)`
- add `lookup_content_hash_for_scene(scene_uuid)`
- add `store_cached_artifacts(content_hash, scene_uuid, scene_path, preview=None, final=None)`
- add validation that indexed paths are relative and resolve inside `settings.artifacts_dir / "scenes"`
- write the index atomically via temporary file + rename

Use a single JSON file. Do not introduce SQLite or a new service.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_cache.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/cache.py layersense_controller/tests/test_cache.py
git commit -m "feat(controller): add index-backed artifact cache"
```

### Task 2: Make render functions return canonical artifacts only

**Files:**
- Modify: `layersense_controller/src/layersense_controller/render.py`
- Modify: `layersense_controller/tests/test_render.py`

**Step 1: Write the failing tests**

Update render tests so they assert:

```python
assert target == artifacts_dir / "scenes" / "demo_project" / "preview" / "shots" / "scene_preview.mp4"
assert target == artifacts_dir / "scenes" / "_root" / "final" / "scene_final.mp4"
```

Add an assertion that no top-level `abc123_preview.mp4` or `abc123_final.mp4` file is created.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -v`

Expected: FAIL because `render_preview()` and `render_final()` still copy to hash-named files.

**Step 3: Write minimal implementation**

In `layersense_controller/src/layersense_controller/render.py`:

- remove the dependency on `preview_artifact()` and `final_artifact()`
- have `render_preview(scene_path, content_hash)` return the canonical `_raw_output_path(scene_path, "preview")`
- have `render_final(scene_path, content_hash)` return the canonical `_raw_output_path(scene_path, "final")`
- keep the function signatures unchanged for now to minimize caller churn

Do not change Manim invocation semantics.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/render.py layersense_controller/tests/test_render.py
git commit -m "refactor(controller): keep render outputs canonical"
```

### Task 3: Add by-hash and scene-UUID routes in router

**Files:**
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_controller/tests/test_router.py`

**Step 1: Write the failing tests**

Add tests for:

```python
def test_render_returns_cached_when_index_points_to_preview_and_final(): ...

def test_get_artifact_by_hash_preview_serves_canonical_file(): ...

def test_get_artifact_by_hash_final_serves_canonical_file(): ...

def test_get_scene_artifact_defaults_to_final_then_falls_back_to_preview(): ...

def test_get_scene_artifact_preview_query_prefers_preview(): ...
```

Assert websocket payloads use:

```python
"/artifacts/by-hash/<content_hash>/preview"
"/artifacts/by-hash/<content_hash>/final"
```

and that the scene route serves the latest cached version for a UUID.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: FAIL because the router still uses flat artifact filenames and lacks the new routes.

**Step 3: Write minimal implementation**

Refactor `layersense_controller/src/layersense_controller/router.py` to:

- replace flat-file cache lookup with index-backed helpers
- keep `POST /render` behavior returning `{"status": "cached"}` or `{"status": "queued"}`
- add `GET /artifacts/by-hash/{content_hash}/{kind}` where `kind` is `preview` or `final`
- add `GET /artifacts/scenes/{scene_uuid}` with `preview: bool = False`
- default the scene route to final if available, otherwise preview
- use hash routes in websocket event payloads

Add a small helper to derive `scene_uuid` from the scene filename:

```python
def scene_uuid_from_path(scene_path: Path) -> str:
    ...
```

Rule:

- `generated_<uuid>.py` -> `<uuid>`
- otherwise -> `scene_path.stem`

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/router.py layersense_controller/tests/test_router.py
git commit -m "feat(controller): serve artifacts via hash and scene routes"
```

### Task 4: Update render pipeline to persist cache metadata incrementally

**Files:**
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_controller/tests/test_router.py`

**Step 1: Write the failing tests**

Add tests for:

```python
def test_render_pipeline_stores_preview_after_preview_render(): ...

def test_render_pipeline_stores_final_after_final_render(): ...

def test_render_pipeline_renders_only_missing_final_when_preview_cached(): ...

def test_render_pipeline_renders_only_missing_preview_when_final_cached(): ...
```

Use monkeypatched cache-store helpers to verify the exact stored values.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: FAIL because the pipeline does not persist preview/final metadata to the index yet.

**Step 3: Write minimal implementation**

In `layersense_controller/src/layersense_controller/router.py`:

- after preview render, call `store_cached_artifacts(..., preview=preview_relative_path)`
- after final render, call `store_cached_artifacts(..., final=final_relative_path)`
- compute relative artifact paths before storing them
- preserve existing log and websocket sequencing

Keep the current background-task shape. Do not introduce a queue or worker system.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/router.py layersense_controller/tests/test_router.py
git commit -m "feat(controller): persist preview and final cache metadata"
```

### Task 5: Update smoke tests to assert the new artifact model

**Files:**
- Modify: `tests/smoke/test_dev_stack_smoke.py`

**Step 1: Write the failing tests**

Update smoke helpers to:

- derive `scene_uuid` from `conversation_id` or the generated filename
- poll `GET /artifacts/scenes/<scene_uuid>` and `GET /artifacts/scenes/<scene_uuid>?preview=true`
- optionally poll `GET /artifacts/by-hash/<content_hash>/preview` and `/final`

Replace any assumption that artifacts live at:

```python
f"/layersense_artifacts/{content_hash}_preview.mp4"
f"/layersense_artifacts/{content_hash}_final.mp4"
```

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke -v`

Expected: FAIL until the helpers and route assertions match the new router behavior.

**Step 3: Write minimal implementation**

In `tests/smoke/test_dev_stack_smoke.py`:

- replace `_artifact_candidates()` with helpers for the by-hash and scene routes
- keep websocket assertions broad enough to accept cached and queued flows
- assert returned URLs start with `/artifacts/by-hash/`
- add at least one check that `/artifacts/scenes/<scene_uuid>` resolves successfully

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke -v`

Expected: PASS in a running local stack

**Step 5: Commit**

```bash
git add tests/smoke/test_dev_stack_smoke.py
git commit -m "test: update smoke coverage for indexed artifact cache"
```

### Task 6: Update docs and verify the full change

**Files:**
- Modify: `docs/ROADMAP.md`
- Modify: `docs/plans/2026-03-07-layersense-architecture-design.md`
- Modify: `docs/plans/2026-03-09-layersense-hardening-followups.md`
- Modify: `README.md`

**Step 1: Write the failing doc assertions**

List the stale claims to remove:

- any mention of top-level `<hash>_preview.mp4` and `<hash>_final.mp4`
- any claim that cache artifacts are themselves the stored media files
- any route examples that no longer match `/artifacts/by-hash/...` and `/artifacts/scenes/...`

**Step 2: Update documentation**

Revise docs so they describe:

- canonical render storage under `layersense_artifacts/scenes/...`
- cache metadata under `layersense_artifacts/cache/index.json`
- content-addressed and scene-oriented artifact routes

Keep the docs concise and consistent with the approved design.

**Step 3: Run targeted controller tests**

Run: `uv run --all-packages pytest layersense_controller/tests/test_cache.py layersense_controller/tests/test_render.py layersense_controller/tests/test_router.py -v`

Expected: PASS

**Step 4: Run repo verification**

Run: `just lint`

Expected: PASS

Run: `just test`

Expected: PASS

**Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/plans/2026-03-07-layersense-architecture-design.md docs/plans/2026-03-09-layersense-hardening-followups.md README.md
git commit -m "docs: describe canonical artifact cache model"
```

## Notes For The Implementer

- Keep the implementation minimal: one JSON index file is enough.
- Do not add a database, ORM, or background queue.
- Preserve current preview/final websocket event ordering.
- Be careful with path validation; never trust indexed paths without constraining them to `layersense_artifacts/scenes`.
- If you discover now-unused flat artifact helpers, remove them after router and tests no longer depend on them.

## Suggested Verification Sequence

1. `uv run --all-packages pytest layersense_controller/tests/test_cache.py -v`
2. `uv run --all-packages pytest layersense_controller/tests/test_render.py -v`
3. `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`
4. `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py -m smoke -v`
5. `just lint`
6. `just test`
