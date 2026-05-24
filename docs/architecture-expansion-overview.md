# LayerSense Architecture Expansion — Overview

**Status:** Living document, written 2026-05-21 to anchor a multi-step architecture expansion. Normalized 2026-05-21 to make this file canon over the per-step plans (see "Provenance" entry 6).
**Audience:** Any agent or developer picking up this work cold.
**Reading time:** ~15 minutes. Read this before touching any plan under `docs/plans/2026-05-21-*.md`.

---

## Purpose of this document

LayerSense is evolving from a proof-of-concept architecture to a substrate that can support a real Manim-YouTube-production workflow for a single developer user. The work is broken into 9 sequenced steps, each with a written plan file under `docs/plans/2026-05-21-*.md`. This document captures the **whole picture** so that:

- A new agent session can pick up any step and understand how it fits the whole.
- The user (Mathias) can return to this work after a break without re-deriving the design.
- Decisions and their rationale are preserved, not just the final shape.

If you are about to implement one of the steps, read this document **first**, then the specific plan under `docs/plans/`.

---

## Product vision (one paragraph)

LayerSense is a single-user assistant for producing Manim-rendered YouTube animation videos. The user draws scenes visually in Excalidraw and writes prompts; AI generates Manim Python code; the system renders it to mp4. Each video is composed of multiple **Projects**, each containing multiple **Scenes** (≈ Manim `Scene` subclasses), each composed of multiple **Frames** (Excalidraw-native frames acting as ordered storyboard beats within one `Scene.construct()`). The single user is the developer building the tool; there are no plans for multi-tenancy or auth in the next 12+ months.

---

## Current state (before the expansion)

What exists today, as the migration begins:

- **`layersense_agent`** (FastAPI) — accepts `POST /api/v1/animation` with an inline Excalidraw payload + prompt; generates one Manim `.py` file; writes it to a host-mounted `./layersense_artifacts/code/generated_<conversation_id>.py`; returns `{ conversation_id, scene_path }`.
- **`layersense_controller`** (FastAPI + Taskiq worker) — accepts `POST /render` with a `scene_path`; computes content hash; checks `./layersense_artifacts/cache/index.json`; queues render via Taskiq; worker shells out to Manim CLI; outputs land under `./layersense_artifacts/scenes/`. Browser-facing routes `/artifacts/by-hash/...` and `/artifacts/scenes/...` stream the mp4s. Render-job state in Redis with long-poll.
- **`layersense_frontend`** (React + Vite) — single-page PoC: one Excalidraw canvas, one prompt textarea, one video player. No routing, no persistence; closing the tab loses everything.
- **Persistence:** none for user content. Cache `index.json` + filesystem + Redis ephemeral job state. No database.
- **Known bug (documented in README):** `fcntl.flock` on `cache/index.json` is unreliable on Docker Desktop shared volumes.

What's working:
- Generate → render → preview → final loop end-to-end via `just docker` + browser at `localhost:3000`.
- Live-stack tests via `just e2e`; reproducible full-suite via `just test-e2e`.
- Strong integration test coverage on the agent; first slice on the controller.

What's missing for the vision:
- No persistent project/scene model. Every "Generate" is a fresh ephemeral conversation.
- No navigation UI. Scenes can't be revisited.
- No multi-scene structure inside a project.
- No frame-as-storyboard composition.
- File-based artifact storage is brittle (the lock bug above) and not abstracted.

---

## Target architecture (end-state of this expansion)

A clean three-actor model with strict role separation:

```
                ┌─────────────────────────┐
                │        Browser          │   thin client, view + input only
                │   (React + Excalidraw)  │   talks to ONE service: the controller
                └────────────┬────────────┘
                             │ HTTPS (REST)
                             ▼
                ┌─────────────────────────┐
                │       Controller        │   the orchestrator
                │ (FastAPI + Taskiq)      │   owns: DB, ObjectStore writes,
                │                         │          render queue, agent dispatch
                └──┬──────────────────┬───┘
                   │                  │
        ┌──────────▼─────────┐  ┌─────▼──────────────┐
        │   SQLite + Redis   │  │       Agent        │   pure function
        │   + ObjectStore    │  │  (FastAPI)         │   stateless code generator
        │                    │  │                    │   no DB, no ObjectStore
        └────────────────────┘  └────────────────────┘   knows nothing about
                                                          Projects or Scenes
```

**Three rules that make this architecture coherent:**

1. **The browser only talks to the controller.** Never to the agent directly. (Today's browser-to-agent path is removed in Step 4.)
2. **The controller is the only writer to durable state** — SQLite (Project/Scene/Frame/Render rows) and ObjectStore (mp4s, generated `.py` files). The agent and the worker do not write to durable state directly.
3. **The agent is a pure function.** It takes an inline payload (`prompt`, `excalidraw_scene_json`, `frames`), returns raw Manim source bytes. It has no settings pointing at the controller, no DB access, no ObjectStore awareness. Replaceable with any equivalent code generator.

These three rules are what the Option C debate (see "Key design decisions" below) settled.

---

## Data model (target)

Lives in a new uv workspace package: `layersense_persistence`. SQLite, single-writer (controller), WAL mode. **Imported by `layersense_controller` only** (the agent has no DB access — Option C). Cross-service DTOs (Pydantic) are exposed in `layersense_persistence.schemas`.

```
Project
  id              uuid TEXT PK
  name            TEXT NOT NULL
  slug            TEXT UNIQUE NOT NULL
  default_render_config_json   TEXT DEFAULT '{}'
  created_at, updated_at

Scene
  id              uuid TEXT PK
  project_id      FK Project (CASCADE)
  name            TEXT NOT NULL
  order_index     INT NOT NULL                       UNIQUE(project_id, order_index)
                                                            UNIQUE(project_id, name)
  prompt          TEXT DEFAULT ''
  excalidraw_scene_json   TEXT DEFAULT '{}'          # inline JSON column (decided)
  current_render_id       FK Render (SET NULL)       # denormalized for nav UI
  thumbnail_artifact_key  TEXT NULL                  # set after preview render
  created_at, updated_at

Frame                                                # storyboard beat inside a Scene
  id              uuid TEXT PK                       # = one Manim section in construct()
  scene_id        FK Scene (CASCADE)
  order_index     INT NOT NULL                       UNIQUE(scene_id, order_index)
  excalidraw_frame_id     TEXT NOT NULL              UNIQUE(scene_id, excalidraw_frame_id)
  prompt_augmentation     TEXT DEFAULT ''
  created_at, updated_at

Render
  id              uuid TEXT PK
  scene_id        FK Scene (CASCADE)
  parent_render_id        FK Render NULL (SET NULL)  # for refinement chains, Step 5
  refinement_prompt       TEXT DEFAULT ''            # prompt instruction for refinement renders (Step 5)
  content_hash    TEXT NOT NULL                      # sha256(scene_py + cli_flags)
  status          TEXT NOT NULL                      # generating | queued | preview_ready | final_ready | failed
  scene_py_artifact_key   TEXT NULL                  # set after agent returns (nullable while status=generating)
  preview_artifact_key    TEXT NULL
  final_artifact_key      TEXT NULL
  log_artifact_key        TEXT NULL                  # Manim stdout/stderr
  cli_flags_json          TEXT DEFAULT '{}'
  conversation_id         TEXT                       # legacy carryover, agent input id
  error_message           TEXT
  created_at, updated_at
  INDEX(scene_id, created_at DESC)
  INDEX(content_hash)
```

**Schema notes on nullability:** `scene_py_artifact_key` is nullable to admit `status="generating"` (Render row created when the user clicks Generate, agent hasn't returned yet). It becomes non-null as soon as the agent response is persisted. `preview_artifact_key` is set at `preview_ready`; `final_artifact_key` and `log_artifact_key` at `final_ready`.

**Schema invariants:**
- `Frame` rows are **derived from Excalidraw scene state**, not authored independently. On `PATCH /scenes/{id}` the controller diffs `excalidraw_scene_json` against existing `Frame` rows: new frame ids → insert; missing → delete; existing → preserve `prompt_augmentation`, update `order_index`.
- `Render` rows are **immutable in identity**. New render = new row. Multiple rows can share `content_hash` (cache reuse) and point at the same blob keys.
- The deprecated `cache/index.json` is replaced by `SELECT * FROM render WHERE content_hash = ?`.

---

## Storage model (target)

Lives in a new uv workspace package: `layersense_storage`. Defines the `ObjectStore` protocol and a local-filesystem implementation. Used by `layersense_controller` (the only writer) and the worker.

```
ObjectStore protocol:
  put(key, bytes), put_stream(key, stream), get(key), open(key),
  head(key), delete(key), list_prefix(prefix), url_for(key)
```

**Canonical key layout** (this is the single source of truth — all per-step plan files cite this):

```
renders/{content_hash}/source.py                  # generated Manim source, immutable per hash
renders/{content_hash}/preview.mp4                # rendered preview
renders/{content_hash}/final.mp4                  # rendered final
renders/{content_hash}/manim.log                  # captured worker stdout/stderr
renders/{content_hash}/thumbnail.png              # first-frame snapshot, set after preview
projects/{project_id}/scenes/{scene_id}.py        # mutable current scene source (Step 7+, package-mode projects)
projects/{project_id}/components/{name}.py        # reusable components (Step 7+)
projects/{project_id}/assets/{asset_id}/{filename}  # binary assets (Step 7+)
```

**Canonical hash definition:** `content_hash = sha256(scene_py_bytes + canonical(cli_flags_json))`. A single hash covers both source identity and render configuration. All plans use this definition; there is no separate "effective hash" or "source hash." The canonical serialization of `cli_flags_json` is compact-sorted JSON (`json.dumps(flags, sort_keys=True, separators=(",", ":"))`).

**Why content-addressed renders.** Everything for one render lives under one `renders/{content_hash}/` prefix. Two `Render` rows that converge on the same source bytes share the blobs for free (deduplication at the storage layer). The directory is trivially deletable and exportable as a unit.

**Why a separate `projects/{project_id}/` tree (Step 7+).** The `renders/` tree stores immutable, per-render snapshots. The `projects/` tree stores the **mutable current state** of a project's source files — the working copy the agent reads and writes. Renders snapshot from working copy into the content-addressed `renders/` tree at render time. The two trees serve different purposes; they coexist.

**Storage root:** `./layersense_artifacts/storage/` (default for `LAYERSENSE_STORAGE_ROOT`).

**Implementation:** `LocalFSObjectStore` only, for now. Atomic writes via temp-file + `os.replace`. S3-compatible impl is a Step 8 follow-up; the protocol is designed to admit it without caller changes.

---

## The canonical request flow (target, after Step 4)

The user is editing scene `scn_abc123` in the browser. Autosave has been quietly `PATCH`-ing the controller every ~800ms. The DB holds the latest Excalidraw JSON, prompt, and frames.

User clicks **Generate**.

```
1. Browser → Controller        POST /api/v1/scenes/scn_abc123/generate {cli_flags?}
                               (tiny payload)
2. Controller                  - reads scene + frames from DB (one transaction)
                               - creates Render row (status=generating)
                               - dispatches single Taskiq task
                               → returns {render_id, status:"generating"} immediately
3. Browser                     starts long-polling GET /render-jobs/{render_id}
                               (unchanged existing endpoint)

   [meanwhile, in the Taskiq task body:]

4. Worker → Agent              POST /api/v1/animation
                               {prompt, excalidraw_scene_json, frames}
                               (big payload, ok — internal compose network)
5. Agent                       calls LLM, returns raw Manim Python source bytes
                               → response: {scene_py_bytes, content_hash}
                               (agent does NOT write to ObjectStore)
6. Worker (still in same task) - writes source to ObjectStore at
                                 renders/{content_hash}/source.py
                               - looks up Render rows by (content_hash, cli_flags)
                               - cache hit + blobs present? mark final_ready, publish event, done
                               - cache miss? proceed to render
7. Worker                      - materializes source to /tmp workdir
                               - runs Manim preview → ObjectStore.put preview.mp4
                               - updates Render (status=preview_ready), publishes event
                               - runs Manim final → ObjectStore.put final.mp4
                               - updates Render (status=final_ready, log_artifact_key, thumbnail), publishes event
                               - cleans up /tmp workdir

8. Browser                     long-poll picks up status changes
                               loads /artifacts/by-hash/{content_hash}/{preview|final}
                               (controller streams from ObjectStore)
```

**Key properties of this flow:**

- **One identifier (`render_id`) covers the whole generate→render lifecycle.** No two-phase commit on the client side.
- **The agent call is off the request hot path.** The browser's HTTP request returns in milliseconds.
- **The agent is replaceable.** Swap the URL, swap the implementation, no other service notices.
- **The agent never touches durable state.** Pure function in, pure function out.
- **Render dedup is automatic.** Same `content_hash` → same blob keys → cache reuse.
- **Concurrent identical renders are deduped via Redis lock** `layersense:lock:render:{effective_hash}` (Step 1's primitive applied at the worker entry).

---

## Two preserved endpoints for non-generate flows

- **`POST /render`** stays in the controller. Takes an explicit `scene_source_key` + `content_hash`. No agent call. Used by:
  - The (deferred) watcher flow in Step 7+.
  - Tests that want to render a known source without LLM nondeterminism.
- **Browser does not use `/render`** after Step 4. It only uses `/api/v1/scenes/{id}/generate` plus the existing render-job long-poll.

This split — `/generate` for "regenerate code from scratch and render", `/render` for "render this explicit pre-existing source" — is intentional and small.

---

## Migration: the 9-step plan

All nine steps have detailed plan files written. The summaries below are the canonical short version; defer to each plan file for the full design.

### Step 1: Redis-backed render lock — `2026-05-21-redis-render-lock-plan.md`

Replaces `fcntl.flock` on `cache/index.json` with a Redis `SET NX PX` lock. Independent, fixes the documented Docker contention bug. Parallel-shippable with Step 2.

**Module constants** (not settings fields) for TTL / acquire timeout. Defaults: 30s TTL, 10s acquire timeout, 50ms poll.

The lock primitive (`locks.py`) also gets reused in Step 3 for `layersense:lock:render:{hash}` dedup.

### Step 2: `layersense_persistence` package — `2026-05-21-layersense-persistence-package-plan.md`

New uv workspace member. SQLite + repositories + Pydantic DTOs. Boundary-pure (no FastAPI / Taskiq / SQLAlchemy in DTOs). No HTTP, no business logic. Parallel-shippable with Step 1.

Schema as written above. WAL mode, `PRAGMA foreign_keys=ON`. `0001_initial.py` is the only migration worth preserving; later schema changes are reset-friendly first-version edits, not migration-sensitive rollout work.

### Step 3: ObjectStore + `cache.py` deletion — `2026-05-21-object-store-and-renders-repository-plan.md`

**The substrate change.** Single PR.

- New `layersense_storage` workspace package with `ObjectStore` protocol + `LocalFSObjectStore`.
- Deletes `layersense_controller/src/layersense_controller/cache.py` entirely.
- `RendersRepository` (from Step 2) becomes the system of record for content-hash → artifact mapping.
- Agent and controller HTTP contract changes: `scene_path` is replaced by `scene_source_key` + `content_hash`.
- Compose stops mounting the shared `./layersense_artifacts/code/` host volume; both services mount only `./layersense_artifacts/storage/`.
- Watcher is disabled (raises on startup) — comes back in Step 7.
- Implicit `_default` Project shim for one step. Deleted in Step 4.

**Amendment from the original Step 3 plan** (per Option C decision):
- The **agent does not write to ObjectStore**. Step 3 wires the controller as the ObjectStore writer; the agent's role is reduced to "receive payload, return raw Python source bytes." This reverses an earlier draft where the agent wrote and returned a key.
- If implementing Step 3 from its current plan file, apply this amendment: agent's `POST /api/v1/animation` returns `{ scene_py_bytes, content_hash }`, not `{ scene_source_key, content_hash }`. The controller writes to ObjectStore.

### Step 4: Frontend revamp + Project/Scene CRUD — `2026-05-21-frontend-revamp-and-project-scene-crud-plan.md`

First user-visible payoff. Three-PR split recommended (controller API → flow rewiring → frontend).

- Controller exposes Project/Scene/Frame CRUD endpoints under `/api/v1/...`.
- Frontend gains `react-router-dom`: `/`, `/projects/:id`, `/projects/:id/scenes/:id`.
- Autosave wires Excalidraw + prompt edits to `PATCH /scenes/{id}` (debounced 800ms).
- **The browser stops calling the agent directly.** New endpoint: `POST /api/v1/scenes/{id}/generate`. Browser hits this; controller orchestrates the agent call internally inside the Taskiq task.
- `_default` Project shim from Step 3 is deleted.
- Frame UI is minimal: read-only frame name + `prompt_augmentation` textarea per frame. No drag-to-reorder.
- `scene.thumbnail_artifact_key` populated by worker on first preview.

**Amendment from the original Step 4 plan** (per Option C decision):
- The agent does **not** fetch scene state from the controller. The controller assembles the agent payload from DB state and passes it inline to the agent.
- The agent has **no** `controller_base_url` setting. There is no `scene_fetcher.py`.
- The new generate endpoint is on the **controller**, not the agent. `POST /api/v1/scenes/{id}/generate` returns `{render_id, status}` immediately; the browser long-polls the existing `/render-jobs/{render_id}` endpoint.
- The agent's `POST /api/v1/animation` keeps today's inline-payload shape, with no `scene_id` field. It is called server-to-server from the controller's Taskiq worker only.

### Step 5: Agent refinement (Tier 1) — `2026-05-21-step-5-agent-refinement-plan.md`

Adds `POST /api/v1/scenes/{id}/refine` on the controller. Uses `parent_render_id` to chain. Agent receives the previous render's source + new prompt diff as inline context. No new agent infrastructure — same pure-function shape, richer payload.

### Step 6: Project export — `2026-05-21-step-6-project-export-plan.md`

`GET /api/v1/projects/{id}/export` produces a downloadable source-only zip containing all scene `.py` files, a manifest, and a generated `manim.cfg` (no mp4 renders). Cheap once Steps 2 + 3 + 4 are in.

### Step 7: Multi-file project + components library (Agent Tier 2) — `2026-05-21-step-7-multi-file-projects-and-components-plan.md`

Project becomes a real directory on ObjectStore at `projects/{project_id}/` with `scenes/`, `components/`, `assets/`. Agent's response schema upgrades from a single `source_code` string to a `FileBundle` (list of files with relative paths) so it can emit reusable component modules alongside the scene file. Watcher comes back, project-aware.

The mutable `projects/{project_id}/scenes/{scene_id}.py` working-copy tree coexists with the immutable `renders/{content_hash}/source.py` snapshot tree (see "Storage model" above). Renders snapshot the working copy at render time.

**Open architectural question (DQ1 in the plan body):** whether the agent gains a constrained tool surface (`read_file`, `write_file`, `list_dir`, `run_render`) or stays pure-function with an inline `FileBundle` response. The Step 7 plan currently recommends inline `FileBundle` to preserve Option C; this overview deferred to the plan's recommendation. Decide before implementing Step 7.

### Step 8: S3-compatible ObjectStore backend — `2026-05-21-step-8-s3-object-store-backend-plan.md`

`S3ObjectStore` impl added alongside `LocalFSObjectStore`. **The local-FS backend remains the default and the only production path.** The S3 implementation is built so the abstraction is exercised by real code (not just typed against), and to unblock an opt-in dev-container path for ephemeral testing against RustFS/Garage/R2. No production adoption of S3 in this migration. See decision #5 below and §"What is explicitly NOT in scope".

### Step 9: OpenCode-style agentic runtime (speculative) — `2026-05-21-step-9-opencode-runtime-evaluation-plan.md`

Re-evaluate with empirical evidence from Tier 2 whether the tool surface needs a full code-agent runtime swap.

---

## Key design decisions and their rationale

These are decisions that took conversation to reach; do not re-litigate without reading the rationale.

### 1. Single-user, single-developer assumption

Confirmed by Mathias. Drives: SQLite (not Postgres), no auth, no per-user prefixes, no general-purpose UI, breaking schema changes are acceptable with manual migration, terse IDE-shaped UX over hand-holding.

### 2. Excalidraw scene JSON lives inline as a DB column

Default until rows consistently exceed ~1 MB. Then revisit. Confirmed.

### 3. No Manim section chapter markers in the video player

Player stays plain `<video>`. Confirmed.

### 4. Scene = one Manim `Scene` subclass; Frame = one section inside `construct()`

Render unit is per-Scene, not per-Frame. Frame is structured prompt input + storyboard order, never an independent render target. Confirmed.

### 5. Local FS object store as the default, indefinitely

S3-compatible backend (RustFS / Garage / etc.) is engineered-for via the protocol but not adopted now. MinIO was excluded after Mathias noted the repo archive / commercialization move. RustFS chosen as the design-time S3-target reference; final backend choice deferred to Step 8.

### 6. The agent is a pure function (Option C)

Reached after rejecting Option A (browser sends inline payload to agent, agent + browser both talk to controller) and Option B (agent fetches from controller). Option C: **browser → controller; controller → agent; agent returns raw source.** The controller is the orchestrator; the agent is a stateless code generator.

Implications:
- Browser only knows the controller's API.
- Agent has no `controller_base_url`, no DB access, no ObjectStore access.
- Controller writes to ObjectStore (not the agent).
- Renames the user-visible generate entry point from `POST /api/v1/animation` (agent) to `POST /api/v1/scenes/{id}/generate` (controller).

### 7. Agent call runs inside the same Taskiq task as the render

Single task does `agent call → cache check → manim render → publish events`. One queue position covers the whole `(generate, render)` lifecycle. Splitting into two tasks is premature.

### 8. `POST /render` endpoint stays

Used by the deferred watcher flow and by tests that want to render a known source without LLM nondeterminism. Browser does not use it after Step 4.

### 9. `/generate` returns immediately with `{render_id, status}`

Browser long-polls the existing `/render-jobs/{id}` endpoint for the full lifecycle. No synchronous wait for the agent call.

### 10. Controller → Agent HTTP: httpx, 120s timeout, no retries on 4xx/5xx

Connection errors get one retry. LLM failures wrap up as `Render.status = failed` with the agent's error in `Render.error_message`.

### 11. Frame existence is Excalidraw-driven

`Frame` rows are derived from `excalidraw_scene_json` via diffing in `PATCH /scenes/{id}`. The exposed `POST /scenes/{id}/frames` and `DELETE /frames/{id}` endpoints exist for tests; they're documented as internal.

### 12. `react-router-dom` is the only new frontend dep

No Tanstack Query / SWR (custom hooks suffice at this scale). No state management library. No UI component library. Matches the existing minimal PoC styling.

### 13. Last-write-wins autosave

No optimistic concurrency control. Single user, single tab in the realistic case. Generate button is disabled while a save is in flight.

### 14. No migration-heavy rollout for any of this

There is no meaningful persisted user data to preserve at this stage; existing rows are smoke-test data only. If a schema change becomes awkward, wipe the local database/artifacts and recreate them from `0001_initial.py`. This is acceptable specifically because of the single-user / single-developer assumption and first-version ergonomics.

### 15. Module constants, not settings fields, for the Redis lock TTL

Per Mathias's preference. `cache_lock_ttl_ms`, `cache_lock_acquire_timeout_ms` are module-level constants in `locks.py`.

### 16. DQ1 resolved: agent stays pure-function with inline FileBundle (Step 7)

The agent does not gain tool access. Step 7's multi-file response is an inline `FileBundle` (list of `{path, content}` pairs). The controller writes them to ObjectStore. This preserves Option C. Re-evaluated only if Step 9 friction log shows it's untenable. Confirmed.

### 17. S3 serving strategy: proxy-bytes default (Step 8)

The controller always proxies artifact bytes (HTTP 200). No redirect to presigned URLs by default. A future opt-in `LAYERSENSE_S3_DIRECT_SERVE=true` flag can enable 302 redirects once SigV4 host-signing is verified for the chosen backend. This eliminates the redirect-vs-stream contract leak. Confirmed.

### 18. Step 9 evidence: friction log only, no quantitative metrics dependency

Step 9's go/no-go decision is based on a qualitative friction log maintained during Step 7 usage. The `metrics.json` sidecar and quantitative thresholds are dropped — they created a dependency on instrumentation that Step 7 doesn't ship. Friction log format and location: `docs/decisions/step-7-agent-friction-log.md`. Confirmed.

### 19. Export endpoint is GET, source-only (Step 6)

`GET /api/v1/projects/{id}/export` returns a zip of `.py` files + manifest + `manim.cfg`. No mp4 renders included. Streaming zip not needed at this scale. The GET method allows `<a href=...>` download links in the frontend. Confirmed.

---

## What to read next, by task

- **You are about to implement Step 1 (Redis lock):**
  read `docs/plans/2026-05-21-redis-render-lock-plan.md`.

- **You are about to implement Step 2 (persistence package):**
  read `docs/plans/2026-05-21-layersense-persistence-package-plan.md`.

- **You are about to implement Step 3 (ObjectStore + cache deletion):**
  read `docs/plans/2026-05-21-object-store-and-renders-repository-plan.md`.
  **Apply the amendment in this document's Step 3 section**: agent returns raw source bytes, controller writes to ObjectStore.

- **You are about to implement Step 4 (frontend + CRUD):**
  read `docs/plans/2026-05-21-frontend-revamp-and-project-scene-crud-plan.md`.
  **Apply the amendments in this document's Step 4 section**: controller orchestrates the agent call, browser never calls the agent, new `/scenes/{id}/generate` endpoint on the controller.

- **You are extending the architecture (Steps 5–9):**
  read the relevant plan file (`docs/plans/2026-05-21-step-{n}-*.md`). All nine plans exist. If you find drift between a plan file and this overview, **this overview wins** — apply the discrepancy as an in-place fix to the plan, log it under Provenance below.

- **You are unsure why a decision was made:**
  search this document's "Key design decisions" section first. If not found, the decision was made informally and should be added here.

---

## What is explicitly NOT in scope of this expansion

- Multi-user, auth, sharing, RBAC.
- Postgres or any DB other than SQLite.
- S3-compatible storage adoption (the abstraction is built; the backend is not).
- Manim section chapter markers in the video player.
- Drag-to-reorder UX for frames.
- A general-purpose UI with onboarding, empty-state hand-holding, etc.
- Multi-scene rendering ("render whole project at once").
- OpenCode integration (revisited in Step 9 only if Tier 2 hits real limits).
- Quantitative metrics sidecar (`metrics.json`) in the render pipeline.

---

## Provenance

This document captures the architecture conversation between Mathias and the Sisyphus agent on 2026-05-21. Key turning points:

1. **Three initiatives proposed** by Mathias: storage → S3, agent → OpenCode, frontend revamp.
2. **Coupling identified:** all three need a Project entity to anchor on. The persistence package becomes the keystone.
3. **Build order derived:** Redis lock → persistence → ObjectStore → frontend/CRUD → refinement → export → multi-file projects → S3 backend → OpenCode (speculative).
4. **Option C reached:** browser → controller → agent, with the agent as a pure function. Reversed an earlier draft where the agent owned ObjectStore writes.
5. **Step 3 and Step 4 plans amended** to reflect Option C. See amendment sections in those steps above.
6. **Normalization pass (2026-05-21, post-audit).** All nine plan files audited; per-plan drift surfaced in `docs/plans/2026-05-21-architecture-plans-audit.md`. This overview promoted to canonical source for: schema, key layout, S3 framing, Step 7 layout coexistence, status enum. Per-step plans amended to cite this file. Canonical source-key form chosen: `renders/{content_hash}/source.py` (free dedup, single prefix per render). Substantive BLOCKING fixes in individual plans (Step 3 contract, Step 4 race, Step 5 schema mismatch, Step 6 streaming, Step 7 split, Step 8 SigV4) deferred to focused per-step amendment passes.
7. **Step 1 + Step 3 + Step 4 substantive amendment pass (2026-05-21).** Step 1 plan extended with `RenewableLock` (heartbeat-renewed long-lived mutex) so Step 3 has the primitive ready. Step 3 plan amended: delivery split into PRs 3a (storage package) and 3b (controller wiring); `/render` HTTP-contract break made explicit (`scene_path` → `source_code` + `content_hash`, hard cutover, no dual-shape support); watcher hard-disabled on startup with Step 7 redesign pointer; `RenewableLock` wired around the worker entrypoint with module-constant config (`render_lock_ttl_ms=30_000`, `render_lock_heartbeat_interval_ms=10_000`, `render_lock_acquire_timeout_ms=5_000`); `_default` shim cleanup boundary declared at Step 4. Step 4 plan amended: `_default` cleanup is handled with reset-friendly first-version ergonomics rather than migration-sensitive choreography; `RenderJobSnapshot` hard schema cutover (`render_id` supersedes `job_id`, status enum unified to backend `Render.status`, `thumbnail_url` added); frame diff algorithm specified as hard-delete-on-disappear with duplicate-id `HTTP 422` collision rule and UX warning tooltip; `isSaving`-gated Generate clarified as race-prevention by construction (no `Render`-row scene-state snapshot fields); real frontend prop shapes reconciled (`Canvas` keeps imperative `forwardRef<CanvasHandle>` and gains additive `initialScene` + `onChange` props; `VideoPlayer` keeps URL-shaped props and adopts backend status enum; UX-shaped `VideoPlayerStatus` deleted). Outstanding BLOCKING items now limited to: Step 5 schema mismatch, Step 6 streaming scope, Step 7 split (DQ1 unresolved), Step 8 SigV4 host rewrite + redirect-vs-stream contract leak, Step 9 metrics-instrumentation dependency on Step 7.
8. **BLOCKING audit resolution pass (2026-05-22).** Four Oracle subagents audited all 9 plans against this overview. Design decisions 16–19 added to resolve open BLOCKINGs: DQ1 (FileBundle), S3 serving (proxy-bytes), Step 9 evidence (friction log only), export endpoint (GET + source-only). Schema amended: `UNIQUE(project_id, name)` on Scene, `Render.refinement_prompt` added. Hash terminology canonicalized (single `content_hash`). Cache-hit ordering clarified: `/generate` always calls agent first; cache hit is post-agent. Remaining per-plan amendments applied in same pass.

If you are extending this document, add a dated entry here.
