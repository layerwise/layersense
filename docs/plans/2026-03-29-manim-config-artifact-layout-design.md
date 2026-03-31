# Manim Config Artifact Layout Design

## Goal

Make Manim rendering deterministic and storage-oriented by replacing implicit output discovery with explicit config files, explicit output names, and artifact-rooted paths.

## Decisions

1. Use two committed Manim config defaults packaged inside `layersense_controller`: `manim-preview.cfg` and `manim-final.cfg`.
2. The controller passes `--config_file` and `--output_file` to every Manim render invocation.
3. Raw Manim outputs live under the existing `layersense_artifacts/scenes` root, not inside `layersense_controller`.
4. Raw output names follow the scene filename stem with `_preview` and `_final` suffixes.
5. The controller keeps the existing content-hash cache outputs, but derives them from deterministic raw artifact locations instead of searching for `GeneratedScene.mp4`.

## Why

The current renderer shells out to Manim using only quality flags, assumes the scene class name `GeneratedScene`, then tries to infer the real output location from process output or by scanning for `GeneratedScene.mp4`.

That is brittle for both local Docker use and any future storage-backed architecture.

Explicit config and output naming solve three problems at once:

- the render process has stable, reviewable filesystem semantics
- the controller no longer needs guesswork to locate outputs
- the raw artifact layout can later map cleanly to object storage concepts such as S3

## Storage Model

`layersense_artifacts` remains the durable artifact root.

Within that root:

- raw Manim-owned render outputs live in deterministic scene-name-based locations under `layersense_artifacts/scenes/<project-or-_root>/<preview|final>/`
- content-hash cache artifacts remain the controller-facing outputs exposed to the rest of the system

This preserves current cache semantics while making the lower-level render storage explicit and future-compatible.

## Manim Configs

Add packaged defaults under `layersense_controller/src/layersense_controller/resources/`:

- `manim-preview.cfg`
- `manim-final.cfg`

Each config explicitly defines output-related fields such as:

- `media_dir`
- `video_dir`
- `partial_movie_dir`
- `log_dir`
- any related temp/text/Tex directories needed for consistency

The configs should point into `layersense_artifacts/scenes`, matching both the mounted Docker layout and the local repo layout, while the controller resolves them from installed package resources rather than repo-root file paths.

## Render Invocation

The controller should invoke Manim like this conceptually:

```bash
manim render \
  --config_file <preview-or-final-cfg> \
  --output_file <project_or_root>/<preview_or_final>/<scene_stem_preview_or_final> \
  <scene_path> \
  GeneratedScene
```

Example:

- `layersense_scenes/project_a/generated_abc.py` preview raw output: `layersense_artifacts/scenes/project_a/preview/generated_abc_preview.mp4`
- `layersense_scenes/project_a/generated_abc.py` final raw output: `layersense_artifacts/scenes/project_a/final/generated_abc_final.mp4`
- `layersense_scenes/generated_root.py` preview raw output: `layersense_artifacts/scenes/_root/preview/generated_root_preview.mp4`

## Controller Cleanup

Replace stdout parsing and recursive media scanning with deterministic path resolution based on:

- selected config
- scene parent path, defaulting to `_root` when there is no parent
- scene stem
- explicit nested output file name

The controller should copy from that deterministic raw path into the existing cache targets:

- `<hash>_preview.mp4`
- `<hash>_final.mp4`

## Non-Goals

- Do not change the requirement that generated scene classes are named `GeneratedScene`.
- Do not redesign the content-hash artifact cache API in this pass.
- Do not introduce actual S3/object storage support in this pass.

## Testing Strategy

- Add failing tests first for deterministic Manim command construction and output-path resolution.
- Verify preview and final renders each use the correct config file and output name.
- Verify copying from the deterministic raw artifact path into the existing cache target.
- Update docs if active render-flow descriptions become stale.
