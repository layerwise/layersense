# Frontend Revamp + Project/Scene CRUD + Controller Orchestration — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md` (overview is canonical for schema, key layout, and Option C boundaries). Amended 2026-05-21 to: (a) make `_default` shim wipe an explicit first-commit migration; (b) declare a hard-cutover schema break for `RenderJobSnapshot` (no back-compat); (c) specify the frame-diff algorithm as hard-delete-on-disappear with explicit collision rule; (d) reconcile real frontend prop shapes (`Canvas` gains an `onChange` callback; `VideoPlayer` keeps URL-shaped props; status vocabulary unifies to the backend `Render.status` enum across the wire); (e) clarify that `isSaving`-gated Generate eliminates the autosave race by construction, not by snapshotting. **Prerequisite note (2026-05-23):** before executing the frontend revamp slices in this plan, complete `docs/plans/2026-05-23-frontend-bun-tailwind-migration-plan.md` so the revamp lands on the Bun/Tailwind baseline instead of extending the Bun + app-CSS stack.
**Step in build order:** 4 of 9
**Depends on:** Step 2 (`layersense_persistence`) merged, Step 3 (`ObjectStore` + `cache.py` deletion + `_default` shim) merged, `docs/plans/2026-05-23-frontend-bun-tailwind-migration-plan.md` executed first for frontend tooling/styling baseline
**Unblocks:** Step 5 (agent refinement), Step 6 (project export)

---

## Why this step

This is the first user-visible payoff and the architectural keystone. After this step:

- The frontend has three navigable views: project list → scene list (storyboard) → scene editor (Excalidraw + prompt + video).
- Projects and scenes are persistent. Closing the browser tab no longer loses work.
- **The Controller is the orchestrator.** It is the only service the browser talks to. It owns the database, the object store, and the agent dispatch.
- **The Agent is a stateless pure function.** It accepts an inline payload (Excalidraw JSON + prompt + frames), returns Manim source code. Nothing else. It has no awareness of Projects, Scenes, the database, or the object store.
- The `_default` Project shim from Step 3 is **deleted** by a focused first-commit migration `0003_drop_default_project_shim.py` (see `_default shim wipe` below). Real `POST /projects` and `POST /projects/{id}/scenes` endpoints replace it.
- Frames are minimally wired: schema and CRUD exist, the agent receives the structured frame array, the UI displays a frame list with `prompt_augmentation` per frame. Drag-to-reorder UX is deferred.

This step does **not** change the agent's generation logic, the object store, or the rendering engine internals. It introduces project/scene CRUD on the controller, moves the agent call server-side, and rebuilds the frontend on top of the new API.

---

## Architectural anchor: Option C

Decided in the Step 4 design discussion. The dependency graph is strictly one-way:

```
Browser ──► Controller ──► Agent
                ▲              │
                └── source ─────┘
                ▼
          ObjectStore + DB
```

- **Browser** is a thin client. It only talks to the Controller.
- **Controller** is the orchestrator and system of record. It owns DB, ObjectStore, Taskiq queue, and is the only caller of the Agent.
- **Agent** is a pure function `(payload) → (source_code, content_hash)`. No DB, no ObjectStore, no controller awareness.

The browser→agent direct call from Step 3 is **retired** in this step. The browser stops sending requests to `localhost:8000` entirely.

---

## `_default` shim wipe (first commit)

Step 4's first commit is migration `migrations/versions/0003_drop_default_project_shim.py`, landing in `layersense_persistence`:

```python
# layersense_persistence/.../migrations/versions/0003_drop_default_project_shim.py

def upgrade() -> None:
    # 1. Collect render rows under _default for blob cleanup.
    conn = op.get_bind()
    keys_to_delete = conn.execute(text("""
        SELECT r.scene_py_artifact_key, r.preview_artifact_key, r.final_artifact_key, r.log_artifact_key,
               s.thumbnail_artifact_key
        FROM render r
        JOIN scene s ON s.id = r.scene_id
        JOIN project p ON p.id = s.project_id
        WHERE p.slug = '_default'
    """)).all()

    # 2. Delete the project row; ON DELETE CASCADE removes scene, frame, render rows.
    op.execute(text("DELETE FROM project WHERE slug = '_default'"))

    # 3. Blob wipe is performed by a one-shot offline helper invoked by the migration runner
    #    (NOT inside the Alembic migration body itself — migrations stay DB-only).
    #    See `scripts/wipe_default_shim_blobs.py`, invoked by `just db_migrate` after the migration applies.

def downgrade() -> None:
    raise NotImplementedError("_default shim wipe is one-way; restoring requires restoring blobs from backup")
```

**Companion offline script `scripts/wipe_default_shim_blobs.py`:**

- Reads the list of artifact keys captured by the migration into a one-shot temporary table OR via a pre-migration `SELECT` exported to JSON in `layersense_artifacts/.migration_state/0003_default_keys.json`.
- For each key, calls `ObjectStore.delete(key)`. Missing keys are skipped silently (idempotent).
- Logs a one-line summary: `wiped N renders / M blobs from _default shim`.

**Why split the DB delete from the blob delete:** Alembic migrations must be DB-only — running them inside a Docker `entrypoint` flow with object-store side effects is an anti-pattern (the migration cannot be replayed safely on a different storage root, e.g., when someone resets storage but not DB). The two-step shape — migration deletes rows; companion script deletes blobs — is recoverable and ordering-safe.

**No data preservation.** The shim only ever held throwaway content from the Step 3 transition window. Anything you care about is re-generated via Step 4's real CRUD-driven flow.

**Anti-resurrection guard:** acceptance criterion 1 below (`grep "_default"` returns zero) plus a SQL assertion in the e2e bootstrap: `SELECT COUNT(*) FROM project WHERE slug='_default'` must return 0 after `just db_reset && just docker`. Any creation path in the controller that would resurrect the shim is removed in the same first commit (the shim's call site from PR 3b is deleted).

---

## Scope

### In scope

1. **Controller HTTP endpoints** for Project, Scene, and Frame CRUD against `layersense_persistence` repositories.
2. **Controller orchestration endpoint**: `POST /api/v1/scenes/{scene_id}/generate` — single entry point that runs the full `(generate-code, render)` lifecycle inside one Taskiq task. Returns a `render_id` immediately; browser long-polls.
3. **Controller → Agent client**: a small `httpx`-based service module that calls the agent's `POST /api/v1/animation`.
4. **Frontend routing** (`react-router-dom`) with three views: `/`, `/projects/:projectId`, `/projects/:projectId/scenes/:sceneId`.
5. **Frontend persistence wiring**: scenes load Excalidraw JSON and prompt from the controller; edits autosave (debounced) via `PATCH /scenes/{id}`. Generate triggers `POST /scenes/{id}/generate`.
6. **Delete the `_default` Project shim** introduced in Step 3.
7. **Frame display**: the scene editor lists Excalidraw frames present in the current scene JSON, in their Excalidraw order, with a `prompt_augmentation` text field per frame. The agent receives this list. UI for *reordering* frames is out of scope.
8. **`scene.thumbnail_artifact_key`**: set by the worker after preview render to a small PNG snapshot. Powers `SceneCard` thumbnails in the project detail view.

### Preserved (per C3a)

- `POST /render` stays as an endpoint for the future watcher flow and tests. It accepts an explicit `source_code` + `content_hash` and skips the agent call. Browser does not use it after this step.

### Out of scope

- Excalidraw frame *reordering UX*. The list reflects Excalidraw's native frame order; no drag-to-reorder yet.
- Multi-scene rendering / "render whole project". One scene at a time.
- Project export / tarballs (Step 6).
- Agent refinement chains via `parent_render_id` (Step 5).
- Component library, asset uploads, multi-file scene projects (Step 7).
- Auth, sharing, user accounts. Single-user assumption holds.
- Optimistic concurrency control on autosave. Last-write-wins is acceptable.

---

## Design

### Controller HTTP surface

All new endpoints under `layersense_controller/src/layersense_controller/api/`, mounted at `/api/v1`. Existing `/render`, `/render-jobs/{id}`, and `/artifacts/...` routes stay where they are — they are render-engine concerns, not CRUD.

```
# Project CRUD
POST   /api/v1/projects                        body: { name }
GET    /api/v1/projects                        → list, ordered by updated_at desc
GET    /api/v1/projects/{project_id}           → project + scene summaries
PATCH  /api/v1/projects/{project_id}           body: { name?, default_render_config? }
DELETE /api/v1/projects/{project_id}

# Scene CRUD
POST   /api/v1/projects/{project_id}/scenes    body: { name, order_index? }
GET    /api/v1/projects/{project_id}/scenes    → list, ordered by order_index asc
GET    /api/v1/scenes/{scene_id}               → scene + frames + current_render summary
PATCH  /api/v1/scenes/{scene_id}               body: { name?, prompt?, excalidraw_scene_json?, order_index? }
DELETE /api/v1/scenes/{scene_id}

# Frame CRUD (internal/test surface; frame existence is normally Excalidraw-driven via PATCH /scenes/{id})
POST   /api/v1/scenes/{scene_id}/frames        body: { excalidraw_frame_id, prompt_augmentation? }
PATCH  /api/v1/frames/{frame_id}               body: { prompt_augmentation? }
DELETE /api/v1/frames/{frame_id}

# Orchestration entry point
POST   /api/v1/scenes/{scene_id}/generate      body: { cli_flags? }
                                                → returns { render_id, scene_id, status: "generating" }
                                                → browser long-polls /render-jobs/{render_id} (existing route)
```

**Notes:**

- **`PATCH /scenes/{id}` is the autosave target.** Partial body; only supplied fields are written.
- **Frames are derived-but-persisted.** When `PATCH /scenes/{id}` updates `excalidraw_scene_json`, the controller runs the frame-diff algorithm specified in `### Frame diff algorithm` below. Frame existence is normally Excalidraw-driven; the explicit Frame CRUD endpoints exist for tests and future tooling, with docstrings flagging them as internal.
- **`POST /scenes/{id}/generate` returns immediately** with a `render_id`. The agent call happens server-side, asynchronously, inside a Taskiq task (per C2a). The browser never holds an open connection waiting for the LLM.
- **`render_id` is the long-poll handle** for the entire `(generate, render)` lifecycle. New states: `generating` (agent call in flight) → `queued` → `preview_ready` → `final_ready` → `failed`.

### `POST /scenes/{scene_id}/generate` lifecycle

```
1. Browser → Controller: POST /api/v1/scenes/{scene_id}/generate { cli_flags? }
2. Controller (sync, in request handler):
     - ScenesRepository.get(scene_id) → 404 if missing
     - Create Render row: status="generating", scene_id=..., cli_flags_json=normalized
     - Dispatch Taskiq task: generate_and_render(render_id)
     - Return { render_id, scene_id, status: "generating" } immediately
3. Browser: GET /render-jobs/{render_id} (long-poll, existing endpoint)
4. Taskiq worker (single task per C2a):
     a. Load Render + Scene + Frames in one read transaction
      b. Build agent payload: { prompt, excalidraw_scene_json, frames: [...] }
      c. POST {agent_base_url}/api/v1/animation → { source_code, content_hash }
         - on agent error: Render.status="failed", Render.error_message=..., publish event, return
      d. Compute canonical content_hash = sha256(source_bytes + canonical(cli_flags_json))
         Single canonical hash: `content_hash = sha256(source_bytes + canonical(cli_flags_json))`.
      e. RendersRepository.find_by_content_hash(content_hash):
           - hit + blobs exist → reuse: copy preview/final/source keys to this Render row,
             status="final_ready", scene.current_render_id=render_id, publish event, return
           - miss or drift → continue
      f. ObjectStore.put(render_source_key(content_hash), source_code.encode())
         Set Render.scene_py_artifact_key=..., status="queued"
      g. Acquire layersense:lock:render:{content_hash} (Step 1's primitive)
     h. Materialize source to /tmp/layersense-renders/{render_id}/scene.py
     i. Run Manim preview → ObjectStore.put_stream(render_preview_key)
        Render.preview_artifact_key=..., status="preview_ready", publish event
     j. Run Manim final → ObjectStore.put_stream(render_final_key)
        Render.final_artifact_key=..., status="final_ready", publish event
     k. Capture first frame as PNG → ObjectStore.put(thumbnail key)
        Scene.thumbnail_artifact_key=...
     l. Scene.current_render_id=render_id
     m. Release lock, clean up /tmp workdir
5. Browser: long-poll resolves with final_ready, fetches /artifacts/by-hash/{content_hash}/final
```

**One Taskiq task does all of (4a–4m).** Per C2a. The state names are *progress markers* on the Render row, not separate tasks.

### Controller → Agent client

`layersense_controller/src/layersense_controller/services/agent_client.py`. Small, sync, `httpx.Client`-based.

```python
class AgentClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None: ...

    def generate_animation(
        self,
        *,
        prompt: str,
        excalidraw_scene_json: dict,
        frames: list[FramePayload],
    ) -> AgentResponse:
        # POST {base_url}/api/v1/animation
        # Returns { source_code, content_hash }
        # Raises AgentCallError on connection failure (after one retry)
        # Raises AgentResponseError on 4xx/5xx (no retry; deterministic failure)
```

**Per C5:**
- `httpx` (sync, since the Taskiq task body is sync — matches Step 3's render task style).
- Settings-driven base URL: `agent_base_url: AnyUrl = AnyUrl("http://agent:8000")` in `RenderControllerSettings`.
- Default 120s timeout (configurable).
- One retry on connection errors only. No retry on 4xx/5xx — deterministic agent failures surface immediately as `Render.status="failed"`.

### Agent ↔ Controller contract

After Step 3 the agent's request shape was loose ("conversation_id-as-anchor"). Step 4 firms it up as a stateless function:

```http
POST http://agent:8000/api/v1/animation
{
  "prompt": "make the circle bounce",
  "excalidraw_scene_json": { "elements": [...], "appState": {...}, "files": {...} },
  "frames": [
    { "excalidraw_frame_id": "fr_001", "order_index": 0, "prompt_augmentation": "..." },
    { "excalidraw_frame_id": "fr_002", "order_index": 1, "prompt_augmentation": "..." }
  ]
}

→ 200 OK
{
  "source_code": "<python source as string>",
  "content_hash": "<sha256 hex of source bytes>"
}
```

**Key changes from Step 3's contract:**

- `conversation_id` is **removed**. The agent doesn't need it; it's a controller-side concept attached to `Render`.
- `excalidraw_scene` → `excalidraw_scene_json`. Naming consistency with the DB column.
- `frames` field is **new**. Ordered, structured. The agent's prompt-construction logic uses it. (Richer prompt-construction *behavior* lands in Step 5; Step 4 may concatenate `frame.prompt_augmentation` strings as a starting heuristic.)

### Frontend architecture

```
layersense_frontend/src/
  App.tsx                       # router shell only
  routes/
    ProjectListRoute.tsx
    ProjectDetailRoute.tsx      # scene list / storyboard view
    SceneEditorRoute.tsx        # the existing 3-pane UI, persistence-backed
  components/
    Canvas.tsx                  # existing imperative forwardRef shape preserved;
                                # gains an optional `onChange(snapshot)` prop wired to
                                # Excalidraw's onChange. SceneEditorRoute uses onChange
                                # (reactive autosave path) and keeps the imperative
                                # getSceneSnapshot() handle for the Generate click.
    VideoPlayer.tsx             # existing URL-shaped props preserved
                                # ({ previewUrl, finalUrl, errorMessage, status }) +
                                # adds `thumbnailUrl`. status type changes from the
                                # UX-shaped enum to the backend RenderJobSnapshot['status'].
    FrameList.tsx               # new; right-rail panel; warns on deletion
    SceneCard.tsx               # new; thumbnail + name in project detail
    ProjectCard.tsx             # new; tile in project list
  hooks/
    useRenderJob.ts             # existing version-based long-poll preserved;
                                # terminal-state check updated to ('final_ready' | 'failed')
    useDebouncedAutosave.ts     # new
    useScene.ts                 # new
    useProjects.ts              # new
    useProject.ts               # new
  api.ts                        # extended with project/scene/frame/generate endpoints
                                # NB: the browser→agent direct call is removed entirely
  types.ts                      # extended with Project, Scene, Frame DTOs;
                                # RenderJobSnapshot rewritten per "Render-job snapshot —
                                # hard schema cutover"; VideoPlayerStatus type DELETED.
```

**Deliberately small dep additions:**

- `react-router-dom` (only new runtime dep).
- No data-fetching library, no state management library, no UI component library.

**Canvas API change (additive, ref-preserving):**

```ts
export type CanvasHandle = {
  getSceneSnapshot: () => ExcalidrawSceneSnapshot
}

export type CanvasProps = {
  initialScene?: ExcalidrawSceneSnapshot           // applied on mount via excalidrawAPI.updateScene
  onChange?: (snapshot: ExcalidrawSceneSnapshot) => void
}

export const Canvas = forwardRef<CanvasHandle, CanvasProps>(...)
```

- `initialScene` lets SceneEditorRoute hydrate the canvas from `GET /scenes/{id}`.
- `onChange` is the autosave entry point; `useDebouncedAutosave` consumes its snapshots.
- The existing imperative `getSceneSnapshot()` handle stays — the Generate button uses it to capture the exact moment-of-click state (belt and braces with `isSaving`-gated Generate).
- Existing Canvas tests are updated to cover both the imperative handle and the new callback.

### Routing

```
/                                              → ProjectListRoute
/projects/:projectId                           → ProjectDetailRoute
/projects/:projectId/scenes/:sceneId           → SceneEditorRoute
```

- Project list: `ProjectCard` tiles + "New Project" button.
- Project detail: `SceneCard` tiles in `order_index` order + "New Scene" button + breadcrumb.
- Scene editor: 3-pane layout, breadcrumb, "Generate" button, render status indicator.
- Empty states are minimal text only.

### Autosave behavior

- 800ms debounce on Excalidraw `onChange` and prompt textarea changes.
- One in-flight `PATCH` per scene; if a new save is queued while one is in flight, queue exactly one (drop intermediate).
- On `PATCH` failure: small "save failed, will retry" indicator; retry once after 2s; on second failure surface a persistent banner.
- **Generate is disabled while `isSaving` is true OR while `lastSavedAt` is older than the most recent local edit.** This eliminates the autosave race **by construction**: the click event for Generate cannot fire while any save is in flight or any unsaved edit exists, so at click time `DB state == client state`. The worker reads scene state at click + ε on the same row; any user edit after Generate click is by definition a new render's input. **No scene-state snapshot fields on `Render` are needed**; the audit's "race" was a misreading of the gating order.
- Last-write-wins. No version field, no `If-Match`.

### Render-job snapshot — hard schema cutover

`RenderJobSnapshot` (the long-poll payload returned by `GET /render-jobs/{render_id}`) changes shape in this step. Hard cutover, no dual-shape support — same rationale as Step 3's `/render` contract break: single-user dev stage, frontend and backend land in the same monorepo PR, e2e covers it.

**Before this step** (today's controller):

```ts
type RenderJobSnapshot = {
  job_id: string                         // synthetic job_id derived from content_hash
  status: 'queued' | 'rendering' | 'succeeded' | 'failed'
  version: number                        // monotonic version for delta long-poll
  preview_url: string | null
  final_url: string | null
  error: string | null
}
```

**After this step:**

```ts
type RenderJobSnapshot = {
  render_id: string                      // canonical Render.id from the DB; supersedes job_id
  scene_id: string                       // for frontend routing / cache invalidation
  content_hash: string                   // for /artifacts/by-hash routing
  status: 'generating' | 'queued' | 'preview_ready' | 'final_ready' | 'failed'
  version: number                        // unchanged contract; monotonic per render_id
  preview_url: string | null             // resolved by controller from preview_artifact_key
  final_url: string | null               // resolved by controller from final_artifact_key
  thumbnail_url: string | null           // resolved from scene.thumbnail_artifact_key once set
  error_message: string | null           // renamed from `error` for clarity
}
```

**Breaking deltas:**

- `job_id` → `render_id`. The DB `Render.id` *is* the handle.
- `status` adopts the backend `Render.status` enum verbatim. `succeeded` → `final_ready`. `rendering` is split into `queued | preview_ready` (intermediate state is observable).
- `generating` is new (covers the agent-call-in-flight window introduced by `POST /scenes/{id}/generate`).
- `scene_id`, `content_hash`, `thumbnail_url` are new.
- `error` → `error_message`.

**Frontend rename impact** (all in `layersense_frontend/src/`):

- `types.ts` — replace `RenderJobSnapshot` with the new shape; the `VideoPlayerStatus` UX type is **deleted**; `VideoPlayer` props use the backend status directly.
- `hooks/useRenderJob.ts` — terminal-state check changes from `status === 'succeeded' | 'failed'` to `status === 'final_ready' | 'failed'`. The `version`-based long-poll API contract on the controller side is preserved (`afterVersion`, `waitSeconds`).
- `components/VideoPlayer.tsx` — props become `{ previewUrl, finalUrl, thumbnailUrl, errorMessage, status: RenderJobSnapshot['status'] }`. The `statusLabel` map is rewritten against the new enum:
  - `generating` → "Generating scene from prompt..."
  - `queued` → "Queueing render..."
  - `preview_ready` → "Preview ready. Waiting for final render..."
  - `final_ready` → "Final render ready"
  - `failed` → "Error"
- `App.tsx` / new routes — pass through the new field names. No semantic change in flow.

**Tests:**

- Existing `useRenderJob.test.ts` and `VideoPlayer.test.tsx` are updated in the same PR. Snapshots regenerated.
- A new vitest case verifies that an incoming snapshot with a legacy `status: 'succeeded'` value fails type-narrowing in CI (proves the cutover is enforced).

**Why no dual-shape support:** the only consumers of `RenderJobSnapshot` are the frontend in the same monorepo and the e2e test. Both are updated atomically. A transition window adds zero value and doubles the surface.

### Frame diff algorithm

Triggered on `PATCH /scenes/{id}` whenever the request body includes `excalidraw_scene_json`. The algorithm runs inside the same DB transaction as the scene update.

**Inputs:**
- `incoming_frames: list[ExcalidrawFrameElement]` — frame elements in `excalidraw_scene_json.elements`, in their array order. Each has a stable Excalidraw `id` (string) and may have `name` / other Excalidraw metadata.
- `existing_rows: list[Frame]` — `SELECT * FROM frame WHERE scene_id = :scene_id ORDER BY order_index ASC`.

**Behavior (hard-delete v1, locked decision):**

```
incoming_ids = [e.id for e in incoming_frames]
existing_ids = [r.excalidraw_frame_id for r in existing_rows]

# 1. Hard-delete: any existing row whose excalidraw_frame_id is not in incoming_ids
#    is DELETEd. ON DELETE CASCADE removes any future per-frame artifacts.
#    Any prompt_augmentation text on the deleted row is GONE. No rescue, no archive.
to_delete = [r for r in existing_rows if r.excalidraw_frame_id not in set(incoming_ids)]
for r in to_delete: session.delete(r)

# 2. Insert: any incoming frame id not in existing_ids becomes a new Frame row.
existing_by_eid = {r.excalidraw_frame_id: r for r in existing_rows}
for new_index, e in enumerate(incoming_frames):
    if e.id not in existing_by_eid:
        session.add(Frame(
            id=uuid4(),
            scene_id=scene_id,
            excalidraw_frame_id=e.id,
            order_index=new_index,
            prompt_augmentation="",   # default; user fills it later via FrameList
            created_at=now(),
        ))

# 3. Reorder: any retained row whose new index differs from its current order_index
#    is updated. prompt_augmentation is preserved verbatim.
for new_index, e in enumerate(incoming_frames):
    if e.id in existing_by_eid:
        row = existing_by_eid[e.id]
        if row.order_index != new_index:
            row.order_index = new_index
            row.updated_at = now()
```

**Collision rule (Excalidraw duplicates a frame id — should not happen, but the spec must cover it):**

- If `incoming_frames` contains two elements with the same `excalidraw_frame_id`, the controller responds `HTTP 422` with `detail: "duplicate excalidraw frame id in payload: <id>"`. No partial write — the entire `PATCH /scenes/{id}` aborts. Excalidraw frame ids are nanoid-shaped and collision-free in practice; this guard exists to fail loud rather than silently corrupting `order_index`.

**Atomicity:**
- All three phases run in the same SQLAlchemy session and commit together. A failure in any phase rolls the whole `PATCH` back; the client retries.

**Explicitly out of scope (deferred, possibly never):**

- Soft-delete / `deleted_at` column on `Frame`. Would let "undo frame delete in Excalidraw" recover the row. Not added: single-user, dev stage, frame deletes are user-driven and the user can re-author augmentation text trivially.
- Archiving deleted frames' `prompt_augmentation` to a per-project `deleted_frame_notes` log. Considered and rejected: pollutes the schema for a once-per-blue-moon convenience.
- Detecting "frame rename" vs "delete + insert" (Excalidraw might reassign ids on certain edits). Not detected; treated as delete + insert. If this turns out to be a real pattern in Excalidraw's behavior, revisit with concrete repro.

**User-visible warning:** the SceneEditor surfaces a tooltip on the FrameList: *"Deleting a frame in the canvas permanently removes its prompt augmentation."* One small UX line; appears next to the FrameList header.

### Persistence schema deltas

**None.** The normalized Step 2 schema (per overview) already includes `scene.thumbnail_artifact_key` and the `generating` status value. If you find them missing because Step 2 shipped before normalization, add a focused migration in this PR; otherwise no schema work here.

---

## File-level changes

### New (controller)

- `layersense_controller/src/layersense_controller/api/{__init__,projects,scenes,frames,generate,dependencies}.py`
- `layersense_controller/src/layersense_controller/services/agent_client.py`
- `layersense_controller/src/layersense_controller/render_tasks_generate.py` — the `generate_and_render` Taskiq task; or fold into existing `render_tasks.py` if it stays under ~300 LOC
- `layersense_controller/tests/integration/test_{projects,scenes,frames,generate}_api.py`
- `layersense_controller/tests/unit/test_agent_client.py`

### New (frontend)

- `src/routes/{ProjectListRoute,ProjectDetailRoute,SceneEditorRoute}.tsx`
- `src/components/{FrameList,SceneCard,ProjectCard}.tsx`
- `src/hooks/{useDebouncedAutosave,useScene,useProjects,useProject}.ts`
- `*.test.tsx` / `*.test.ts` for each

### Modified (controller)

- `layersense_controller/src/layersense_controller/main.py` — register new routers.
- `layersense_controller/src/layersense_controller/router.py`:
  - Delete the `_default` project shim from Step 3.
  - `POST /render` keeps its current shape (per C3a): `{ scene_id?, source_code, content_hash, cli_flags? }`. Used by the (future) watcher and tests.
- `layersense_controller/src/layersense_controller/render_tasks.py` — existing render task is reused as a sub-step of `generate_and_render`, or factored into a shared internal function.
- `layersense_controller/src/layersense_controller/config.py` — add `agent_base_url`, `agent_timeout_seconds`.
- `docker-compose.yml` — set `LAYERSENSE_AGENT_BASE_URL=http://agent:8000` on `controller` and `controller-worker`.

### Modified (agent)

- `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`:
  - Request schema: `{ prompt, excalidraw_scene_json, frames: [...] }`. Drops `conversation_id`.
  - Response schema: `{ source_code, content_hash }`. Drops `conversation_id`.
  - Prompt-construction logic accepts structured `frames` input; starting heuristic concatenates `frame.prompt_augmentation` strings as a prefix. Smarter behavior in Step 5.

### Modified (frontend)

- `src/App.tsx` — replace single-page layout with `<BrowserRouter>` + route definitions.
- `src/api.ts` — add project/scene/frame/generate endpoints. **Remove the `postAnimation` helper that called the agent directly.**
- `src/types.ts` — add `Project`, `Scene`, `Frame` types matching the controller's Pydantic schemas.
- `src/hooks/useRenderJob.ts` — handle the new `generating` and `failed` states.

### Deleted

- The `_default` Project shim in `layersense_controller`.
- Any frontend code that called the agent's `/api/v1/animation` directly.

### Modified (docs)

- `README.md`:
  - "Current Status" → describes project/scene/frame model, three-route frontend, controller-as-orchestrator.
  - "Current Architecture" → updated flow diagram showing browser → controller → agent (no browser → agent edge).
  - Add a "Persistence" section pointing at the schema in `layersense_persistence`.
- `docs/ROADMAP.md` — update near-term focus.

---

## Test plan

### Controller (integration, `TestClient(app)`)

For each of `test_projects_api.py`, `test_scenes_api.py`, `test_frames_api.py`:

- CRUD happy paths.
- Validation errors (empty name, invalid IDs, duplicate `(project_id, name)`).
- Cascade deletes.
- `PATCH /scenes/{id}` with new `excalidraw_scene_json` whose frame elements differ: verify diff inserts/deletes correctly and preserves `prompt_augmentation` on retained frames.

For `test_generate_api.py`:

- Happy path with `respx`-mocked agent: returns `render_id` immediately; long-poll progresses `generating → queued → preview_ready → final_ready`; final blobs exist in the test object store.
- Cache-hit path for `POST /api/v1/scenes/{id}/generate`: For /generate: the worker ALWAYS calls the agent first. Cache hit is checked AFTER agent returns — if content_hash matches existing artifacts, skip Manim render and copy keys. Agent call is never skipped for /generate. Cache-hit-skips-agent only applies to POST /render.
- Agent-failure path: mocked agent returns 500; Render.status becomes `failed` with `error_message` populated; long-poll resolves with `failed`.
- Agent-timeout path: mocked agent hangs; AgentClient times out; Render.status becomes `failed`.
- Concurrent generates for the same scene-with-identical-`content_hash`: deduped by `layersense:lock:render:{hash}`; only one Manim invocation.

For `test_agent_client.py` (unit):

- Builds correct request body from `(prompt, excalidraw_scene_json, frames)`.
- One retry on `httpx.ConnectError`; no retry on 4xx/5xx.
- Timeout config respected.
- Maps response JSON to `AgentResponse`; raises typed errors on shape mismatches.

### Agent (integration)

- `POST /api/v1/animation { prompt, excalidraw_scene_json, frames }` happy path: returns `{ source_code, content_hash }` matching `sha256(source_code.encode())`.
- Verifies `frames` field is consumed (not silently dropped) by checking the LLM payload via VCR cassette.
- No backward compat. Cassette refresh expected.

### Frontend (vitest)

- `useDebouncedAutosave` debounces correctly, queues at most one in-flight request, retries once on failure.
- `useScene` loads scene + frames, exposes `mutate` helpers, applies edits while autosave is in flight.
- Each route renders, navigates, handles loading/error states.
- `FrameList` renders frames in order, edits propagate to autosave.
- `useRenderJob` handles new `generating` state.
- Existing component tests adjusted for new prop shape.
- **No test mocks `localhost:8000`.**

### e2e

- `tests/e2e/test_dev_stack_e2e.py`:
  - Create project via API, create scene, PATCH excalidraw + prompt, `POST /scenes/{id}/generate`, long-poll until `final_ready`, assert preview/final URLs return 200 with non-empty body, assert `scene.current_render_id` and `scene.thumbnail_artifact_key` are set.
  - Replaces the existing single-shot e2e test.

---

## Acceptance criteria

1. `grep -rn "_default" layersense_controller/src/ layersense_persistence/src/` returns no matches (the shim and its row are gone after migration `0003`).
2. `grep -rn "localhost:8000\|http://agent" layersense_frontend/src/` returns no matches. Browser does not talk to the agent.
3. `react-router-dom` is the only new runtime dependency in `layersense_frontend/package.json`.
4. `uv run --all-packages pytest -m unit` and `-m integration` pass; coverage for new controller `api/*.py` ≥ 95%; `services/agent_client.py` ≥ 95%.
5. `bun run --cwd layersense_frontend test` (vitest) passes; new hooks/components ≥ 90% covered; updated `Canvas.test.tsx` covers the new `onChange` callback and `initialScene` hydration.
6. `just e2e` passes against the local Docker stack with the rewritten e2e test.
7. `just test-e2e` passes.
8. `just lint` passes (Python + ESLint + tsc).
9. After `just db_reset && just docker` from a clean state:
   - `SELECT COUNT(*) FROM project WHERE slug='_default'` returns 0 (anti-resurrection guard).
   - `http://localhost:3000/` shows an empty project list with "New Project".
   - Creating a project, then a scene, persists across page reload.
   - Editing Excalidraw + prompt autosaves within ~1s of typing pause.
   - Clicking Generate is disabled while `isSaving` is true; verified by a vitest case + an e2e probe.
   - Clicking Generate produces a render whose preview/final play.
   - Closing and reopening the tab restores the scene with its last-rendered video and thumbnail.
10. README accurately describes the controller-as-orchestrator architecture.
11. The agent's `POST /api/v1/animation` request schema is `{ prompt, excalidraw_scene_json, frames }` and response is `{ source_code, content_hash }`. Verified by AST/grep on Pydantic models.
12. `POST /render` still exists (per C3a) but no frontend code references it. Verified by grep on `layersense_frontend/src/`.
13. The agent does not import `layersense_persistence` or `layersense_storage`. Verified by grep.
14. `RenderJobSnapshot` (Python + TypeScript) carries exactly `{ render_id, scene_id, content_hash, status, version, preview_url, final_url, thumbnail_url, error_message }`. No legacy fields (`job_id`, `error`, `succeeded`). Verified by Pydantic schema + vitest type test.
15. `Frame` rows for a scene are deleted when their `excalidraw_frame_id` disappears from `excalidraw_scene_json` (verified by integration test covering insert, reorder, and hard-delete paths).
16. `PATCH /scenes/{id}` with duplicate `excalidraw_frame_id`s in `excalidraw_scene_json.elements` returns `HTTP 422` and rolls back the entire transaction (verified by integration test).
17. Migration `0003_drop_default_project_shim.py` is irreversible (`downgrade()` raises) and runs cleanly against a DB with a `_default` project containing scenes + renders; companion `scripts/wipe_default_shim_blobs.py` is idempotent on a missing-blob input.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Long Taskiq task (agent + manim preview + manim final) holds a worker for minutes | Acceptable for single-user. If it bites, split per C2b — small refactor; the state machine on Render already accommodates intermediate states. |
| Agent failure leaves Render in `generating` forever if the task crashes mid-flight before catching the error | Wrap the task body in a top-level `try/except/finally` that sets `status="failed"` on any unhandled exception. Verified by a fault-injection test. |
| Frame diff hard-delete loses `prompt_augmentation` if user temporarily deletes a frame in Excalidraw to redraw | **Documented v1 behavior** (locked decision). The SceneEditor surfaces a one-line tooltip warning on FrameList. Single-user; if this turns into a real workflow pain, add 30-day soft-delete on `Frame` in a follow-up. |
| `_default` shim wipe migration `0003` cannot be safely rerun if blobs were already deleted | Companion script `scripts/wipe_default_shim_blobs.py` is idempotent — `ObjectStore.delete()` on a missing key is a no-op. Migration `downgrade()` raises explicitly. |
| `RenderJobSnapshot` schema break breaks long-lived browser tabs across deploy | Single-user dev; full-page reload after deploy is acceptable. Frontend version-check is out of scope. |
| Frame diff fires on every Excalidraw `onChange` flush, generating many small DB transactions | The 800ms debounce on autosave consolidates `onChange` bursts; one `PATCH` per pause, one diff per `PATCH`. Negligible at single-user scale. |
| Excalidraw assigns a *new* `excalidraw_frame_id` to a renamed/recreated frame, treated as delete + insert | Documented as a known edge case; behavior is hard-delete of the old row including augmentation. If observed in practice, revisit with a concrete repro. |
| Frontend bundle growth from `react-router-dom` | ~10kb gzipped. Negligible. |
| The frame CRUD endpoints invite confusion | Router docstrings flag them as internal. Open to suppressing them entirely on push-back. |
| Cassette refresh churn on agent VCR tests (second time after Step 3) | One commit; called out in PR description. The agent's contract is finally stable after this step. |
| Long single PR | Split rule: (a) `_default` wipe migration + project/scene/frame CRUD endpoints + agent client + agent contract change, (b) `/scenes/{id}/generate` orchestration task + thumbnail capture + e2e, (c) frontend revamp + `RenderJobSnapshot` cutover. Each is independently shippable; `just e2e` keeps passing throughout. **Recommendation: three PRs in order.** |

---

## Estimated shape

- Controller: ~800 LOC src + ~900 LOC tests
- Agent: ~100 LOC delta + ~150 LOC tests
- Frontend: ~1200 LOC src + ~600 LOC tests
- Docs: ~80 LOC

Total: ~3800 LOC delta. Three-PR split recommended.

---

## Assumptions

1. `react-router-dom` v7+. Standard, fits Vite + React 19.
2. `respx` for mocking httpx in agent-client tests; `pytest-httpx` is a fine alternative.
3. Last-write-wins autosave is acceptable.
4. Single Taskiq task for the whole `(generate, render)` lifecycle (per C2a).
5. `POST /render` stays for the future watcher (per C3a).
6. The agent receives structured `frames` in this step but the prompt-construction *behavior* is a placeholder (concatenated augmentations) until Step 5.
7. Including `scene.thumbnail_artifact_key` in this step is acceptable.
8. The frame CRUD endpoints stay exposed but are documented as internal.
9. Three-PR split as listed in the Risks table's "Long single PR" row.
10. `isSaving`-gated Generate is a sufficient race-prevention mechanism. No `Render`-row scene-state snapshot fields are introduced.
11. Frame diff uses hard-delete on disappearance, no rescue, no archive. SceneEditor surfaces a one-line warning tooltip.
12. `RenderJobSnapshot` hard cutover with no dual-shape support. Single-user dev; full-page reload after deploy is the migration path.
13. Status vocabulary unifies to the backend `Render.status` enum across the wire. Frontend's UX-shaped `VideoPlayerStatus` enum is deleted; `VideoPlayer` consumes the backend enum directly and owns its own label mapping.
14. `Canvas` keeps its imperative `forwardRef<CanvasHandle>` shape; new `initialScene` + `onChange` props are additive. Generate uses the imperative handle; autosave uses `onChange`.

**Amendment (2026-05-22):** Cache-hit ordering corrected: agent always called for /generate; cache hit is post-agent. Hash terminology unified to single content_hash. Per audit findings 4.1, 4.2.

→ Correct any of these or I proceed to Step 5 (agent refinement endpoint with `parent_render_id` chaining + structured frame-aware prompt construction). Step 5 is where the agent stops being one-shot — the controller calls the agent with the previous Render's source as additional context, and the agent's prompt-composition logic upgrades to use the structured `frames` field meaningfully.
