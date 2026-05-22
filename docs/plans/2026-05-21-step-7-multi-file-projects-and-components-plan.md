# Multi-File Projects + Components Library (Agent Tier 2) — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md`. Migration number is `0006` per the normalized sequence (Step 5 = 0004, Step 6 = 0005, Step 7 = 0006). This step's `projects/{project_id}/...` ObjectStore tree is the mutable working copy; it **coexists with** the existing `renders/{content_hash}/...` immutable snapshot tree (per overview "Storage model"). It does not replace it. **DQ1 RESOLVED (2026-05-22, design decision #16):** The agent stays pure-function with inline FileBundle response. No tool surface. Controller writes all files to ObjectStore. Option C preserved. Re-evaluate only if Step 9 friction log shows this is untenable.
**Step in build order:** 7 of 9
**Depends on:** Step 2 (`layersense_persistence`), Step 3 (`layersense_storage` + ObjectStore), Step 4 (frontend revamp + controller orchestration), Step 5 (agent refinement), Step 6 (project export)
**Unblocks:** Step 8 (S3-compatible ObjectStore backend), Step 9 (OpenCode-style agentic runtime, speculative)

**Amendment (2026-05-22):** DQ1 resolved: inline FileBundle (decision #16). Migration numbering corrected to 0006. Cache-hit ordering fixed (agent always called for /generate). __init__.py marked as materialization-only. Hash terminology unified. Per audit findings 7.1-7.5.

---

## Why this step

After Step 4, every scene is a self-contained `.py` file generated from scratch. The agent has no memory of what it built before, no access to shared utilities, and no way to compose with primitives it already created. Every prompt starts from zero.

This step makes a project a real Python package. Scenes can `from components.spring import animated_spring`. The agent receives the project's existing component files as inline context, can create new components, and can update existing ones. The controller writes the agent's output back to the ObjectStore atomically. The watcher returns — now project-aware — enabling a "render-on-save" loop when the user edits component files in an external IDE.

**User behaviors this unlocks:**

- "Create a reusable `animated_spring` component, then use it in three scenes." The agent creates `components/spring.py` on the first prompt; subsequent scene prompts receive that file as context and can import it.
- "Refine the spring component so it bounces faster." The agent receives the current `components/spring.py`, edits it, and the controller writes the updated file back. All scenes that import it can be re-rendered.
- "I edited `components/spring.py` in VS Code." The watcher detects the local file change, syncs it to the ObjectStore, and re-renders affected scenes automatically.
- "Show me what components this project has." The frontend's new Components tab lists the project's component files.

---

## Scope

### In scope

1. **Project-as-package ObjectStore layout**: `scenes/`, `components/`, `assets/` directories under `projects/{project_id}/`.
2. **Schema additions**: `Component` table (one row per component file, current-state-only); `Render.bundle_manifest_json` column (records which component versions were used for a render).
3. **Agent payload enrichment**: controller packages all current component files into the agent's inline payload. Agent receives the full project context; no tool surface, no HTTP back-channel.
4. **Agent output contract change**: agent returns a `FileBundle` (a list of `{path, content}` pairs) instead of a single `source_code` string. The bundle may include new or updated component files alongside the target scene file.
5. **Controller bundle-writeback**: controller receives the `FileBundle`, writes all files to the ObjectStore atomically (best-effort; see design), updates `Component` rows, then renders the target scene.
6. **Watcher rebirth**: project-aware watcher that materializes the project locally, watches for file-system changes, syncs edits back to the ObjectStore, and triggers re-renders of affected scenes.
7. **Manim CLI workdir**: worker materializes the full project package (all component files + target scene) into a temp directory before invoking Manim, so `from components.x import y` resolves correctly.
8. **Frontend Components tab**: read-only file tree on the project detail page showing component files. No in-browser editing.
9. **Backwards compatibility**: existing single-file scenes from Steps 3–6 continue to work as-is. New projects use the package shape. Migration is opt-in.

### Out of scope (deferred)

- **Asset uploads** (images, fonts, custom SVGs). Manim stdlib assets are sufficient for now. Deferred to a Step 7.5 follow-up.
- **In-browser component editing**. The UI shows a read-only file tree. Editing happens via agent prompts or an external IDE.
- **Drag-to-reorder components** or any component-management UI beyond the read-only tree.
- **Per-component render targets**. Components are not independently renderable; they are imported by scenes.
- **Multi-scene batch rendering** ("render all scenes that import this component"). Triggering re-renders of affected scenes is the watcher's job; the UI does not expose a "render all" button.
- **Component versioning history in the UI**. Components are current-state-only in the DB. Historical content is recoverable via `Render.bundle_manifest_json` if needed.
- **Two-way sync for external edits via ObjectStore events**. The watcher uses a local materialization + filesystem events (watchdog). ObjectStore-native event subscriptions are deferred to Step 8 (S3 backend).
- **`S3ObjectStore` backend**. Step 8.
- **OpenCode integration**. Step 9.
- **Auth, multi-user, RBAC**. Single-user assumption holds.

---

## Design

### 1. Project-as-package ObjectStore layout

After this step, a project's files live under a stable prefix in the ObjectStore:

```
projects/{project_id}/
  components/
    spring.py                          # a component file
    text_utils.py                      # another component file
  assets/                              # reserved; empty until Step 7.5
  scenes/
    {scene_id}.py                      # the generated scene file (current version)
```

**Key conventions:**

- **`scenes/{scene_id}.py`** is the canonical current source for a scene. It is the file the agent is asked to generate or update. It is distinct from `renders/{content_hash}/source.py` (the immutable render-time snapshot). The scene file is mutable; the render snapshot is immutable.
- **`components/*.py`** are shared Python modules. The agent can create new ones or update existing ones. The controller writes them back after each agent call.
- **`__init__.py` files** are materialization-only (written to `/tmp` workdir for Manim execution). They are NOT stored in ObjectStore canonical key layout.
- **`assets/`** is reserved. No files are written here in Step 7.
- **Component file paths are relative to the project root.** The agent emits paths like `components/spring.py`, not absolute paths. The controller prepends `projects/{project_id}/` when writing to the ObjectStore.

**Key naming:**

```python
# layersense_storage/src/layersense_storage/keys.py additions
def project_component_key(project_id: str, relative_path: str) -> str:
    # relative_path: "components/spring.py"
    return f"projects/{project_id}/{relative_path}"

def project_scene_key(project_id: str, scene_id: str) -> str:
    return f"projects/{project_id}/scenes/{scene_id}.py"
```

**Project initialization** (on `POST /api/v1/projects`): the controller does not write package `__init__.py` files to ObjectStore. The render materializer creates empty `__init__.py` files in the `/tmp` workdir each time Manim runs.

**Backwards compatibility:** existing projects (created before Step 7) have no `projects/{project_id}/` prefix in the ObjectStore. Their renders still work via `renders/{content_hash}/source.py`. The new package layout is only used for projects that have at least one component, a project-scoped scene at `projects/{project_id}/scenes/{scene_id}.py`, or that were created after Step 7.

---

### 2. Schema additions

#### 2a. `Component` table

One row per component file, current-state-only. No history; the agent prompt is the history.

```sql
-- Migration: 0006_add_component_and_bundle_manifest.py

CREATE TABLE component (
    id              TEXT PRIMARY KEY,           -- uuid4
    project_id      TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    relative_path   TEXT NOT NULL,              -- e.g. "components/spring.py"
    content_hash    TEXT NOT NULL,              -- sha256 of current content
    artifact_key    TEXT NOT NULL,              -- ObjectStore key for current content
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (project_id, relative_path)
);

CREATE INDEX ix_component_project_id ON component(project_id);
```

**Rationale:**

- `UNIQUE(project_id, relative_path)` enforces one row per file. Upsert on write.
- `content_hash` enables cheap "did this component change?" checks without reading the blob.
- `artifact_key` is the ObjectStore key for the current content. Stable; the key is `projects/{project_id}/{relative_path}`.
- No `scene_id` FK. Components are project-scoped, not scene-scoped.

#### 2b. `Render.bundle_manifest_json` column

```sql
-- Same migration 0006
ALTER TABLE render ADD COLUMN bundle_manifest_json TEXT NOT NULL DEFAULT '{}';
```

Shape of the JSON:

```json
{
  "scene_key": "projects/{project_id}/scenes/{scene_id}.py",
  "components": [
    { "relative_path": "components/spring.py", "content_hash": "abc123..." },
    { "relative_path": "components/text_utils.py", "content_hash": "def456..." }
  ]
}
```

This records exactly which component versions were used for a render. Allows reproducing old renders by checking out the component content at those hashes (via `renders/{content_hash}/source.py` for the scene, and by looking up the component content hash in the ObjectStore at the time of the render — or by storing component snapshots under `renders/{render_id}/components/` if strict reproducibility is needed; see Design Question #5).

#### 2c. `Project.python_package_name` field

```sql
-- Same migration 0006
ALTER TABLE project ADD COLUMN python_package_name TEXT;
```

Nullable. Set on project creation to a sanitized, Python-identifier-safe version of the project slug (e.g., `my_project`). Used as the top-level package name if the project is ever exported as a standalone Python package (Step 6 follow-up). Not used by the Manim workdir in Step 7 (the workdir uses the project root directly, not a named package).

---

### 3. Agent payload changes

#### 3a. The core tension: tool surface vs. richer inline payload

The overview's Step 7 outline says: *"Agent gains a constrained tool surface (`read_file`, `write_file`, `list_dir`, `run_render`) scoped to the project."*

**This plan recommends NOT implementing a tool surface.** Instead, the controller packages the project's relevant files into the agent's inline payload, and the agent returns a `FileBundle` of writes. The controller commits the bundle.

**Rationale (per Key Design Decision #6 — agent is a pure function):**

A tool surface would require the agent to make HTTP calls back to the controller (or to a sidecar) during generation. This violates the pure-function principle: the agent would have side effects, would need a `controller_base_url` setting, and would be harder to test, replace, or reason about. The overview's wording ("agent gains a constrained tool surface") was written before Option C was settled; it describes the *capability* (the agent can read and write project files) but not the *mechanism*. The mechanism that preserves the pure-function invariant is: the controller sends the files inline, the agent returns writes inline.

**This is a design question for user confirmation.** See Design Questions section.

#### 3b. What files are sent inline ("relevant project files")

**Recommendation: naive — send all component files.**

For Step 7, the controller sends the entire `components/` directory to the agent as part of the payload. This is:

- Simple to implement (no import parsing, no dependency graph).
- Correct by construction (the agent always has full context).
- Acceptable in practice: component files are small Python modules, typically 1–20 KB each. A project with 20 components is ~200 KB of context — well within LLM context window limits.

Smart import parsing (send only files imported by the target scene) is a premature optimization. Revisit only if payload size becomes a measured problem (e.g., a project with 100+ components).

#### 3c. New agent request shape

```http
POST http://agent:8000/api/v1/animation
{
  "prompt": "add a bouncing spring to the intro scene",
  "excalidraw_scene_json": { ... },
  "frames": [ ... ],
  "project_context": {
    "python_package_name": "my_project",
    "existing_scene_source": "<current scene .py content, or null if new>",
    "components": [
      {
        "relative_path": "components/spring.py",
        "content": "<full file content>"
      },
      {
        "relative_path": "components/text_utils.py",
        "content": "<full file content>"
      }
    ]
  }
}
```

**Notes:**

- `project_context` is **optional**. If absent (legacy path or project has no components), the agent behaves exactly as in Step 4/5. Backwards compatible.
- `existing_scene_source` is the current content of `projects/{project_id}/scenes/{scene_id}.py` from the ObjectStore, or `null` if this is the first generation for this scene. Allows the agent to refine the scene in place rather than regenerating from scratch.
- `components` is the full list of current component files. The agent may reference them in its output.
- The agent's system prompt is updated to explain the project-package convention: scenes live in `scenes/`, components in `components/`, imports use `from components.x import y`.

---

### 4. Agent output contract: `FileBundle`

Today the agent returns:

```json
{ "source_code": "<python>", "content_hash": "<sha256>" }
```

After this step, the agent returns a `FileBundle`:

```json
{
  "files": [
    {
      "relative_path": "scenes/{scene_id}.py",
      "content": "<python source for the scene>"
    },
    {
      "relative_path": "components/spring.py",
      "content": "<python source for the new/updated component>"
    }
  ]
}
```

**Contract rules:**

- The bundle **must** contain exactly one file with `relative_path` matching `scenes/{scene_id}.py`. This is the primary scene file. The controller uses it to compute `content_hash` and trigger the render.
- The bundle **may** contain zero or more component files (`components/*.py`). These are written to the ObjectStore and the `Component` table before the render starts.
- The bundle **must not** contain files outside `scenes/` and `components/`. The controller validates this and rejects bundles with unexpected paths (security: prevents path traversal).
- The bundle **must not** contain `__init__.py` files. Those are managed by the controller.
- `content_hash` is no longer returned by the agent. The controller computes it after receiving the bundle.

**Canonical render hash definition:** `content_hash` is the controller-computed SHA-256 over the canonical render input (scene content plus normalized CLI flags JSON). It is the render cache key used under `renders/{content_hash}/...`. Component `content_hash` fields remain SHA-256 hashes of each component file's current content.

**Backwards compatibility:** the agent's response schema gains a `files` field. If the agent returns the old `{ source_code, content_hash }` shape (legacy agent or Step 4/5 agent), the controller wraps it into a single-file bundle automatically. This allows a gradual rollout.

---

### 5. Controller orchestration: bundle-writeback + render

The `generate_and_render` Taskiq task (from Step 4) is extended:

```
[Extended generate_and_render task body]

1. Load Render + Scene + Frames + Project in one read transaction.
2. Load all Component rows for the project → fetch their content from ObjectStore.
3. Load existing scene source from ObjectStore (projects/{project_id}/scenes/{scene_id}.py), if present.
4. Build agent payload: { prompt, excalidraw_scene_json, frames, project_context: { ... } }
5. POST {agent_base_url}/api/v1/animation → FileBundle
   - on agent error: Render.status="failed", publish event, return
6. Validate bundle:
   - Exactly one scene file at scenes/{scene_id}.py
   - All paths under scenes/ or components/
   - No path traversal (no "..", no absolute paths)
   - on validation failure: Render.status="failed", error_message="invalid bundle", return
7. Write component files to ObjectStore (best-effort atomic):
   For each component file in bundle:
     a. ObjectStore.put(project_component_key(project_id, relative_path), content.encode())
     b. Upsert Component row: (project_id, relative_path, content_hash, artifact_key, updated_at)
   → Component writes are committed here, before the render. They are NOT rolled back on render failure.
     (See Design Question #3 for rationale.)
8. Write scene file to ObjectStore:
   ObjectStore.put(project_scene_key(project_id, scene_id), scene_content.encode())
9. Compute content_hash = sha256(scene_content + canonical_cli_flags_json)
10. Build bundle_manifest_json from current component content_hashes.
11. RendersRepository.find_by_content_hash(content_hash):
    - hit + blobs exist → reuse (same as Step 4 cache-hit path)
    - miss or drift → continue
12. ObjectStore.put(render_source_key(content_hash), scene_content.encode())
    Render.scene_py_artifact_key=..., Render.bundle_manifest_json=..., status="queued"
13. Materialize full project to /tmp/layersense-renders/{render_id}/project/:
    - Write __init__.py, components/__init__.py
    - Write all component files (from ObjectStore or from bundle)
    - Write scene file as scene.py at the project root (or in scenes/ — see Manim workdir design)
14. Run Manim preview → ObjectStore.put_stream(render_preview_key)
    Render.preview_artifact_key=..., status="preview_ready", publish event
15. Run Manim final → ObjectStore.put_stream(render_final_key)
    Render.final_artifact_key=..., status="final_ready", publish event
16. Capture thumbnail → Scene.thumbnail_artifact_key=...
17. Scene.current_render_id=render_id
18. Release lock, clean up /tmp workdir
```

**Step 7 vs. step 13 detail (Manim workdir):** see section 6 below.

---

### 6. Manim CLI workdir: materializing the project package

Manim must be invoked from a directory where `from components.spring import ...` resolves. This requires the project to be materialized as a real Python package on disk before `manim` is called.

**Workdir layout:**

```
/tmp/layersense-renders/{render_id}/
  project/                          ← Python package root; Manim is invoked from here
    __init__.py
    components/
      __init__.py
      spring.py
      text_utils.py
    scene.py                        ← the target scene file, copied here from the bundle
```

**Manim invocation:**

```bash
cd /tmp/layersense-renders/{render_id}/project/
manim scene.py {SceneClassName} --config_file ... --media_dir ... --output_file ...
```

The scene file is placed at the project root (not in `scenes/`) for the Manim invocation. This is because Manim's `--output_file` and media layout work most predictably when the scene file is at the working directory root. The `from components.x import y` imports resolve because `components/` is a sibling of `scene.py` and the CWD is the package root.

**Workdir lifecycle:**

- Created by `materialize_project_for_render(render_id, project_id, scene_content, components)` context manager.
- Cleaned up in `finally` block regardless of render outcome.
- The context manager is responsible for writing all files atomically (write to temp, rename).
- If materialization fails (e.g., ObjectStore read error), the render fails with `status="failed"` and the workdir is cleaned up.

**`materialize_project_for_render` signature:**

```python
@contextmanager
def materialize_project_for_render(
    render_id: str,
    scene_content: str,
    components: list[ComponentFile],  # {relative_path, content}
    workdir_root: Path,
) -> Iterator[Path]:
    """Yields the project root path. Cleans up on exit."""
    ...
```

---

### 7. Watcher: project-aware rebirth

The watcher was disabled in Step 3 with a `NotImplementedError` and a pointer to Step 7. This step brings it back.

**Design: local materialization + filesystem events (watchdog)**

The watcher maintains a local materialization of each active project under `LAYERSENSE_PROJECT_WORKDIR/{project_id}/`. When the user edits a component file in VS Code (or any external editor), the watcher detects the change, syncs the file to the ObjectStore, updates the `Component` row, and triggers a re-render of affected scenes.

**Watcher flow:**

```
1. On startup: for each project with at least one Component row,
   materialize the project to LAYERSENSE_PROJECT_WORKDIR/{project_id}/.
2. watchdog FileSystemEventHandler watches LAYERSENSE_PROJECT_WORKDIR/ recursively.
3. On file change event for {project_id}/components/{filename}.py:
   a. Read the new content from disk.
   b. Compute content_hash.
   c. If content_hash == Component.content_hash for this file: skip (no-op, e.g. IDE touch).
   d. ObjectStore.put(project_component_key(project_id, relative_path), content)
   e. Upsert Component row.
   f. Find all Scene rows for this project.
   g. For each scene: POST /api/v1/scenes/{scene_id}/generate (or dispatch Taskiq task directly).
      → This triggers a full generate+render cycle for each affected scene.
      → The agent receives the updated component in its payload.
4. On file change event for {project_id}/scenes/{scene_id}.py:
   a. Read the new content.
   b. ObjectStore.put(project_scene_key(project_id, scene_id), content)
   c. Dispatch render-only task (POST /render with the new source, no agent call).
      → This is the "render-on-save" loop for direct scene edits.
```

**Design question: does the watcher trigger a full generate+render (agent call) or render-only?**

- For **component changes**: full generate+render is recommended. The agent needs to see the updated component to potentially update the scene's imports or usage. A render-only path would render stale scene code against the new component, which may or may not work.
- For **scene file changes**: render-only. The user edited the scene directly; no agent call needed.

**`LAYERSENSE_PROJECT_WORKDIR`**: new env var, default `/tmp/layersense-projects`. The watcher materializes projects here. This is ephemeral; on restart, the watcher re-materializes from the ObjectStore.

**Two-way sync:** the watcher is the canonical path for external edits flowing back to the ObjectStore. The ObjectStore is the source of truth; the local materialization is a cache. The watcher writes local changes to the ObjectStore; the controller writes ObjectStore changes to the local materialization (on every bundle-writeback). This is one-way sync in each direction, not a general two-way sync. Conflicts are resolved by last-write-wins (single user, single machine).

**Watcher startup guard:** the watcher only activates if `LAYERSENSE_ENABLE_WATCHER=true` (default `false`). This prevents it from running in the default Docker stack where the project workdir is not mounted. The user opts in by setting the env var and mounting `LAYERSENSE_PROJECT_WORKDIR` as a host volume.

---

### 8. Frontend: Components tab

Minimal. The project detail page gains a "Components" tab alongside the existing scene list.

**Components tab:**

- Lists all `Component` rows for the project, grouped by directory (currently just `components/`).
- Each row shows: filename, `updated_at`, `content_hash` (truncated to 8 chars).
- Clicking a component opens a read-only code viewer (syntax-highlighted, no editing).
- No "delete component" button in Step 7. Deletion happens via agent prompt ("remove the spring component") or by deleting the file externally.
- "Components" tab is hidden if the project has zero components.

**No new frontend dependencies.** The code viewer uses a `<pre>` with a CSS class; syntax highlighting via a lightweight library (e.g., `highlight.js` or `prism.js`) is optional and deferred.

---

### 9. Component versioning

**Recommendation: current-state-only.**

The `Component` table has one row per `(project_id, relative_path)`. Each agent call that modifies a component overwrites the row in place (`updated_at` advances, `content_hash` changes). There is no history table.

**Rationale:**

- The agent prompt is the history. "The spring component I made last time" is recovered by looking at the last render's `bundle_manifest_json`, which records the component's `content_hash` at render time. If the user needs to recover an old version, they can look at the render's manifest and find the content hash — but recovering the actual bytes requires either storing component snapshots or re-generating.
- For Step 7, strict component reproducibility is not a requirement. The user is a single developer who can re-generate if needed.
- A history table adds complexity (migration, repository methods, UI) for a benefit that is speculative at this stage.

**If strict reproducibility is needed later:** add a `component_snapshot` table keyed by `(project_id, relative_path, content_hash)` that stores the blob key. The `bundle_manifest_json` already records the content hashes; the snapshots would make them recoverable without re-generation. This is a clean follow-up.

---

## File-level changes

### New files

**`layersense_persistence/`**

- `src/layersense_persistence/models.py` — add `Component` ORM model.
- `src/layersense_persistence/repositories/components.py` — `ComponentsRepository` with `upsert`, `get`, `list_by_project`, `delete`.
- `src/layersense_persistence/schemas.py` — add `ComponentRead`, `ComponentCreate`, `ComponentUpdate` DTOs.
- `migrations/versions/0006_add_component_and_bundle_manifest.py` — adds `component` table, `render.bundle_manifest_json`, `project.python_package_name`.
- `tests/unit/test_repositories_components.py`

**`layersense_storage/`**

- `src/layersense_storage/keys.py` — add `project_component_key`, `project_scene_key` helpers.
- `tests/unit/test_keys.py` — extend with new key helpers.

**`layersense_controller/`**

- `src/layersense_controller/services/project_packager.py` — assembles the `project_context` payload for the agent: loads component rows, fetches content from ObjectStore, builds `ProjectContext` Pydantic model.
- `src/layersense_controller/services/bundle_writer.py` — validates and writes a `FileBundle` to the ObjectStore; upserts `Component` rows; returns the scene content and bundle manifest.
- `src/layersense_controller/services/project_materializer.py` — `materialize_project_for_render` context manager; writes the project package to a temp workdir for Manim.
- `src/layersense_controller/watcher.py` — rewritten (was disabled since Step 3); project-aware watchdog-based watcher.
- `src/layersense_controller/api/components.py` — `GET /api/v1/projects/{project_id}/components` and `GET /api/v1/components/{component_id}` endpoints.
- `tests/unit/test_project_packager.py`
- `tests/unit/test_bundle_writer.py`
- `tests/unit/test_project_materializer.py`
- `tests/integration/test_components_api.py`
- `tests/integration/test_generate_with_components.py` — extends the Step 4 generate integration tests with component bundle scenarios.
- `tests/integration/test_watcher.py`

**`layersense_agent/`**

- `src/layersense_agent/api/v1/schemas/animation.py` (or equivalent) — add `ProjectContext`, `ComponentFile`, `FileBundle`, `FileBundleItem` Pydantic models.
- `tests/integration/test_animation_api_with_components.py` — VCR-backed tests for the new payload shape.

**`layersense_frontend/`**

- `src/components/ComponentsTab.tsx`
- `src/components/ComponentFileViewer.tsx`
- `src/hooks/useProjectComponents.ts`
- `src/components/ComponentsTab.test.tsx`

### Modified files

**`layersense_persistence/`**

- `src/layersense_persistence/__init__.py` — export `ComponentsRepository`, `ComponentRead`, etc.
- `src/layersense_persistence/models.py` — add `Component` model; add `bundle_manifest_json` to `Render`; add `python_package_name` to `Project`.

**`layersense_storage/`**

- `src/layersense_storage/keys.py` — add project-scoped key helpers.

**`layersense_controller/`**

- `src/layersense_controller/render_tasks.py` (or `render_tasks_generate.py`) — extend `generate_and_render` task with steps 1–18 from the orchestration design above.
- `src/layersense_controller/services/agent_client.py` — update `generate_animation` to accept `project_context: ProjectContext | None` and return `FileBundle` (with backwards-compat shim for old `{ source_code, content_hash }` response shape).
- `src/layersense_controller/api/projects.py` — `POST /api/v1/projects` initializes project metadata without writing package `__init__.py` files to ObjectStore.
- `src/layersense_controller/main.py` — register `components` router; conditionally start watcher if `LAYERSENSE_ENABLE_WATCHER=true`.
- `src/layersense_controller/config.py` — add `project_workdir: Path`, `enable_watcher: bool`.
- `docker-compose.yml` — add `LAYERSENSE_ENABLE_WATCHER` env var (default `false`); document how to opt in.

**`layersense_agent/`**

- `src/layersense_agent/api/v1/endpoints/animate_scene.py` — accept `project_context` in request; return `FileBundle` in response; update prompt-construction logic to include component context.
- `src/layersense_agent/api/v1/schemas/` — add new schema models.

**`layersense_frontend/`**

- `src/routes/ProjectDetailRoute.tsx` — add Components tab.
- `src/api.ts` — add `getProjectComponents`, `getComponentById` API helpers.
- `src/types.ts` — add `Component` type.

**Docs**

- `README.md` — update "Current Architecture" to describe multi-file project shape; add "Components" section.
- `docs/ROADMAP.md` — update near-term focus.
- `docs/plans/2026-05-21-architecture-expansion-overview.md` — add a dated entry in the Provenance section noting Step 7 decisions.

---

## Test plan

### Unit tests

**`layersense_persistence` — `test_repositories_components.py`:**

- `upsert` creates a new row when `(project_id, relative_path)` is absent.
- `upsert` updates `content_hash`, `artifact_key`, `updated_at` when the row exists.
- `list_by_project` returns all components for a project, ordered by `relative_path`.
- `delete` removes the row; subsequent `get` returns `None`.
- Cascade: deleting a project deletes all its components.

**`layersense_storage` — `test_keys.py` additions:**

- `project_component_key` produces stable, escape-safe paths.
- `project_component_key` rejects paths with `..` or absolute components.
- `project_scene_key` produces stable paths.

**`layersense_controller` — `test_project_packager.py`:**

- Builds correct `ProjectContext` from a project with zero components (empty list).
- Builds correct `ProjectContext` from a project with N components; content fetched from a mock ObjectStore.
- Handles ObjectStore read failure gracefully (raises, does not silently omit a component).

**`layersense_controller` — `test_bundle_writer.py`:**

- Accepts a valid bundle with one scene file and zero component files.
- Accepts a valid bundle with one scene file and two component files; writes all to ObjectStore; upserts Component rows.
- Rejects a bundle with no scene file.
- Rejects a bundle with two scene files.
- Rejects a bundle with a file outside `scenes/` or `components/` (e.g., `../../etc/passwd`).
- Rejects a bundle with an `__init__.py` file.
- Returns correct `bundle_manifest_json` reflecting current component content hashes.

**`layersense_controller` — `test_project_materializer.py`:**

- Materializes a project with zero components: workdir contains `__init__.py`, `components/__init__.py`, `scene.py`.
- Materializes a project with two components: workdir contains all expected files with correct content.
- Cleans up workdir on normal exit.
- Cleans up workdir on exception (verify `finally` path).
- Raises on ObjectStore read failure; workdir is cleaned up.

**`layersense_controller` — `test_agent_client.py` additions:**

- Sends `project_context` in request body when provided.
- Parses `FileBundle` response correctly.
- Falls back to wrapping `{ source_code, content_hash }` response into a single-file bundle (backwards compat).

### Integration tests

**`layersense_controller` — `test_components_api.py`:**

- `GET /api/v1/projects/{project_id}/components` returns empty list for a new project.
- After a generate that produces a component, the endpoint returns the component.
- `GET /api/v1/components/{component_id}` returns the component with content.
- 404 on unknown component ID.

**`layersense_controller` — `test_generate_with_components.py`:**

- Happy path: agent returns a bundle with one scene file and one new component file. Controller writes both to ObjectStore, upserts Component row, renders the scene. `bundle_manifest_json` on the Render row reflects the component.
- Second generate on the same scene: agent returns an updated component. Controller overwrites the component in ObjectStore, updates Component row, re-renders. Old Render row's `bundle_manifest_json` still reflects the old component hash.
- Agent returns a bundle with only the scene file (no components): controller renders normally; no Component rows are created or modified.
- Agent returns an invalid bundle (path traversal): controller sets `Render.status="failed"` with a descriptive error; no files are written to ObjectStore.
- Cache-hit path with components: `/generate` always calls the agent first to obtain the current `FileBundle`; after the controller computes `content_hash`, a cache hit reuses existing render artifacts and skips Manim rendering. Component writeback still follows the bundle-writeback rules before the post-agent cache check.

**`layersense_controller` — `test_watcher.py`:**

- Watcher detects a component file change in the materialized project directory.
- Watcher syncs the changed file to the ObjectStore (verified via mock ObjectStore).
- Watcher upserts the Component row.
- Watcher dispatches a generate task for each scene in the project (verified via mock Taskiq broker).
- Watcher ignores changes to `__init__.py` files.
- Watcher ignores changes to non-Python files.
- Watcher detects a scene file change and dispatches a render-only task (no agent call).
- Watcher does not activate when `LAYERSENSE_ENABLE_WATCHER=false`.

**`layersense_agent` — `test_animation_api_with_components.py`:**

- `POST /api/v1/animation` with `project_context` containing two components: response is a `FileBundle` with at least one scene file.
- `POST /api/v1/animation` without `project_context`: response is a `FileBundle` with one scene file (backwards compat).
- VCR cassette covers the new payload shape.

### e2e tests

**`tests/e2e/test_dev_stack_e2e.py` additions:**

- Create a project. Generate a scene with a prompt that asks for a reusable component. Assert that `GET /api/v1/projects/{project_id}/components` returns at least one component after the generate completes.
- Generate a second scene in the same project with a prompt that references the component from the first scene. Assert that the second scene's render succeeds and that `bundle_manifest_json` on the Render row references the component.
- (Optional, requires watcher enabled) Edit a component file in the materialized project directory. Assert that a new render is triggered for the affected scene within N seconds.

---

## Acceptance criteria

All grep-verifiable:

1. `grep -rn "project_context" layersense_agent/src/` returns at least one match (agent accepts the new field).
2. `grep -rn "FileBundle\|file_bundle" layersense_controller/src/` returns matches in `bundle_writer.py` and `agent_client.py`.
3. `grep -rn "path_traversal\|relative_path.*\.\." layersense_controller/src/` returns a match in `bundle_writer.py` (path validation is present).
4. `grep -rn "materialize_project_for_render" layersense_controller/src/` returns matches in `project_materializer.py` and the render task.
5. `grep -rn "bundle_manifest_json" layersense_persistence/src/` returns a match in `models.py`.
6. `grep -rn "LAYERSENSE_ENABLE_WATCHER" layersense_controller/src/` returns a match in `config.py`.
7. `grep -rn "NotImplementedError" layersense_controller/src/layersense_controller/watcher.py` returns no matches (watcher is no longer a stub).
8. `uv run --all-packages pytest -m unit` passes.
9. `uv run --all-packages pytest -m integration` passes.
10. `just lint` passes.
11. `just e2e` passes against the local Docker stack.
12. After `just docker` from a clean state: creating a project, generating a scene with a component-creating prompt, and then generating a second scene that imports the component — both renders succeed and the Components tab shows the component.
13. `grep -rn "from components\." layersense_controller/src/` returns no matches (the controller does not import from the user's project components — it only manages them as blobs).
14. Coverage for `layersense_controller/src/layersense_controller/services/bundle_writer.py` ≥ 95%.
15. Coverage for `layersense_controller/src/layersense_controller/services/project_materializer.py` ≥ 95%.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Agent emits conflicting files (e.g., two entries for the same `relative_path` in the bundle) | `bundle_writer.py` validates the bundle before writing: deduplicate by `relative_path`, last-entry-wins, log a warning. Document this behavior. |
| Component naming collision: agent creates `components/utils.py` which shadows a Python stdlib module | Document the convention: component names should be descriptive and project-specific. The agent's system prompt warns against shadowing stdlib names. No runtime enforcement in Step 7. |
| Manim workdir: `from components.x import y` fails because the workdir layout is wrong | Covered by `test_project_materializer.py` unit tests and the e2e test. The materializer is the single source of truth for workdir layout; any layout bug surfaces immediately in tests. |
| A component change breaks dependent scenes (import error, API change) | This is expected behavior. The user iterates via the agent ("fix the spring component so it works with the intro scene"). The watcher's re-render will surface the error in `Render.status="failed"` with the Manim log. No automatic rollback. |
| Component writes committed before render; a bad agent suggestion leaves components in a broken state | Documented explicitly. Single-user dev workflow: the next prompt fixes it. The `bundle_manifest_json` on the last successful Render records the last known-good component hashes, which can be used to recover. |
| Security: `read_file`/`write_file` tool surface (if implemented) could escape the project sandbox | This plan recommends NOT implementing a tool surface. The agent receives files inline and returns files inline. No HTTP back-channel, no filesystem access from the agent. Path validation in `bundle_writer.py` is the security boundary. |
| Path traversal in bundle: agent emits `relative_path: "../../etc/passwd"` | `bundle_writer.py` validates all paths: must be relative, must not contain `..`, must start with `scenes/` or `components/`. Rejects the bundle and sets `Render.status="failed"`. Covered by unit tests. |
| Watcher triggers a generate loop: generate writes a component, watcher detects the write, triggers another generate | The watcher only watches `LAYERSENSE_PROJECT_WORKDIR`, which is a local materialization. The controller writes to the ObjectStore and then syncs to the local workdir. The watcher must ignore writes that originate from the controller itself (e.g., by comparing content hashes before dispatching). Covered by `test_watcher.py`. |
| Watcher is not enabled by default; users may not discover it | Documented in README. The Components tab in the frontend mentions "edit components in your IDE with the watcher enabled". |
| Large number of components bloats the agent payload | Naive approach sends all components. Revisit if payload exceeds ~500 KB (roughly 50+ large component files). Smart import parsing is the mitigation; deferred. |
| Backwards compatibility: existing single-file scenes break when the controller tries to load `project_context` | `project_context` is optional in the agent request. The controller only sends it if the project has at least one Component row or is in "package mode". Legacy projects are not in package mode. |
| Taskiq task body grows very long (agent call + bundle write + materialization + render) | Single task per C2a (Step 4 decision). If it becomes unwieldy, split into two tasks: `generate_bundle` → `render_bundle`. The Render row's status machine already accommodates intermediate states. Deferred. |

---

## Estimated shape

This is the largest step in the migration.

| Area | LOC delta (src) | LOC delta (tests) |
|---|---|---|
| `layersense_persistence` (Component model + repo + migration) | ~200 | ~200 |
| `layersense_storage` (key helpers) | ~50 | ~50 |
| `layersense_controller` (packager + bundle writer + materializer + watcher + API + task extension) | ~900 | ~1000 |
| `layersense_agent` (new schemas + prompt construction) | ~200 | ~200 |
| `layersense_frontend` (Components tab + viewer + hook) | ~400 | ~200 |
| Docs | ~100 | — |
| **Total** | **~1850** | **~1650** |

**Recommended PR split (3 PRs):**

1. **Schema + storage keys + persistence** (`layersense_persistence` migration, `Component` repo, `layersense_storage` key additions). No behavior change; `just test_python` passes throughout.
2. **Agent contract + controller bundle infrastructure** (new agent schemas, `FileBundle` response, `bundle_writer`, `project_packager`, `project_materializer`, `agent_client` update, task extension, components API). The generate flow works end-to-end with components. `just e2e` passes.
3. **Watcher rebirth + frontend Components tab**. Opt-in via `LAYERSENSE_ENABLE_WATCHER`. Frontend shows the Components tab. `just e2e` passes.

---

## Design questions (surface for user confirmation before implementation)

### DQ1: Tool surface vs. richer inline payload (CRITICAL — resolve before PR 2)

The overview's Step 7 outline says the agent "gains a constrained tool surface (`read_file`, `write_file`, `list_dir`, `run_render`)". This plan recommends **not** implementing a tool surface. Instead, the controller sends project files inline and the agent returns a `FileBundle`.

**The tension:** a tool surface would allow the agent to be more selective (read only the files it needs, write only the files it changes). The inline approach sends everything and receives everything, which is simpler but less flexible.

**Recommendation:** inline payload + `FileBundle`. Preserves the pure-function invariant (Key Design Decision #6). The tool surface described in the overview is the *capability*, not the *mechanism*. Revisit in Step 9 if the inline approach hits real limits.

**Question for Mathias:** confirm that the inline approach is preferred over a tool surface. If you want a tool surface, the agent would need an HTTP back-channel to the controller (or a sidecar), which violates the pure-function principle and requires revisiting Decision #6.

---

### DQ2: Atomic component writes — rollback on render failure? (resolve before PR 2)

This plan recommends: component writes are committed at agent-return time, before the render. If the render fails, the components are NOT rolled back.

**Trade-off:** a bad agent suggestion can leave components in a broken state until the next prompt fixes them. For single-user dev, this is acceptable — the user iterates.

**Alternative:** write components to a staging area, promote to canonical only on render success. More complex; adds a two-phase write pattern.

**Question for Mathias:** confirm that no-rollback is acceptable. If you want rollback, the staging area approach is the mitigation.

---

### DQ3: Component versioning — current-state-only vs. history table (resolve before PR 1)

This plan recommends: one `Component` row per `(project_id, relative_path)`, updated in place. No history.

**Trade-off:** you cannot recover an old component version from the DB alone. You can recover it from `Render.bundle_manifest_json` (which records the content hash) if you also store component snapshots under a content-addressed key. This plan does NOT store component snapshots; it only stores the current version.

**Question for Mathias:** is current-state-only acceptable? If you want strict reproducibility (recover any component at any point in time), the mitigation is to add a `component_snapshot` table keyed by `(project_id, relative_path, content_hash)` that stores the blob key. This is a clean follow-up and does not need to block Step 7.

---

### DQ4: Watcher trigger for component changes — full generate+render vs. render-only (resolve before PR 3)

When the watcher detects a component file change, this plan recommends triggering a **full generate+render** (agent call + render) for each affected scene.

**Trade-off:** a full generate+render is expensive (LLM call per scene). A render-only path is cheaper but may produce incorrect results if the scene's imports or usage of the component need to be updated.

**Alternative:** render-only for component changes. The user manually triggers a generate if the scene needs to be updated.

**Question for Mathias:** which behavior do you want for the watcher? Full generate+render (expensive, always correct) or render-only (cheap, may need manual generate after component API changes)?

---

### DQ5: `bundle_manifest_json` — store component content or just hashes? (resolve before PR 2)

This plan stores only content hashes in `bundle_manifest_json`. To recover the actual component content at a past render, you would need to find the ObjectStore key for that hash — which is `projects/{project_id}/{relative_path}` (the current version, which may have changed).

**If strict reproducibility is needed:** store component snapshots under `renders/{render_id}/components/{relative_path}` at render time. This doubles the storage for components but makes every render fully reproducible.

**Question for Mathias:** is hash-only sufficient, or do you want component snapshots stored per render? For a single-user dev workflow, hash-only is likely sufficient. Snapshots are a clean follow-up.

---

## Assumptions

1. The agent's LLM context window is large enough to hold all component files inline. For a project with 20 components averaging 5 KB each, that is 100 KB of context — well within GPT-4o's 128K token window. Revisit if projects grow beyond ~50 components.
2. Manim can be invoked from a temp directory that is not the repo root. The `--config_file` flag points at the packaged config resource; the `--media_dir` flag points at the ObjectStore's storage root. No Manim config assumes a specific working directory.
3. `watchdog` is an acceptable dependency for the watcher. It is a well-maintained Python library for filesystem events. Add to `layersense_controller/pyproject.toml` as an optional dep (`[project.optional-dependencies] watcher = ["watchdog>=4.0"]`).
4. The agent's system prompt can be updated to explain the project-package convention without breaking existing behavior. The prompt update is additive.
5. `python_package_name` on `Project` is nullable and not used by the Manim workdir in Step 7. It is reserved for Step 6 follow-up (project export as a standalone Python package).
6. The `FileBundle` response shape is backwards-compatible: if the agent returns the old `{ source_code, content_hash }` shape, the controller wraps it into a single-file bundle. This allows a gradual rollout without requiring the agent to be updated atomically with the controller.
7. Component files are always valid Python. The controller does not validate Python syntax before writing to the ObjectStore. Syntax errors surface as Manim render failures with a descriptive log.
8. The watcher is opt-in (`LAYERSENSE_ENABLE_WATCHER=false` by default). The default Docker stack does not mount `LAYERSENSE_PROJECT_WORKDIR` as a host volume. Users who want the watcher must opt in explicitly.
9. Existing projects (created before Step 7) are not automatically migrated to package mode. They continue to work as single-file scenes. The "convert to multi-file" migration is a future follow-up.
10. The Components tab in the frontend is read-only. In-browser editing is explicitly out of scope for Step 7.
11. Asset uploads (images, fonts) are deferred to Step 7.5. Manim stdlib assets are sufficient for the initial component library use case.
12. The `bundle_manifest_json` column is added to `Render` in migration `0006`. If migration `0006` has not yet been finalized, fold all Step 7 schema changes into that single migration.
13. `just lint` and `just test` are the verification gates before claiming any PR in this step is done.

→ Confirm DQ2–DQ5 before implementation begins. DQ1 is resolved by design decision #16: the agent stays a pure function with inline `FileBundle` response.
