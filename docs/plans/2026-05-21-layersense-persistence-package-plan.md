# LayerSense Persistence Package — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md` (canonical for schema and architecture).
**Author:** Sisyphus (OpenCode session, 2026-05-21, Planning architecture and future directions for repo)
**Scope:** Step 2 of the multi-step architecture revamp covering object storage, agent evolution, and frontend revamp.

## Session Note

This plan was produced during an architecture-planning conversation with the developer (sole user). The conversation covered three coupled initiatives:

1. Promoting the on-disk artifact filesystem to an S3-compatible service.
2. Evolving the `openai-agents` workflow toward a repo-aware, OpenCode-style agentic assistant.
3. Revamping the frontend from PoC tiles into a Project → Scene → Frame navigation model.

Key conclusions reached before this plan:

- **All three initiatives share one keystone: a durable Project/Scene/Frame/Render data model.** This plan delivers exactly that and nothing more.
- **Single-user (developer-only) for the next 12+ months.** SQLite with WAL is the right durable store; no Postgres, no auth, no RBAC.
- **MinIO is no longer the default S3 candidate** (upstream archived for commercialization). The chosen approach is a pluggable `ObjectStore` abstraction with `LocalFSObjectStore` as the production default; an `S3ObjectStore` impl (against RustFS / Garage / R2 / etc.) is a Step 8 follow-up, not a near-term commitment.
- **Excalidraw scene JSON is stored inline** as a JSON column (no object-store offload until measured pain).
- **Manim sections / chapter markers in the player are explicitly out of scope.** Frames map to ordered storyboard beats inside one Manim `Scene` class with sequential `play()` calls.
- **No general-purpose UI affordances.** The product is an IDE-shaped tool for one developer producing Manim YouTube videos. Schema and API decisions reflect that.

This plan is the sole deliverable to land before any of the downstream steps (frontend revamp, agent Tier 1/2, RustFS integration, render-lock migration to Redis) become unblockable.

## Build Order Context

The full agreed sequence after this conversation:

| # | Step | Status |
|---|---|---|
| 1 | Redis `SETNX` render-lock — replace `index.json` file-lock | Independent; can run in parallel with this plan. |
| 2 | **`layersense_persistence` package: SQLite + Project/Scene/Frame/Render schema, migrations, repository pattern** | **This plan.** |
| 3 | `ObjectStore` interface + `LocalFSObjectStore`. Move `.mp4` and generated `.py` access behind it. Retire `cache/index.json`. | Depends on (2). |
| 4 | Frontend revamp: project list → scene list → 3-pane scene editor; persistence-backed. | Depends on (2)+(3). |
| 5 | Frames as ordered prompt-augmentation beats. Agent Tier 1 (multi-turn refinement via persisted `conversation_id`). | Depends on (2)+(4). |
| 6 | Project export (zip of project dir from object store + DB-rendered manifest). | Depends on (2)+(3). |
| 7 | Agent Tier 2: project workspace tool surface (`read_file`, `write_file`, `list_dir`, `run_render`), components library convention. | Depends on (2)–(5). |
| 8 | `S3ObjectStore` impl + integration test against ephemeral RustFS container. **Default stays local.** | Depends on (3). |
| 9 | (Far future, only with empirical evidence) OpenCode integration replacing Tier 2 tool layer. | Re-evaluate after (7). |

## Scope

A new uv workspace member that owns the durable schema and exposes typed repositories. **Imported by `layersense_controller` only** (per Option C, the agent has no DB access — see overview "Three rules"). Cross-service DTOs (Pydantic) live in `layersense_persistence.schemas` and are imported by `layersense_controller` for HTTP body shapes; the agent uses its own request/response models unaware of persistence.

**Out of scope here:** API changes in agent/controller, frontend work, object store abstraction, render-lock migration. Each of those is a follow-up plan that depends on this one landing.

## Package Layout

```text
layersense_persistence/
  pyproject.toml
  src/layersense_persistence/
    __init__.py              # public exports
    config.py                # DB_PATH env, single Settings model
    database.py              # engine factory, session ctx manager
    models.py                # SQLAlchemy ORM: Project, Scene, Frame, Render
    schemas.py               # Pydantic DTOs for cross-service boundaries
    repositories/
      __init__.py
      projects.py
      scenes.py
      frames.py
      renders.py
    migrations/              # Alembic
      env.py
      versions/
        0001_initial.py
  tests/
    unit/
      test_models.py
      test_repositories_projects.py
      test_repositories_scenes.py
      test_repositories_frames.py
      test_repositories_renders.py
    integration/
      test_migrations_roundtrip.py
      test_concurrent_writes_wal.py
```

## Schema (Alembic `0001_initial`)

```sql
-- Project
id                          TEXT PRIMARY KEY            -- uuid4
name                        TEXT NOT NULL
slug                        TEXT NOT NULL UNIQUE        -- url-safe, derived from name on create
created_at                  TEXT NOT NULL               -- ISO8601 UTC
updated_at                  TEXT NOT NULL
default_render_config_json  TEXT NOT NULL DEFAULT '{}'

-- Scene
id                       TEXT PRIMARY KEY
project_id               TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE
name                     TEXT NOT NULL
order_index              INTEGER NOT NULL
prompt                   TEXT NOT NULL DEFAULT ''
excalidraw_scene_json    TEXT NOT NULL DEFAULT '{}'   -- inline JSON, per decision
current_render_id        TEXT REFERENCES render(id) ON DELETE SET NULL
thumbnail_artifact_key   TEXT                          -- set by worker after preview render
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
UNIQUE (project_id, order_index)
UNIQUE (project_id, name)

-- Frame  (storyboard beat inside a Scene; ordered prompt-augmentation unit)
id                       TEXT PRIMARY KEY
scene_id                 TEXT NOT NULL REFERENCES scene(id) ON DELETE CASCADE
order_index              INTEGER NOT NULL
excalidraw_frame_id      TEXT NOT NULL       -- the in-Excalidraw frame element id
prompt_augmentation      TEXT NOT NULL DEFAULT ''
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL
UNIQUE (scene_id, order_index)
UNIQUE (scene_id, excalidraw_frame_id)

-- Render
id                       TEXT PRIMARY KEY
scene_id                 TEXT NOT NULL REFERENCES scene(id) ON DELETE CASCADE
parent_render_id         TEXT REFERENCES render(id) ON DELETE SET NULL
content_hash             TEXT NOT NULL                       -- canonical hash of (scene_py + cli_flags)
status                   TEXT NOT NULL                       -- generating | queued | preview_ready | final_ready | failed
scene_py_artifact_key    TEXT                                -- nullable while status=generating; set on agent response
preview_artifact_key     TEXT                                -- nullable until preview_ready
final_artifact_key       TEXT                                -- nullable until final_ready
log_artifact_key         TEXT                                -- captured Manim stdout/stderr; set at final_ready or failed
cli_flags_json           TEXT NOT NULL DEFAULT '{}'
conversation_id          TEXT                                -- agent conversation that produced this
error_message            TEXT
created_at               TEXT NOT NULL
updated_at               TEXT NOT NULL

CREATE INDEX ix_render_scene_id_created_at ON render(scene_id, created_at DESC);
CREATE INDEX ix_render_content_hash ON render(content_hash);
```

### Schema Rationale

- **TEXT uuids, not autoincrement int.** Cross-service references survive DB rebuilds; safe for export/import.
- **`current_render_id` is denormalized** (could be derived from latest `render` row). Worth it: avoids subquery on every scene fetch in the navigation UI.
- **`scene_py_artifact_key` on Render, not Scene.** The generated `.py` is a render-time artifact, immutable, content-addressed; multiple renders of the same scene can have different generated code. Nullable to admit `status="generating"` (Render row exists, agent hasn't returned yet); set as soon as the agent response is persisted.
- **`log_artifact_key` on Render.** Captures Manim stdout/stderr. Set when the worker finishes (success or failure). `cache.py` had no equivalent and that hurt debugging.
- **`scene.thumbnail_artifact_key`.** Set by the worker after preview render. Powers `SceneCard` thumbnails in the project detail view (Step 4).
- **`status` as string enum, not lookup table.** Single-user, low cardinality, evolves with code; no value in normalizing.
- **Timestamps as ISO8601 TEXT, not Julian.** Human-readable in `sqlite3` CLI, sortable lexicographically, no timezone surprises.
- **No soft delete.** Cascade on project/scene delete. Single user, can recover from object store + git if needed.
- **No `cache_index` table.** Render rows already index by `content_hash`. The old `index.json` is obsoleted by `SELECT * FROM render WHERE content_hash = ?` (consumed in Step 3).

## Configuration

`config.py`:

```python
class PersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAYERSENSE_")
    db_path: Path = Path("./layersense_artifacts/db/layersense.sqlite")
    sqlite_echo: bool = False
```

`database.py`:

- `create_engine(...)` with `connect_args={"check_same_thread": False}`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `PRAGMA synchronous=NORMAL`.
- `@contextmanager get_session()` yielding a SQLAlchemy `Session` with explicit `commit`/`rollback`.
- `init_db()` for first-run schema bootstrap when migrations directory is unavailable (tests).

## Repository Pattern

Each repo is a thin class taking a `Session` in its constructor. No global state, no service locator. Example shape:

```python
class ScenesRepository:
    def __init__(self, session: Session) -> None: ...

    def create(self, *, project_id: str, name: str, order_index: int | None = None) -> Scene: ...
    def get(self, scene_id: str) -> Scene | None: ...
    def list_by_project(self, project_id: str) -> list[Scene]: ...
    def update(
        self,
        scene_id: str,
        *,
        prompt: str | None = None,
        excalidraw_scene_json: str | None = None,
        name: str | None = None,
    ) -> Scene: ...
    def reorder(self, project_id: str, ordered_ids: list[str]) -> None: ...
    def set_current_render(self, scene_id: str, render_id: str) -> Scene: ...
    def delete(self, scene_id: str) -> None: ...
```

Same shape for `ProjectsRepository`, `FramesRepository`, `RendersRepository`. Repositories return ORM models for in-process callers; cross-service boundaries use `schemas.py` Pydantic DTOs.

## Pydantic DTOs (`schemas.py`)

`ProjectRead`, `SceneRead`, `SceneWithFramesRead`, `FrameRead`, `RenderRead`, plus `*Create` / `*Update` variants. These are what `layersense_agent` and `layersense_controller` import. They never import ORM models directly.

## Workspace Integration

- Root `pyproject.toml` — add `layersense_persistence` to `[tool.uv.workspace] members`.
- `layersense_persistence/pyproject.toml` deps: `sqlalchemy>=2.0`, `alembic`, `pydantic>=2`, `pydantic-settings`. No `fastapi`, `taskiq`, or `httpx` — keep boundary-pure.
- `layersense_controller` adds `layersense-persistence` as a workspace dep. **`layersense_agent` does not depend on this package** (Option C: agent is a pure function with no DB awareness).

## Justfile Additions

```text
db_migrate:
    uv run --package layersense-persistence alembic upgrade head

db_revision message:
    uv run --package layersense-persistence alembic revision --autogenerate -m "{{message}}"

db_reset:
    rm -f ./layersense_artifacts/db/layersense.sqlite
    just db_migrate
```

`just setup` gains a `db_migrate` step at the end.

## Test Plan

Following `.agents/skills/write-python-tests/SKILL.md`.

**unit** (`tests/unit/`):

- ORM constraint tests: unique `(project_id, order_index)`, cascade deletes, FK enforcement (verify `PRAGMA foreign_keys=ON` is actually applied).
- Repository CRUD happy paths against an in-memory SQLite.
- DTO ↔ ORM round-trip.
- Slug derivation edge cases (collisions, unicode, length cap).
- `reorder` correctness with concurrent indices.

**integration** (`tests/integration/`):

- `test_migrations_roundtrip.py`: fresh file SQLite, run `alembic upgrade head` → schema matches `models.metadata`. Then `downgrade base` → empty.
- `test_concurrent_writes_wal.py`: two threads with separate connections writing to disjoint tables; both succeed under WAL. Darwin/linux only.

**No e2e tests in this step.** Live-stack changes come in the follow-up plans that consume this package.

## Acceptance Criteria

A reviewer can verify each of these directly:

1. `just setup && just db_migrate` produces `./layersense_artifacts/db/layersense.sqlite` with the schema above; `sqlite3 ... ".schema"` matches `models.py`.
2. `uv run --package layersense-persistence pytest -m unit` passes; `-m integration` passes.
3. Coverage for `layersense_persistence/src/**` is ≥ 95% from unit + integration combined. Repositories are the bulk of the lines and they are trivially testable.
4. `layersense_controller` imports `layersense_persistence.schemas` only (no ORM leakage). `layersense_agent` does **not** import `layersense_persistence` at all (Option C). Both verified by an AST/grep test in `tests/test_python_test_taxonomy.py` style: assert no `from layersense_persistence.models import` outside the persistence package, and no `import layersense_persistence` anywhere under `layersense_agent/src/`.
5. `just lint` passes.
6. Existing `just test_python` still passes — no behavioral change to agent or controller in this step. The package is added but not yet wired into request paths.
7. README "Repo Shape" updated to list the new workspace member; `docs/ROADMAP.md` gets a one-line entry under near-term focus.

## Out of Scope (Explicitly)

- Does not migrate the existing `cache/index.json`. That file keeps working until Step 3 wires `RendersRepository` into the controller.
- Does not change any HTTP route. Agent and controller behavior is byte-identical after this step.
- Does not introduce the `ObjectStore` abstraction. That is Step 3.
- Does not change the file-lock / Redis-lock situation. That is Step 1, which can run in parallel with this work since they touch disjoint modules.

## Estimated Shape

Single focused PR. ~600–900 LOC across `layersense_persistence/src/**` and ~400–600 LOC of tests. One Alembic migration. Two README/ROADMAP doc touches. Zero behavior change in existing services.

## Assumptions

1. Alembic is acceptable (no hand-rolled migration runner requested).
2. `./layersense_artifacts/db/` as the SQLite location is fine. It sits alongside `cache/`, `code/`, `scenes/` — all under the existing host-mount, which means existing `docker-compose.yml` volume mounts already cover it.
3. Only `layersense_controller` imports this package directly. `layersense_agent` stays a pure function and is unaware of the DB (Option C). Single-user, single-host: SQLite file with WAL written by the controller only; no DB-as-a-service needed.
4. SQLAlchemy 2.0 typed ORM style is acceptable — modern, matches the "type everything" repo norm.

→ Correct any of these before implementation begins.

## Open Follow-Ups After This Lands

- Step 1 plan: Redis `SETNX` render-lock to retire the file-lock contention bug documented in `README.md` L197.
- Step 3 plan: `ObjectStore` interface + `LocalFSObjectStore`; controller switches from `cache/index.json` to `RendersRepository`. **Per Option C, the controller (not the agent) writes generated `.py` bytes through the object store and records the key on the Render row.** The agent returns raw source bytes from `POST /api/v1/animation`; it never touches the object store.
- Step 4 plan: Frontend revamp (project navigation, scene editor, persistence-backed). Browser stops calling the agent directly; controller orchestrates the agent call server-side.

These three plans should be authored after this package is merged and exercised in at least one consuming service path.
