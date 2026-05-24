# Project Export — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md`. Canonical source-key form: `renders/{content_hash}/source.py`.
**Amendment (2026-05-22):** Endpoint changed to GET. Scope narrowed to source-only (no renders). Streaming removed. Per design decision #19 and audit findings 6.1-6.2.
**Step in build order:** 6 of 9
**Depends on:** Step 2 (`layersense_persistence`) merged, Step 3 (`layersense_storage` + `ObjectStore`) merged, Step 4 (Project/Scene CRUD + controller orchestration) merged
**Unblocks:** Step 7 (multi-file project + components library), Step 8 (S3 backend)

---

## Why this step

The user has a project with multiple scenes, each with a successful render. They want to:

1. **Hand the project to another machine** — open it in a real IDE, run it with vanilla Manim, push it to GitHub.
2. **Archive a snapshot** — a zip is a durable, self-contained record of what was generated at a point in time.
3. **Share with collaborators** — someone with `pip install manim` should be able to run the scenes without LayerSense.

This step is cheap relative to its value: the data is already in the DB and the object store. The export endpoint is a read-only aggregation of existing rows and blobs. No new durable state is written. No new background tasks are needed. The only new infrastructure is a zip-building utility and a single HTTP endpoint.

**Why now (after Step 4, before Step 7):** Step 4 establishes the Project/Scene/Render model and the object store. Step 6 is the first "harvest" of that model. Step 7 will expand the project to a multi-file structure; the export format defined here should be forward-compatible with that (the `scenes/` directory layout already anticipates it).

---

## Scope

### In scope

1. `GET /api/v1/projects/{project_id}/export` — synchronous, returns a `application/zip` response with `Content-Disposition: attachment; filename="{project_slug}.zip"`.
2. Zip contents:
   - `scenes/{order_index:03d}_{scene_slug}.py` — each scene's latest successful render's source (from `Render.scene_py_artifact_key` via ObjectStore).
   - `manim.cfg` — the project's `default_render_config` materialized as a Manim INI config file.
   - `README.md` — project name, scene list, LayerSense provenance footer.
   - `requirements.txt` — pins the Manim version used at render time (see schema delta below).
   - `manifest.json` — structured metadata: project id/name/slug, per-scene entries (scene id, name, order_index, render id, content_hash, manim_version, source key), `skipped_scenes` array, `generated_at` ISO timestamp.
3. Export is source-only: .py scene files + manifest.json + manim.cfg. No mp4 renders included (design decision #19). Streaming zip is not needed — source-only exports are small. The GET method enables <a href=...> download links in the frontend without JavaScript fetch/blob handling.
4. Small schema addition: add `Render.manim_version TEXT NULL` column. The worker records the Manim version string at render time. Used by `requirements.txt` generation.
5. Frontend: "Export" button on the project detail page header. Triggers a direct browser download via `<a href="/api/v1/projects/{id}/export" download>`.

### Out of scope

- Including rendered mp4s in export.
- Project import / round-trip (Step 7+).
- Multi-file project structure (Step 7 will extend the zip layout; this step defines the baseline).
- Scheduled / background export jobs. The endpoint is synchronous.
- Export of Frame-level data beyond what's embedded in the scene source.
- Auth / signed download URLs. Single-user assumption holds.

---

## Design

### Endpoint shape

```
GET /api/v1/projects/{project_id}/export

→ 200 OK
  Content-Type: application/zip
  Content-Disposition: attachment; filename="my-project.zip"
  <zip bytes>

→ 404 if project not found
```

**Why `GET`:** Export is source-only: .py scene files + manifest.json + manim.cfg. No mp4 renders included (design decision #19). Streaming zip is not needed — source-only exports are small. The GET method enables <a href=...> download links in the frontend without JavaScript fetch/blob handling.

**Synchronous response.** The zip is built in memory from small Python source files (typically 1–10 KB each). A 20-scene project is ~200 KB of source; in-memory is trivially fast.

### Zip layout

```
{project_slug}.zip
├── manifest.json
├── README.md
├── requirements.txt
├── manim.cfg
└── scenes/
    ├── 001_intro.py
    ├── 002_main_animation.py
    └── 003_outro.py
```

### File contents

#### `scenes/{order_index:03d}_{scene_slug}.py`

Raw Python source bytes from `ObjectStore.get(render.scene_py_artifact_key)`. No transformation. The file is the exact source that was rendered.

**Scene slug derivation:** derived on-the-fly from `scene.name` at export time. No `scene.slug` column is added (see Assumptions). Algorithm:

```python
import re, unicodedata

def slugify(name: str) -> str:
    # Normalize unicode → ASCII approximation
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    # Lowercase, replace non-alphanumeric runs with underscore
    name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return name or "scene"
```

**Collision handling:** if two scenes produce the same slug (e.g., "Scene 1" and "scene_1"), append `_{order_index}` as a disambiguator. The `order_index` prefix already makes filenames unique in practice, but the slug itself should be stable and human-readable.

#### `manim.cfg`

Manim uses a standard INI-format config file. The project's `default_render_config_json` is materialized into the `[CLI]` section. Unknown keys are passed through; the user is responsible for validity.

```ini
# Generated by LayerSense — do not edit manually
# Project: My Project
# Exported: 2026-05-21T14:30:00Z

[CLI]
quality = medium_quality
preview = False
save_last_frame = False
# ... other keys from default_render_config_json
```

If `default_render_config_json` is `{}` (the default), emit a minimal `manim.cfg` with a comment explaining it uses Manim's built-in defaults.

#### `README.md`

Minimal. Human-editable before sharing.

```markdown
# My Project

Generated by [LayerSense](https://github.com/layerwise/layersense) on 2026-05-21.

## Scenes

| # | File | Scene Name |
|---|------|------------|
| 1 | scenes/001_intro.py | Intro |
| 2 | scenes/002_main_animation.py | Main Animation |
| 3 | scenes/003_outro.py | Outro |

## Running

```bash
pip install -r requirements.txt
manim scenes/001_intro.py Intro
```

## Notes

- Scenes with no successful render are not included (see `manifest.json` → `skipped_scenes`).
- Re-render all scenes: `for f in scenes/*.py; do manim "$f"; done`
```

#### `requirements.txt`

```
manim==0.18.1
```

The version is read from `Render.manim_version` of the scene's latest successful render. If multiple scenes have different `manim_version` values (unlikely but possible after an upgrade), use the most common version and note the discrepancy in `manifest.json`. If `manim_version` is `NULL` (renders predating this step), fall back to `manim>=0.18` with a comment.

#### `manifest.json`

```json
{
  "layersense_export_version": "1",
  "generated_at": "2026-05-21T14:30:00Z",
  "project": {
    "id": "proj_abc123",
    "name": "My Project",
    "slug": "my-project"
  },
  "scenes": [
    {
      "id": "scn_001",
      "name": "Intro",
      "order_index": 0,
      "slug": "intro",
      "file": "scenes/001_intro.py",
      "render_id": "rnd_xyz",
      "content_hash": "abc123...",
      "manim_version": "0.18.1",
      "scene_py_artifact_key": "renders/abc123.../source.py"
    }
  ],
  "skipped_scenes": [
    {
      "id": "scn_002",
      "name": "Draft Scene",
      "order_index": 1,
      "reason": "no_successful_render"
    }
  ],
  "export_scope": "source_only"
}
```

### Scenes with no successful render

**Recommendation: skip and list in `manifest.json` → `skipped_scenes` with `reason: "no_successful_render"`.**

Rationale: an empty stub `.py` would be confusing — it would look like a real scene but fail to render. The manifest makes the omission explicit and machine-readable. The README also notes it in plain text.

A scene is "skipped" if:
- It has no `Render` rows at all, OR
- All its `Render` rows have `status` in `{queued, generating, failed}` (no `preview_ready` or `final_ready`).

The "latest successful render" is the most recent `Render` row for the scene with `status IN ('preview_ready', 'final_ready')`, ordered by `created_at DESC`.

### Export size and in-memory zip

Export is source-only: .py scene files + manifest.json + manim.cfg. No mp4 renders included (design decision #19). Streaming zip is not needed — source-only exports are small. The GET method enables <a href=...> download links in the frontend without JavaScript fetch/blob handling.

Build the zip entirely in memory using `zipfile.ZipFile` with `io.BytesIO`. Source files are small; a 50-scene project is ~500 KB. Return as `Response(content=buf.getvalue(), media_type="application/zip", ...)`.

### `Render.manim_version` schema delta

Add `manim_version TEXT NULL` to the `Render` table.

The worker records the version at render time:

```python
import manim
render.manim_version = manim.__version__
```

This is a one-line addition to the worker's render task, after the Manim import is already present.

If local renders predate this schema shape, `manim_version` may be `NULL`. The export falls back to `manim>=0.18` in `requirements.txt` with a comment. Given first-version ergonomics, resetting local DB state is also acceptable.

### Generation flow (step by step)

```
1. Controller receives GET /api/v1/projects/{project_id}/export
2. ProjectsRepository.get(project_id) → 404 if missing
3. ScenesRepository.list_by_project(project_id, order_by=order_index) → ordered scene list
4. For each scene:
     a. RendersRepository.latest_successful(scene_id) → Render | None
     b. If None → add to skipped_scenes list, continue
     c. ObjectStore.get(render.scene_py_artifact_key) → source bytes
     d. Derive scene_slug from scene.name (slugify)
     e. Build zip entry: scenes/{order_index:03d}_{scene_slug}.py
5. Build manim.cfg from project.default_render_config_json
6. Build README.md from project name + scene table
7. Build requirements.txt from render.manim_version values
8. Build manifest.json
9. Return zip as Response (in-memory)
```

### Frontend integration

**Button placement:** project detail page header, alongside "New Scene". Label: "Export ZIP".

**Implementation:**

```tsx
<a
  href={`/api/v1/projects/${projectId}/export`}
  download={`${project.slug}.zip`}
>
  Export ZIP
</a>
```

This is a plain anchor tag — no JavaScript, no spinner, no state. The browser handles the download natively. The `download` attribute hints the filename.

**No progress indicator** for the default path. The zip is built in milliseconds for source-only exports.

---

## File-level changes

### `layersense_persistence`

- `layersense_persistence/src/layersense_persistence/repositories/renders.py` — add `latest_successful(scene_id: str) -> Render | None` query method.
- `layersense_persistence/src/layersense_persistence/schemas.py` — add `manim_version: str | None` to `RenderSchema`.

### `layersense_controller`

**New:**

- `layersense_controller/src/layersense_controller/api/export.py` — FastAPI router with the single `GET /api/v1/projects/{project_id}/export` endpoint. Thin: delegates to `export_service.py`.
- `layersense_controller/src/layersense_controller/services/export_service.py` — pure business logic: assembles zip bytes from repositories + object store. No FastAPI imports. Testable in isolation.
- `layersense_controller/src/layersense_controller/services/zip_builder.py` — thin wrapper around `zipfile.ZipFile` + `io.BytesIO`. Provides a clean `ZipBuilder` context manager that accumulates entries and returns bytes. Keeps `export_service.py` free of `zipfile` details.
- `layersense_controller/src/layersense_controller/services/manim_cfg.py` — `render_config_to_manim_cfg(config: dict) -> str`. Pure function, no I/O. Converts `default_render_config_json` to INI string.
- `layersense_controller/tests/unit/test_export_service.py` — unit tests for zip building, manim.cfg generation, slug derivation, collision handling, skipped-scene logic.
- `layersense_controller/tests/integration/test_export_api.py` — integration tests using `TestClient(app)` + in-memory SQLite + `LocalFSObjectStore(tmp_path)`.

**Modified:**

- `layersense_controller/src/layersense_controller/main.py` — register `export.router`.
- `layersense_controller/src/layersense_controller/render_tasks.py` (or `render_tasks_generate.py`) — record `manim_version` on the `Render` row after render completes.

### `layersense_frontend`

**Modified:**

- `src/routes/ProjectDetailRoute.tsx` — add "Export ZIP" anchor in the page header.
- `src/api.ts` — optionally add a typed `exportProject(projectId, includeRenders?)` helper that constructs the URL (not strictly needed since it's a plain anchor, but useful for tests).
- `src/types.ts` — no changes needed (export is a download, not a JSON response).

### Docs

- `README.md` — add "Project Export" to the "Current Status" section.
- `docs/ROADMAP.md` — mark Step 6 as in-progress / complete.

---

## Test plan

### Unit tests (`layersense_controller/tests/unit/test_export_service.py`)

All tests use in-memory fakes (no filesystem, no HTTP).

**`manim_cfg.py`:**
- Empty config dict → minimal `[CLI]` section with comment.
- Config with known keys (`quality`, `preview`, `save_last_frame`) → correct INI output.
- Config with unknown keys → passed through without error.
- Config with nested values → flattened or stringified (document the behavior).

**`zip_builder.py`:**
- Add text entry → bytes in zip match input.
- Add binary entry → bytes in zip match input.
- Multiple entries → all present, no duplicates.
- `ZipBuilder` context manager → `BytesIO` is closed after `__exit__`.

**`export_service.py`:**
- Project with 3 scenes, all with successful renders → zip contains `scenes/001_*.py`, `002_*.py`, `003_*.py`, `manim.cfg`, `README.md`, `requirements.txt`, `manifest.json`. No extra entries.
- Project with 1 scene missing a render → that scene appears in `manifest.json` → `skipped_scenes`; zip has 2 scene files, not 3.
- Project with all scenes skipped → zip contains only `manim.cfg`, `README.md`, `requirements.txt`, `manifest.json`; `skipped_scenes` has all scenes.
- Scene name with unicode → slug is ASCII, non-empty, no path traversal characters.
- Two scenes with identical slugs → disambiguated by `_{order_index}` suffix.
- `manim_version` is `NULL` on all renders → `requirements.txt` contains `manim>=0.18` with comment.
- `manim_version` differs across scenes → most common version used; discrepancy noted in `manifest.json`.
- `manifest.json` is valid JSON and matches the schema (use `pydantic` model to validate).

**Slug derivation (`slugify`):**
- ASCII name → lowercase, spaces to underscores.
- Unicode name (e.g., "Scène 1") → ASCII approximation.
- Name with only special characters → falls back to `"scene"`.
- Empty string → `"scene"`.
- Name that is already a valid slug → unchanged.

### Integration tests (`layersense_controller/tests/integration/test_export_api.py`)

Use `TestClient(app)` + in-memory SQLite (via `layersense_persistence` test fixtures) + `LocalFSObjectStore(tmp_path)`.

**Setup helper:** `create_project_with_scenes(n_scenes, n_with_renders)` — creates a project, `n_scenes` scenes, and for `n_with_renders` of them, a `Render` row with `status="final_ready"` and a real `.py` file written to the test object store.

**Tests:**

- `GET /api/v1/projects/{id}/export` happy path (3 scenes, all rendered):
  - Response status 200.
  - `Content-Type: application/zip`.
  - `Content-Disposition` contains `filename="{project_slug}.zip"`.
  - Unzip response body; assert `scenes/001_*.py`, `002_*.py`, `003_*.py` exist.
  - Assert `manifest.json` is valid JSON with `scenes` length 3 and `skipped_scenes` length 0.
  - Assert `manim.cfg` is non-empty.
  - Assert `README.md` contains the project name.
  - Assert `requirements.txt` contains `manim`.
  - Assert each `.py` file content matches what was written to the object store.

- Mixed: 2 rendered, 1 not:
  - Zip has 2 scene files.
  - `manifest.json` → `skipped_scenes` has 1 entry with `reason: "no_successful_render"`.

- All scenes skipped:
  - Zip has no `scenes/` entries.
  - `manifest.json` → `skipped_scenes` has all scenes.
  - Response is still 200 (not an error).

- Project not found:
  - `GET /api/v1/projects/nonexistent/export` → 404.

- Object store blob missing for a scene that has a `Render` row (drift):
  - Scene is treated as skipped (graceful degradation); logged as a warning.
  - Response is still 200; `skipped_scenes` includes the scene with `reason: "source_blob_missing"`.

### e2e (`tests/e2e/test_dev_stack_e2e.py`)

Add one e2e test:

```python
@pytest.mark.e2e
def test_project_export_downloads_valid_zip(controller_client):
    # 1. Create project + scene via API
    # 2. POST /scenes/{id}/generate, poll until final_ready
    # 3. GET /projects/{id}/export
    # 4. Assert response is a valid zip
    # 5. Unzip; assert scenes/*.py exists and is non-empty
    # 6. Assert manifest.json is valid JSON
    # 7. Assert requirements.txt contains "manim"
    # 8. Assert manim.cfg exists
```

The "exported zip can be rendered with vanilla Manim" criterion is verified manually (not automated in CI, since it requires a Manim install). Document this in the acceptance criteria.

---

## Acceptance criteria

1. `GET /api/v1/projects/{id}/export` returns `200 application/zip` for a project with at least one successfully rendered scene.
2. Unzipping the response produces `scenes/*.py`, `manim.cfg`, `README.md`, `requirements.txt`, `manifest.json`.
3. Each `scenes/*.py` file is byte-identical to the source stored in the object store at `Render.scene_py_artifact_key`.
4. `manifest.json` is valid JSON parseable by the `ManifestSchema` Pydantic model.
5. `requirements.txt` contains a `manim` pin or range.
6. `manim.cfg` is a valid INI file with a `[CLI]` section.
7. Scenes with no successful render appear in `manifest.json` → `skipped_scenes` and are absent from `scenes/`.
8. `uv run --all-packages pytest -m unit` passes; `test_export_service.py` coverage ≥ 95%.
9. `uv run --all-packages pytest -m integration` passes; `test_export_api.py` coverage ≥ 90%.
10. `just lint` passes.
11. `grep -rn "export" layersense_frontend/src/routes/ProjectDetailRoute.tsx` returns the export anchor element.
12. **Manual acceptance:** unzip the export on a machine with `pip install manim==<pinned version>`; run `manim scenes/001_*.py <ClassName>`; render succeeds without LayerSense running.
13. `Render.manim_version` is recorded by the worker for all new renders after this step lands.
14. `GET /api/v1/projects/nonexistent/export` returns 404.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `ObjectStore.get` raises `ObjectNotFoundError` for a scene that has a `Render` row (blob drift after manual storage wipe) | Catch `ObjectNotFoundError` per scene in `export_service.py`; treat as skipped with `reason: "source_blob_missing"`. Log a warning. Never let one missing blob abort the whole export. |
| Scene name slugification produces empty string or path-traversal characters | `slugify()` has an explicit fallback to `"scene"` and strips all non-alphanumeric characters. Unit-tested with adversarial inputs. |
| Two scenes with identical slugs produce a filename collision in the zip | Disambiguate with `_{order_index}` suffix. The `order_index` prefix already makes the full filename unique; the slug collision only affects readability, not correctness. |
| `manim_version` is NULL for all existing renders (predating this step) | Graceful fallback to `manim>=0.18` in `requirements.txt` with a comment. Not an error. |
| `default_render_config_json` contains keys that are not valid Manim CLI options | Pass through without validation. The user is responsible for the config. Document this in the README and in the `manim.cfg` header comment. |
| The export endpoint is slow for large projects (many scenes, large source files) | Source files are 1–10 KB each. 50 scenes = ~500 KB. Object store reads are local filesystem. Total time is well under 1s. No async needed. |

---

## Estimated shape

- `layersense_persistence` delta: ~60 LOC (schema/model update + repository method + schema field).
- `layersense_controller` new src: ~350 LOC (`export.py`, `export_service.py`, `zip_builder.py`, `manim_cfg.py`).
- `layersense_controller` test: ~400 LOC (`test_export_service.py`, `test_export_api.py`).
- `layersense_controller` modified src: ~30 LOC (register router, record `manim_version` in worker).
- `layersense_frontend` delta: ~40 LOC (export anchor + optional helper).
- Docs: ~30 LOC.

**Total: ~910 LOC delta.** Single PR; no split needed.

---

## Assumptions

Surface these explicitly — push back before implementation begins.

1. **`GET` for the export endpoint.** Export is source-only and small, and `GET` enables direct anchor-tag downloads. → *Confirmed by amendment 2026-05-22.*

2. **Source-only export.** The zip contains .py scene files, `manifest.json`, `manim.cfg`, `README.md`, and `requirements.txt`; no mp4 renders are included. → *Confirmed by amendment 2026-05-22.*

3. **No streaming zip path.** Source-only exports are small enough for in-memory zip construction. → *Confirmed by amendment 2026-05-22.*

4. **Scenes with no successful render are skipped (not stubbed).** An empty stub `.py` would be confusing. The manifest makes the omission explicit. → *Push back if you want a stub file instead.*

5. **`Render.manim_version` is added in this step.** This is a small schema delta. Existing local renders may have `NULL`; the export falls back gracefully, and resetting local DB state remains acceptable. → *Push back if you want to defer this column to a later step.*

6. **Scene slug is derived on-the-fly from `scene.name`; no `scene.slug` column is added.** The derivation is deterministic and collision-safe. Adding a stored slug would add unnecessary schema/uniqueness complexity for first-version ergonomics. → *Push back if you want a stored slug.*

7. **File naming convention: `scenes/{order_index:03d}_{scene_slug}.py`.** The `order_index` prefix ensures natural sort order and uniqueness. The slug provides human readability. → *Push back if you prefer `scenes/{scene_slug}.py` (no prefix) or a different convention.*

8. **README content is minimal.** Project name, scene table, run instructions, provenance footer. No prompts, no frame augmentations, no render history. The user can hand-edit before sharing. → *Push back if you want richer README content.*

9. **No `zipstream-ng` dependency.** Stdlib `zipfile` + `BytesIO` is sufficient for source-only exports. → *Confirmed by amendment 2026-05-22.*

10. **The "exported zip can be rendered with vanilla Manim" criterion is verified manually, not in CI.** Automating this would require a Manim install in the test environment, which is a significant CI overhead. → *Push back if you want this automated.*

11. **`POST /render` is not used by the export endpoint.** Export is read-only; it does not trigger new renders. Scenes with no successful render are skipped. → *Correct me if you want the export to trigger renders for unrendered scenes.*

→ Correct any of these or I proceed to implementation.
