# Controller CLI Flags Design

## Summary

Replace the shared `RenderOptions` model with a controller-local `CLIFlags` request model carried in the `POST /render` JSON body. Keep background color out of controller inputs entirely; the generated scene source is now the source of truth for that behavior.

## Problem

`RenderOptions` currently implies a shared agent/controller rendering contract, but the only live field, `background_color`, does not map to a supported Manim CLI flag in the installed runtime. That makes the model misleading and non-functional.

The model also lives in `layersense_domain`, which incorrectly suggests it is a stable shared contract between services.

## Goals

- Remove the false shared contract around render-time options.
- Introduce a controller-owned JSON-body model for supported Manim CLI flags.
- Keep the `POST /render` request shape explicit and easy to validate with FastAPI.
- Preserve cache identity semantics by hashing normalized controller CLI inputs.
- Remove background color from controller request handling.

## Non-Goals

- Add UI for every Manim CLI flag.
- Support output-shape-changing flags such as `format`, `save_last_frame`, `transparent`, `save_sections`, or `write_all`.
- Keep backward compatibility for `render_options` in the controller API.

## Recommended Approach

Use a nested `cli_flags` object inside the existing `POST /render` JSON body.

Example request body:

```json
{
  "scene_path": "/layersense_artifacts/code/generated_123.py",
  "conversation_id": "123",
  "cli_flags": {
    "quality": "m",
    "renderer": "cairo"
  }
}
```

This is preferred over headers or query params because the values are job inputs, not transport metadata or read filters.

## Model Placement

`CLIFlags` should live inside `layersense_controller`, not `layersense_domain`.

Reasoning:

- The fields map directly to controller subprocess behavior.
- The agent should not suggest or own controller CLI behavior by default.
- Keeping the model local prevents the same false coupling that `RenderOptions` introduced.

`layersense_domain` remains useful for truly shared concepts, but controller-specific process flags are not one of them.

## Proposed Model

Initial allowlist:

- `quality`: `l | m | h | p | k`
- `resolution`: string matching `"W,H"`
- `frame_rate`: positive float
- `renderer`: `cairo | opengl`
- `from_animation_number`: string passthrough for Manim's accepted range syntax

Suggested shape:

```python
from typing import Literal

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated

Resolution = Annotated[str, StringConstraints(pattern=r"^\d+,\d+$")]


class CLIFlags(BaseModel):
    quality: Literal["l", "m", "h", "p", "k"] | None = None
    resolution: Resolution | None = None
    frame_rate: float | None = Field(default=None, gt=0)
    renderer: Literal["cairo", "opengl"] | None = None
    from_animation_number: str | None = None
```

## API Changes

### Agent

- Stop returning `render_options` from `POST /api/v1/animation`.
- Keep background-color handling inside generated scene code only.

### Frontend

- Remove `render_options` from `AnimationResponse`.
- Rename `RenderQueueRequest.render_options` to `cli_flags`.
- Default to an empty `cli_flags` object until UI controls exist.

### Controller

- Rename `RenderRequest.render_options` to `cli_flags`.
- Rename Taskiq payload plumbing and cache helpers accordingly.
- Translate only allowlisted `CLIFlags` fields into Manim subprocess args.
- Remove background-color-specific controller behavior.

## Data Flow

1. Agent generates scene code and persists any background config in the file itself.
2. Frontend queues `POST /render` with `scene_path`, `conversation_id`, and optional `cli_flags`.
3. Controller validates `cli_flags` via FastAPI/Pydantic.
4. Controller hashes scene content plus normalized `cli_flags` payload for cache identity.
5. Worker maps `cli_flags` to subprocess args and renders preview/final artifacts.

## Cache Identity

Cache hashing should continue to include the normalized controller request flags because those flags affect render output.

Normalization rule:

- use `model_dump(mode="json", exclude_none=True)` for `CLIFlags`

This avoids cache key churn from absent fields while still distinguishing materially different render requests.

## Testing

### Controller unit/integration

- Replace `RenderOptions` expectations with `CLIFlags` expectations.
- Assert supported fields map to the correct subprocess args.
- Assert unsupported legacy `render_options` contract is removed from tests.

### Agent tests

- Remove response assertions for `render_options`.
- Keep source-level background-color assertions.

### Frontend tests

- Update TypeScript request/response contracts to `cli_flags`.

### E2E

- Remove dependence on agent-returned render options.
- Queue renders with `cli_flags: {}` by default.
- Add at least one path that exercises a non-empty supported `cli_flags` payload once the frontend exposes or the test injects one.
- Keep background-color coverage focused on generated scene source, not controller request options.

## Docs Impact

Update:

- `README.md`
- any controller API docs or architecture notes referencing `render_options`

Key wording change:

- agent no longer "extracts allowlisted render options" for controller use
- frontend queues renders with optional controller `cli_flags`

## Risks

- Breaking API compatibility for any callers still posting `render_options`
- Partial migration if frontend/types/tests are not updated atomically
- Future temptation to move controller-only flags back into shared domain models

## Mitigations

- Make the rename atomic across backend, frontend, tests, and docs.
- Keep `CLIFlags` in `layersense_controller` to reinforce ownership boundaries.
- Restrict the initial allowlist to flags that do not alter artifact serving semantics.

## Implementation Outline

1. Remove `RenderOptions` from shared domain usage.
2. Add controller-local `CLIFlags` model and rename request/task plumbing.
3. Update subprocess arg construction to use allowlisted fields only.
4. Update frontend request/response types and API helpers.
5. Remove `render_options` from agent response models and tests.
6. Update e2e and repo docs.
