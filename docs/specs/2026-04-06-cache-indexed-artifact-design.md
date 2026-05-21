# Cache-Indexed Artifact Design

**Date:** 2026-04-06  
**Status:** Approved

---

## Context

`layersense_controller` currently renders canonical Manim outputs under `layersense_artifacts/scenes/...`, then copies those outputs to flat cache files at the artifact root:

- `layersense_artifacts/<content_hash>_preview.mp4`
- `layersense_artifacts/<content_hash>_final.mp4`

This makes the cache mechanically effective, but it introduces an impure storage model:

- the same rendered media exists twice
- the top-level artifact directory mixes cache identity with stored media
- browser-facing URLs are coupled to duplicate cache files instead of canonical artifacts

The design goal is to preserve content-addressed cache hits while making the filesystem and URL model cleaner.

## Goals

- Keep a single canonical copy of each rendered media file.
- Keep the filesystem clean and storage-oriented.
- Allow cache lookup through metadata rather than duplicate files.
- Preserve content-hash-based cache hits.
- Expose stable HTTP routes that do not leak storage layout assumptions.

## Non-Goals

- Introducing a database-backed artifact store.
- Preserving the existing flat `<content_hash>_{preview|final}.mp4` files.
- Building historical version browsing for a scene UUID.
- Solving multi-tenant or remote deployment storage concerns.

## Decision

Adopt an index-backed cache with canonical artifacts.

The storage and lookup responsibilities are split cleanly:

- `layersense_artifacts/code/...` stores generated Manim source files.
- `layersense_artifacts/scenes/...` stores canonical rendered media files.
- `layersense_artifacts/cache/index.json` stores cache metadata that maps content hashes and scene UUIDs to canonical artifact paths.

The content hash remains the cache key, but it no longer becomes the artifact filename.

## Storage Model

Canonical files remain where Manim already writes them:

- `layersense_artifacts/scenes/<project>/preview/...`
- `layersense_artifacts/scenes/<project>/final/...`

New cache metadata lives under:

- `layersense_artifacts/cache/index.json`

No duplicate media files are written at the artifact root.

## Cache Index Shape

The index should support two lookups:

1. `content_hash -> artifact record`
2. `scene_uuid -> latest content_hash`

One acceptable v1 shape is:

```json
{
  "by_hash": {
    "<content_hash>": {
      "scene_path": "code/generated_<scene_uuid>.py",
      "scene_uuid": "<scene_uuid>",
      "preview": "scenes/_root/preview/generated_<scene_uuid>_preview.mp4",
      "final": "scenes/_root/final/generated_<scene_uuid>_final.mp4",
      "updated_at": "2026-04-06T12:34:56Z",
      "artifact_version": 1
    }
  },
  "by_scene_uuid": {
    "<scene_uuid>": "<content_hash>"
  }
}
```

### Field Notes

- `scene_path`: relative path under the configured scenes/code directory for debugging and traceability.
- `scene_uuid`: conversation/scene identifier already used by the frontend.
- `preview` and `final`: relative canonical artifact paths under `layersense_artifacts`.
- `updated_at`: timestamp for debugging and stale-index inspection.
- `artifact_version`: reserved for future index migrations.

## Controller Flow

### Render Request

On `POST /render`:

1. Validate the incoming scene path is a file inside the configured `scenes_dir`.
2. Compute the scene file's content hash.
3. Parse the scene UUID from the scene filename or relative path convention.
4. Look up the content hash in the cache index.
5. Verify any indexed `preview` and `final` paths still exist and remain inside `layersense_artifacts/scenes`.
6. If both artifacts exist, broadcast a cache-hit event and return `{"status": "cached"}`.
7. If either artifact is missing, render only the missing artifact(s).
8. After each successful render, atomically update the index.
9. Update `by_scene_uuid[scene_uuid] = content_hash` so semantic scene routes resolve to the latest rendered version.

### Render Pipeline

The existing preview-then-final pipeline remains intact:

- preview render writes the canonical preview file under `scenes/...`
- final render writes the canonical final file under `scenes/...`
- each successful step updates the metadata index

The render functions should stop copying media to hash-named root files.

## URL Surface

Two route families should remain available.

### 1. Content-addressed routes

- `GET /artifacts/by-hash/<content_hash>/preview`
- `GET /artifacts/by-hash/<content_hash>/final`

These routes resolve through the cache index, then serve the canonical media file.

### 2. Scene-oriented routes

- `GET /artifacts/scenes/<scene_uuid>`
- `GET /artifacts/scenes/<scene_uuid>?preview=true`

Behavior:

- default route returns the final render if available, else the preview render
- `?preview=true` prefers the preview render
- scene UUID routes resolve via `scene_uuid -> latest content_hash -> artifact record`

This lets the frontend think in conversation/scene UUID terms while keeping storage layout private.

## Why This Is More Elegant

- Canonical media exists in exactly one place.
- The artifact directory reflects domain concepts instead of cache internals.
- Cache identity is expressed as metadata, not duplicate files.
- URLs become semantic API routes instead of direct file-path conventions.
- Storage layout can change later without forcing frontend changes.

## Consistency Rules

- The index is metadata, not proof of artifact existence.
- Every lookup must verify the referenced file exists.
- Every indexed path must be relative and must resolve inside `layersense_artifacts/scenes`.
- If a referenced file is missing, clear that field in memory and treat the request as a partial cache miss.
- Index writes must be atomic: write a temporary file, then rename into place.
- Partial states are valid: preview may exist while final does not.

## Failure Handling

- If the preview artifact exists but final is missing, reuse preview and render only final.
- If the final artifact exists but preview is missing, reuse final and render only preview.
- If an index entry references an invalid path, reject it and rerender as needed.
- If the scene UUID has no latest hash, return `404` from the scene route.
- If a `by_hash` entry exists but the requested preview/final field is absent or stale, return `404` from the content-addressed route.

## Testing Impact

### Unit tests

- cache index load/save behavior
- content-hash and scene-UUID lookup behavior
- missing-file and stale-index recovery
- path validation for indexed artifact paths
- atomic persistence behavior

### Router tests

- cache-hit behavior through the index
- by-hash preview/final routes
- scene UUID route default and `?preview=true` behavior
- partial cache hits and rerender paths

### Render tests

- render functions return canonical `scenes/...` paths
- no duplicate hash-named files are created

### Smoke tests

- stop expecting top-level hash-named mp4 files
- verify semantic routes under `/artifacts/scenes/<scene_uuid>`
- verify by-hash routes resolve canonical artifacts

## Migration Notes

This change can be done in-place without a separate data migration for current local development:

- old hash-named root files can simply stop being written
- new renders populate the index naturally
- existing stale flat files may remain on disk until manually cleaned, but they should no longer be read by the controller

If desired, a follow-up cleanup command can delete orphaned top-level cache files.

## Open Implementation Detail

The controller needs a small, explicit helper for deriving `scene_uuid` from a scene path.

For the current repo conventions, the simplest rule is:

- if the filename matches `generated_<uuid>.py`, use `<uuid>`
- otherwise, use the filename stem as the scene UUID fallback

That keeps smoke tests and manually-authored scenes working without introducing new request fields.
