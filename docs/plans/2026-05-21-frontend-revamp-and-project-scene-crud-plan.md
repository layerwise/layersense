# Frontend Revamp + Project/Scene CRUD + Controller Orchestration — Implementation Plan

**Status:** Proposed
**Step in build order:** 4 of 9
**Depends on:** Step 2 (`layersense_persistence`) merged, Step 3 (`ObjectStore` + `cache.py` deletion) merged
**Unblocks:** Step 5 (agent refinement), Step 6 (project export)

---

## Why this step

This is the first user-visible payoff and the architectural keystone. After this step:

- The frontend has three navigable views: project list → scene list (storyboard) → scene editor (Excalidraw + prompt + video).
- Projects and scenes are persistent. Closing the browser tab no longer loses work.
- **The Controller is the orchestrator.** It is the only service the browser talks to. It owns the database, the object store, and the agent dispatch.
- **The Agent is a stateless pure function.** It accepts an inline payload (Excalidraw JSON + prompt + frames), returns Manim source code. Nothing else. It has no awareness of Projects, Scenes, the database, or the object store.
- The `_default` Project shim from Step 3 is **deleted**. Real `POST /projects` and `POST /projects/{id}/scenes` endpoints replace it.
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
- **Frames are derived-but-persisted.** When `PATCH /scenes/{id}` updates `excalidraw_scene_json`, the controller diffs the Excalidraw frame elements against existing `frame` rows: new frame ids → insert; missing → delete; existing → preserve `prompt_augmentation`, update `order_index` to match Excalidraw scene order. Frame existence is normally Excalidraw-driven; the explicit Frame CRUD endpoints exist for tests and future tooling, with docstrings flagging them as internal.
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
     d. Compute effective_hash = sha256(content_hash + canonical_cli_flags_json)
     e. RendersRepository.find_by_content_hash(effective_hash):
          - hit + blobs exist → reuse: copy preview/final/source keys to this Render row,
            status="final_ready", scene.current_render_id=render_id, publish event, return
          - miss or drift → continue
     f. ObjectStore.put(render_source_key(effective_hash), source_code.encode())
        Set Render.scene_py_artifact_key=..., status="queued"
     g. Acquire layersense:lock:render:{effective_hash} (Step 1's primitive)
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
    Canvas.tsx                  # existing; receives initial scene + onChange
    VideoPlayer.tsx             # existing; receives content_hash
    FrameList.tsx               # new; right-rail panel
    SceneCard.tsx               # new; thumbnail + name in project detail
    ProjectCard.tsx             # new; tile in project list
  hooks/
    useRenderJob.ts             # existing; minor edits for new states (generating, failed)
    useDebouncedAutosave.ts     # new
    useScene.ts                 # new
    useProjects.ts              # new
    useProject.ts               # new
  api.ts                        # extended with project/scene/frame/generate endpoints
                                # NB: the browser→agent direct call is removed entirely
  types.ts                      # extended with Project, Scene, Frame DTOs
```

**Deliberately small dep additions:**

- `react-router-dom` (only new runtime dep).
- No data-fetching library, no state management library, no UI component library.

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
- **Generate is disabled while `isSaving` is true OR while `lastSavedAt` is older than the most recent local edit.** This eliminates the autosave race that motivated Option C.
- Last-write-wins. No version field, no `If-Match`.

### Persistence schema deltas

Step 2's schema covers everything except:

- **`scene.thumbnail_artifact_key TEXT NULL`** — set by the worker after preview render. Migration `0003_add_scene_thumbnail.py` (or fold into 0002 if not yet finalized).
- **`render.status` enum gains `"generating"`** — new pre-render state. No migration needed (status is TEXT); update controller's allowed-values check and test assertions.

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
- Cache-hit path: a previous Render with the same effective hash exists; agent **is not called** (verified via `respx`); status goes straight to `final_ready`.
- Agent-failure path: mocked agent returns 500; Render.status becomes `failed` with `error_message` populated; long-poll resolves with `failed`.
- Agent-timeout path: mocked agent hangs; AgentClient times out; Render.status becomes `failed`.
- Concurrent generates for the same scene-with-identical-effective-hash: deduped by `layersense:lock:render:{hash}`; only one Manim invocation.

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

1. `grep -rn "_default" layersense_controller/src/` returns no matches.
2. `grep -rn "localhost:8000\|http://agent" layersense_frontend/src/` returns no matches. Browser does not talk to the agent.
3. `react-router-dom` is the only new runtime dependency in `layersense_frontend/package.json`.
4. `uv run --all-packages pytest -m unit` and `-m integration` pass; coverage for new controller `api/*.py` ≥ 95%; `services/agent_client.py` ≥ 95%.
5. `npm test` (vitest) passes; new hooks/components ≥ 90% covered.
6. `just e2e` passes against the local Docker stack with the rewritten e2e test.
7. `just test-e2e` passes.
8. `just lint` passes (Python + ESLint).
9. After `just docker` from a clean state:
   - `http://localhost:3000/` shows an empty project list with "New Project".
   - Creating a project, then a scene, persists across page reload.
   - Editing Excalidraw + prompt autosaves within ~1s of typing pause.
   - Clicking Generate produces a render whose preview/final play.
   - Closing and reopening the tab restores the scene with its last-rendered video and thumbnail.
10. README accurately describes the controller-as-orchestrator architecture.
11. The agent's `POST /api/v1/animation` request schema is `{ prompt, excalidraw_scene_json, frames }` and response is `{ source_code, content_hash }`. Verified by AST/grep on Pydantic models.
12. `POST /render` still exists (per C3a) but no frontend code references it. Verified by grep on `layersense_frontend/src/`.
13. The agent does not import `layersense_persistence` or `layersense_storage`. Verified by grep.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Long Taskiq task (agent + manim preview + manim final) holds a worker for minutes | Acceptable for single-user. If it bites, split per C2b — small refactor; the state machine on Render already accommodates intermediate states. |
| Agent failure leaves Render in `generating` forever if the task crashes mid-flight before catching the error | Wrap the task body in a top-level `try/except/finally` that sets `status="failed"` on any unhandled exception. Verified by a fault-injection test. |
| Frame diffing on autosave loses `prompt_augmentation` if user temporarily deletes a frame in Excalidraw to redraw | Documented behavior. Single-user; if it bites, add 30-day soft-delete on Frame in a follow-up. |
| Frontend bundle growth from `react-router-dom` | ~10kb gzipped. Negligible. |
| The frame CRUD endpoints invite confusion | Router docstrings flag them as internal. Open to suppressing them entirely on push-back. |
| Cassette refresh churn on agent VCR tests (second time after Step 3) | One commit; called out in PR description. The agent's contract is finally stable after this step. |
| Long single PR | Split rule: (a) controller API endpoints + agent contract change + agent client, (b) `/scenes/{id}/generate` orchestration task + e2e, (c) frontend revamp. Each is independently shippable; `just e2e` keeps passing throughout. **Recommendation: three PRs in order.** |

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
9. Three-PR split.

→ Correct any of these or I proceed to Step 5 (agent refinement endpoint with `parent_render_id` chaining + structured frame-aware prompt construction). Step 5 is where the agent stops being one-shot — the controller calls the agent with the previous Render's source as additional context, and the agent's prompt-composition logic upgrades to use the structured `frames` field meaningfully.
