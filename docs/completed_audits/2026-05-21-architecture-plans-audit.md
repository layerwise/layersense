# Adversarial Audit of LayerSense Architecture Plans

**Date:** 2026-05-21
**Auditor:** Sisyphus (synthesizing 8 parallel Oracle audits)
**Scope:** All 10 plans under `docs/plans/2026-05-21-*.md`
**Method:** 7 per-plan adversarial audits + 1 cross-plan consistency audit, all run in parallel by Oracle. Anchors (overview, persistence plan, Redis lock plan) read directly. Findings below are the synthesis.

---

## Executive verdict

The plan set is **architecturally coherent at the level of the overview document** but **operationally inconsistent across the individual plan files**. The overview describes Option C cleanly; many plan files were written before the Option C amendment landed and have not been updated. As a result, a future agent picking up any one plan in isolation will implement a contradictory version of the system.

**Two systemic problems dominate:**

1. **The overview's Step 3 / Step 4 amendments live only in the overview.** The plan files themselves still encode pre-amendment designs (browser→agent, agent writes ObjectStore, scene_source_key vs source_code). Any agent reading only the plan will get the wrong design.
2. **Multiple plans were drafted in parallel without a shared schema/key-layout canon.** Migration file numbers collide, ObjectStore key layouts disagree across three plans, the Render schema has three competing "initial" definitions.

**Recommendation: do not implement any plan beyond Step 1 (Redis lock) without a normalization pass first.** Step 1 is the only plan that survives audit largely intact.

---

## BLOCKING findings (must fix before implementation)

### Cross-plan: Option C is encoded in the overview but not in the plan files

The single most important finding. The overview (L261–264, L277–281) explicitly says Step 3 and Step 4 plans need amendments. The plan files were never updated.

- **Object-store plan L163–178, L364**: still shows browser→agent flow; browser still forwards source to `/render`. Contradicts overview L78–80 and its own §Scope at L20–22.
- **Object-store plan L274** (test text): claims "agent has pre-populated `scene_source_key`" — pre-amendment.
- **Persistence plan L267–268** (§Open Follow-Ups): still says "agent writes generated `.py` through the object store and records the key on the Render row" — pre-amendment.
- **Step 7 plan L170–178**: contradicts the overview's L291–293 ("Agent gains a constrained tool surface"). The plan recommends no tool surface and inline `FileBundle` instead, with DQ1 still unresolved.
- **Step 9 plan L216–219**: reverts Step 7's `FileBundle` agent response back to `{ scene_py_bytes, content_hash }`. Cross-plan contradiction.

**Fix:** mechanically apply the overview's amendments into every plan file. Add a "amended on date X" banner. Mark DQ1 in Step 7 as resolved one way or the other before implementation.

### Cross-plan: ObjectStore key layout has three incompatible definitions

- **Overview L152–159**: `scenes/{scene_id}/source/{content_hash}.py`
- **Object-store plan L101–106**: `renders/{content_hash}/source.py`
- **Step 7 plan L58–78**: `projects/{project_id}/scenes/{scene_id}.py` (mutable current source)
- **Step 5 plan L454**: even mis-cites the overview's own layout
- **Step 6 plan L204**: uses Step 3's layout (will break once Step 7 lands)

**Fix:** pick one layout in the overview. Update every plan to cite it verbatim. Step 7 needs an explicit migration section if it really does change the layout.

### Cross-plan: Render schema has three competing "initial" definitions

- **Overview L117–128**: includes `log_artifact_key`, `thumbnail_artifact_key`, status enum with `generating`.
- **Persistence plan L116–128**: omits `log_artifact_key`, omits `thumbnail_artifact_key`, status enum omits `generating`.
- **Step 3 plan L125–133** and **Step 4 plan L257–263**: add the missing fields as later migrations.

This means two "initial schemas" exist depending on which doc you read.

**Fix:** treat the overview as canon. Update the persistence-plan schema. Delete the later migration entries (they become no-ops).

### Cross-plan: Migration file numbers collide

All three of Step 5, Step 6, Step 7 propose `migrations/versions/0004_*.py`:
- Step 5 L176–182: `0004_add_render_refinement_prompt.py`
- Step 6 L241–244: `0004_add_render_manim_version.py`
- Step 7 L110–139, L746: `0004_add_components_and_bundle_manifest.py`

**Fix:** plans must use placeholder slugs (e.g., `00NN_add_refinement_prompt.py`) and let the implementing PR allocate the next available number, OR sequence them explicitly: Step 5 = 0004, Step 6 = 0005, Step 7 = 0006.

### Step 3: `/render` HTTP contract is self-contradictory

- Plan L20 and L46 claim visible behavior is unchanged.
- Plan L167, L182, L235 remove `scene_path`, require `source_code`, update frontend.
- Existing `router.py:28-31, 135-184` only accepts `scene_path`.

This is a breaking API migration disguised as internal substrate work. **Fix:** acknowledge the breaking change explicitly; spell out the migration window; update acceptance criteria to verify the new contract end-to-end.

### Step 3: `_default` Project shim is hand-waved on both ends

- Step 3 L141 creates shim scenes with empty `prompt` and `excalidraw_scene_json`.
- Step 4 L18, L287–310 says it deletes the shim but **doesn't specify whether existing `_default` rows are re-parented or wiped**.
- Step 2 repository contract doesn't guarantee idempotent upsert-by-slug, which the shim creation requires.

Single-user assumption permits wiping, but it must be explicit. **Fix:** Step 4 plan adds a data-migration section: "drop the `_default` project, cascade-delete all rows under it, accept artifact wipe."

### Step 3 + Step 7: Watcher lifecycle is incoherent

- Step 3 L234 says watcher is "left alone for now"; L304 requires no `scenes_dir` matches in source.
- Current `watcher.py:20-25, 39-42` hard-depends on `settings.scenes_dir` and posts `scene_path` to `/render`.
- Step 7 re-enables watcher "project-aware" but never specifies what it watches (host FS? ObjectStore polling?) or how it reconciles with ObjectStore as the source of truth.

**Fix:** Step 3 must explicitly disable the watcher (e.g., raise on startup) rather than "leave it alone." Step 7 must specify the watcher's new event source. Step 7 plan also lacks a concrete sync API for ObjectStore writes triggering watcher events.

### Step 3: render dedup lock is unsafe and under-specified

- Plan L211 says simultaneous identical renders may both proceed; L213 says "Recommended… Add it"; L278 makes lock dedup an integration requirement.
- Step 1's lock primitive defaults to **30s TTL** (sized for sub-second cache writes). Render preview+final can take **multiple minutes**.
- No specification of TTL override, lock renewal during long renders, or release-on-failure path.

**Fix:** explicit per-content-hash render lock with multi-minute TTL, heartbeat renewal, and guaranteed release on worker crash (Taskiq middleware or `finally` block). Document this in either Step 1 (extend the primitive) or Step 3 (extend the call site).

### Step 4: autosave/generate race is not actually closed

The plan claims "Generate button is disabled while a save is in flight" but:
- `POST /generate` (L124–126, L254–255) loads Scene+Frames in the Taskiq worker, **after the request returns**.
- Edits saved after click but before worker read can change render input.
- No scene revision/snapshot is captured.

**Fix:** snapshot scene state into the Render row at `/generate` time (e.g., `excalidraw_scene_json_snapshot`, `prompt_snapshot`, or a `scene_version` integer that the worker re-reads). Alternative: take an explicit Excalidraw snapshot client-side and send it inline with `/generate`.

### Step 4: render-job HTTP shape is incomplete

- Plan maps `render_id` onto `/render-jobs/{render_id}` but existing snapshots use `job_id`, `conversation_id`, URLs, and old statuses (`render_jobs.py:16-24, 52-80`).
- Browser artifact resolution at L101–103, L145 requires `content_hash`, but `POST /generate` returns no `content_hash` and existing `/render-jobs` snapshot has no `content_hash`.

**Fix:** explicit migration of `render_jobs.py` Redis snapshot schema; spell out new fields (`render_id`, `content_hash`, `scene_id`, `preview_artifact_key`, `final_artifact_key`).

### Step 4: Frame diff contract is underspecified and destructive

- L108–109 says insert/delete/preserve by Excalidraw frame id.
- No extraction algorithm specified, no duplicate-id behavior, no safeguard against deleting frames with non-empty `prompt_augmentation`.
- L401 admits potential silent data loss.

**Fix:** specify (a) Excalidraw frame extraction algorithm, (b) collision behavior (UNIQUE constraint guards this in DB but the diff still needs a rule), (c) require a non-destructive flag or undo journal for frames with content.

### Step 4: existing frontend assumptions are wrong

- Plan L215 says `Canvas` receives initial scene + `onChange`. Actual `Canvas.tsx:17-45` exposes only `getSceneSnapshot()` via ref, passes no `initialData`/`onChange` to Excalidraw.
- Plan L216 says `VideoPlayer` receives `content_hash`. Actual `VideoPlayer.tsx:10-15` receives concrete preview/final URLs plus status/error.

**Fix:** re-read the actual frontend code and rewrite the affected sections.

### Step 5: `refinement_prompt` is never stored before the worker reads it

- L127 creates the Render with `status`, `scene_id`, `parent_render_id`, `cli_flags_json` only.
- L176–180 has the worker reading `render.refinement_prompt`.
- L147 omits the field at creation.

**Fix:** add `refinement_prompt` to the create payload. Add a NOT NULL constraint or default.

### Step 5: Render rows created before required fields exist

- Step 2 schema (L120–124) defines `content_hash` and `scene_py_artifact_key` as `NOT NULL`.
- Step 5 (L127, L174–186) creates `status="generating"` rows **before** the agent returns source/hash.

**Fix:** either make those fields nullable until `final_ready` (overview already implies this) and update the persistence-plan schema, OR insert the Render row after the agent returns. The former is more honest about state machine reality.

### Step 5: cache semantics contradict refinement identity

- L83–87, L151–154, L373 explicitly **exclude `parent_render_id` from the cache key** and **test that identical refinement source cache-hits**.
- This means a refinement can serve a prior unrelated render's artifacts.

**Fix:** include `parent_render_id` (or its absence) in the effective hash. Update the test.

### Step 6: download HTTP method is inconsistent

- Endpoint is `POST /api/v1/projects/{project_id}/export` (L28, L55–67).
- Frontend uses `<a href=... download>` (L37, L284–290) which is `GET`.
- Acceptance criterion L449 only greps for the anchor.

**Fix:** make export `GET` (idempotent read), OR make the frontend `POST` and stream to a download via blob.

### Step 6: `include_renders=final` can select a render without a final mp4

- L225–229: "successful" includes both `preview_ready` and `final_ready`.
- L272–275: blindly reads `render.final_artifact_key`.

**Fix:** when `include_renders=final`, filter to `status='final_ready'` AND `final_artifact_key IS NOT NULL`.

### Step 6: streaming scope is contradictory

- L41 says streaming is out of scope.
- L35 says rendered exports (which can be 1–2GB) are in scope.
- L69 says rendered zips are streamed.
- L239 says streaming can be follow-up.
- L493–494 says streaming is in scope.

**Fix:** pick one. Either streaming is in scope and the implementation uses `StreamingResponse` + `zipstream`, or rendered exports are deferred.

### Step 7: `FileBundle` contract is impossible as written

- L253, L277 require response to contain exactly `scenes/{scene_id}.py`.
- L194–214 shows agent request with no `scene_id` or target path.

**Fix:** add `target_scene_path` to the agent request, OR make the agent free to pick its filename and have the controller rename on write.

### Step 7: cache key ignores components

- L74–76, L315–337: render output depends on imported components.
- L289–291: `effective_hash` is only `scene_content + cli_flags`.
- Result: component-only edits incorrectly reuse stale renders.

**Fix:** `effective_hash` must include the resolved transitive component-bundle hash.

### Step 7: cache-hit test contradicts orchestration

- L270–291: task calls the agent **before** computing `effective_hash`.
- L583: integration test expects a component cache hit where "agent is not called."

**Fix:** restructure orchestration to compute the cache key from (scene_excalidraw + components-bundle-hash + cli_flags) **before** the agent call. This also enables actual cache benefits.

### Step 8: presigned local-dev host rewrite breaks SigV4

- L208–216: rewrites `http://rustfs:9000` to `http://localhost:9000` and claims signatures cover "path and query, not the host."
- SigV4 presigned URLs **sign the `host` header**. The rewrite invalidates the signature.

**Fix:** use a shared hostname (Docker network alias + `/etc/hosts` entry), OR generate the presigned URL using the public-facing host name from request time.

### Step 8: backend choice leaks through HTTP contract

- L176–199, L476–483: local routes return 200 streaming bytes, S3 routes return 302 redirects.
- Tests explicitly assert 302.

**Fix:** either always return 302 (with local impl serving via a temporary signed-URL equivalent), or always proxy bytes. Pick one client-visible contract.

### Step 9: purity is redefined, not preserved

- Overview L69–80, L78–80: agent is a pure function, no durable-state awareness.
- Step 7 L168–177: rejects tool surface as Option C violation.
- Step 9 L134–140, L202–223: admits filesystem tools and temp project dirs but claims "purity survives if HTTP boundary unchanged."

The architectural break is real and must be acknowledged, not redefined away.

**Fix:** Step 9 must explicitly say "Option C is amended/superseded by this step" and propagate the implications.

---

## SHOULD-FIX findings (correctness issues that don't block, but reduce confidence)

### Schema and storage

- **Persistence plan L44, L196, L260**: claims `layersense_persistence` is imported by both agent and controller and assumes shared SQLite access. Overview L88 says controller only. Step 4 L391 forbids agent imports. **Fix:** drop agent dep.
- **Step 3 plan L39, L236 vs L335**: contradicts itself on whether agent mounts the storage volume.
- **Step 4 plan, multiple**: `thumbnail_artifact_key` timing is contradictory between "after preview" (L56) and "after final" (L139–143). Display path lacks an artifact route or DTO field.
- **Step 4 plan L92 + persistence L102–103**: `PATCH /scenes/{id}` accepts `order_index`, but `UNIQUE(project_id, order_index)` requires atomic bulk reorder. No bulk reorder endpoint specified.
- **Step 4 plan L251–254**: autosave sends full Excalidraw JSON every 800ms with no size limit, compression, or 413 behavior. Overview L313–315 says "revisit at >1MB" — needs enforcement.

### Caching, locks, config

- **Redis lock plan L114, L141–142**: proposes `cache_lock_ttl_ms` and `cache_lock_acquire_timeout_ms` as settings fields. Overview L239–241, L371–373 say module constants. (Already discussed; you already chose constants.)
- **Step 3 plan L208**: artifact routes use `content_hash` but Step 3 L189 introduces `effective_hash` that includes CLI flags. Mismatch causes wrong-or-missing artifact lookups for non-default flags.
- **Step 8 plan L91-92, L184-195, L328**: no `CacheControl` on S3 uploads; no response cache headers; 1h presigned TTL is the only knob — uncoordinated with video player session length.
- **Step 8 plan L89-99, L103-111**: `put_stream` may drop `ContentType` (only set on `put`). Breaks `head().content_type` and direct S3 video serving.

### Process / agent

- **Step 5 plan L75, L138–140, L170, L472**: "previous prompt recovery" is internally contradictory; reads from `scene_py_artifact_key` then admits no snapshot exists and falls back to current `Scene.prompt`.
- **Step 5 plan L303, L306, L374**: parent_render traversal not actually specified despite claiming arbitrary chains; tests only assert third → second.
- **Step 5 plan L118, L304–305, L476**: "previous render" resolved by latest-`created_at`, not `scene.current_render_id`. Will diverge once revert/history exists.
- **Step 6 plan L131–135**: `manim.cfg` includes `Exported: <timestamp>`, breaking deterministic export.
- **Step 6 plan L29-35**: zip omits Excalidraw JSON, prompt, frames, logs — all of which are DB-stored project state. Weakens "archive a snapshot."
- **Step 6 plan L412–414**: missing-artifact policy only covers source blobs; no rule for missing preview/final blobs.
- **Step 7 plan L255, L276–280, L534–535, L550**: path-traversal validation skips symlink/realpath/TOCTOU.
- **Step 7 plan L415, L236-257, L376-390**: component deletion is promised in UI but not modeled in `FileBundle` or watcher.
- **Step 7 plan L184-190, L596-600, L604-607**: test strategy underestimates cassette nondeterminism for multi-file outputs.

### Dependency drift

- **Step 6 L5**: claims deps on Steps 2, 3, 4. Omits Step 5 (overview L283-289 sequences Step 5 first).
- **Step 9 L61-65**: requires Step 7 metrics sidecars at `renders/{content_hash}/metrics.json`. Step 7 L438-517, L612-630 contain no metrics instrumentation. **Fix:** add metrics to Step 7 or to a Step 7.5 milestone.

### Scope drift

- **Step 5**: not really "Tier 1 refinement" — adds frames-aware prompt construction (L26-32, L281-295) that changes fresh-generation behavior and cassettes.
- **Step 6**: overview L287-289 calls this "cheap." Plan adds schema migration + worker changes + optional streaming + frontend state + ~910 LOC. Likely scope creep or overview underestimate.
- **Step 7**: 749 LOC plan covering schema, storage, agent contract, controller render path, watcher, frontend. **Oracle verdict:** split before implementation.
- **Step 8 vs overview L401-406**: overview says S3 adoption is out of scope; Step 8 implements it. Resolve by either (a) framing Step 8 as "abstraction-ready, default still local, opt-in dev container" or (b) updating the overview.

### Overview staleness

- **Overview L233, L393-394**: claims Steps 5-9 are "outlined only" / "no plan files exist yet." All five plans exist. Update the overview.

---

## NIT findings

- **Object-store plan AC L316**: criterion 13 verifies no external imports of `models`. That does not prove write ownership — direct SQL evades the check.
- **Step 5 plan L332, L427**: refers to `services/prompt_builder.py`. Actual instructions live inline in `layersense_agent/src/layersense_agent/agents/agent.py:11-139`.
- **Step 6 plan L162-167**: README example uses `manim scenes/001_intro.py Intro`. Manim class name is not in the manifest.
- **Step 7 plan L155-162, L739**: `python_package_name` is premature schema churn.
- **Step 8 plan L123-139**: `Protocol` "default implementation" claim is misleading — structural `Protocol` does not provide runtime defaults.
- **Step 9 plan L65-66**: metrics keyed by `content_hash` may collide across renders. Use `render_id`.

---

## What to do, in order

1. **Normalization PR (no implementation).** Update the overview to be canon for: schema (include `log_artifact_key`, `thumbnail_artifact_key`, full status enum), key layout (one definition), Option C amendments fully written into Step 3 and Step 4 plan files, plan-file existence acknowledged. Renumber Step 5/6/7 migrations sequentially. This PR touches only the `docs/plans/` files.
2. **Step 1 (Redis lock) ships as planned** with the module-constants amendment. This is the only plan that survives audit largely intact. Apply the per-content-hash render-lock TTL extension here so Step 3 can consume it.
3. **Step 2 (persistence) ships** with the schema normalized to overview, the agent dep dropped, and the §Open Follow-Ups bullet rewritten.
4. **Step 3 gets rewritten,** not edited. The cumulative drift (Option C, key layout, `/render` contract, watcher, dedup lock, `_default` shim) is too large for surgical fixes. The rewrite stays focused: ObjectStore + cache.py deletion + RendersRepository wiring, with a properly amended Option C flow.
5. **Step 4 gets a focused amendment pass:** Option C flow, race-condition fix (scene snapshot in Render row), render-job snapshot schema migration, frame diff algorithm, correct frontend characterization.
6. **Step 5 gets the BLOCKING fixes** (refinement_prompt creation, NOT NULL relaxation, cache-key includes parent_render_id, current_render_id used for previous-render lookup).
7. **Step 6 gets a scope decision** (in or out of streaming) and a GET vs POST decision, then the BLOCKING fixes.
8. **Step 7 gets split** into:
   - 7a: bundle/cache correctness (FileBundle contract, components in effective_hash, orchestration order)
   - 7b: watcher re-enablement (with concrete event source)
   - 7c: frontend
   Plus: explicit Option C amendment (this step changes the agent's interface) and metrics instrumentation if Step 9 will gate on it.
9. **Step 8 gets the BLOCKING fixes** (SigV4 host rewrite, contract leak) and a clear stance on overview L401-406.
10. **Step 9 stays speculative,** but rewrites the "purity preserved" framing into "Option C is amended here," and tightens decision triggers to deterministic AND-of-thresholds.

---

## What is healthy about the plan set

This audit is intentionally negative. For balance:

- The **overview document is excellent** as an anchor. It is internally consistent and clear on rationale.
- **Option C is the right decision** and was reached deliberately, with documented amendments.
- **Step 1 and Step 2 are clean** — both are small, focused, and largely audit-proof.
- The **build-order DAG is correct** — Steps 1 and 2 are genuinely parallel, downstream sequencing is sound.
- The **schema is well-designed** in the overview (with the noted normalization gaps).
- **Single-user / SQLite / no-S3 / local-FS-indefinite** decisions are correct and well-defended.

The problem is not the architecture. The problem is that **multiple plan files were written in parallel against an evolving overview, and the amendments never propagated.** A single normalization PR fixes most of this.
