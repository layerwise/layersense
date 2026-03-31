# Manim Config Artifact Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make controller-driven Manim renders deterministic by introducing explicit preview/final config files, explicit output names, and artifact-rooted raw output paths.

**Architecture:** The controller continues to expose the same cache-facing preview/final artifacts, but the underlying Manim invocation becomes explicit: config file + nested output name + deterministic artifact location. Raw Manim outputs are stored under `layersense_artifacts/scenes/<project-or-_root>/<preview|final>/`, allowing future migration toward object-storage-style artifact handling without changing the cache API now.

**Tech Stack:** Python, FastAPI, pytest, Manim, Docker-mounted filesystem artifacts

---

### Task 1: Lock in deterministic render invocation with tests

**Files:**
- Modify: `layersense_controller/tests/test_render.py`
- Modify: `layersense_controller/src/layersense_controller/render.py`

**Step 1: Write the failing test**

- Add tests proving preview render uses `--config_file manim-preview.cfg` and `--output_file <project-or-_root>/preview/<scene_stem>_preview`.
- Add tests proving final render uses `--config_file manim-final.cfg` and `--output_file <project-or-_root>/final/<scene_stem>_final`.
- Add a test proving raw output path resolution is deterministic and no longer depends on stdout parsing or `GeneratedScene.mp4` scanning.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`

Expected: FAIL because the current renderer only passes quality flags and still parses/discovers output paths heuristically.

**Step 3: Write minimal implementation**

- Replace quality-flag-only invocation with explicit `--config_file` and `--output_file` arguments.
- Resolve the expected raw output path directly from `layersense_artifacts/scenes`, preserving the scene parent path or `_root` when there is no parent.
- Remove the old stdout parsing and recursive media scan logic if no longer needed.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`

Expected: PASS

### Task 2: Add committed Manim config files for preview and final renders

**Files:**
- Create: `manim-preview.cfg`
- Create: `manim-final.cfg`
- Modify: `layersense_controller/tests/test_render.py`

**Step 1: Write the failing test**

- Add tests proving the renderer points at the committed preview/final config files and that those configs align with `layersense_artifacts/scenes` as the artifact-rooted media base.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`

Expected: FAIL because the config files do not exist yet and the renderer cannot reference them.

**Step 3: Write minimal implementation**

- Create the two config files using the exported `manim.cfg` format as reference.
- Set explicit output-related directories under `layersense_artifacts/scenes` for both preview and final render paths.
- Keep the two configs as similar as possible, differing only where preview/final settings genuinely differ.

**Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`

Expected: PASS

### Task 3: Preserve cache behavior and document the new artifact semantics

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `layersense_controller/tests/test_render.py`

**Step 1: Write or extend failing test if needed**

- Add or extend a test proving raw Manim output is copied into the existing `<hash>_preview.mp4` and `<hash>_final.mp4` cache targets.

**Step 2: Run focused tests**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py layersense_controller/tests/test_router.py -q`

Expected: PASS

**Step 3: Update docs**

- Clarify that raw Manim outputs live under `layersense_artifacts/scenes/<project-or-_root>/<preview|final>/...`.
- Clarify that controller-served preview/final artifacts still use the existing cache-facing names.

**Step 4: Run repo verification**

Run: `just lint`

Run: `just test`

Expected: PASS
