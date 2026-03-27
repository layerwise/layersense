# LayerSense Architecture Design

**Date:** 2026-03-07  
**Status:** Approved

---

## Vision

LayerSense bridges the visual creativity of Excalidraw with the precise, mathematical control of Manim Community — mediated by AI.

The primary user is a developer/researcher who wants to iterate quickly on mathematical or visual animations without writing Manim boilerplate from scratch.

---

## User Journey

1. User draws shapes in the Excalidraw canvas and types a prompt describing the desired animation.
2. Clicks "Generate" → the AI translates the drawing + prompt into a Manim Python scene file written to disk.
3. User reviews and edits the generated file in their local IDE.
4. On every save, the file-watcher triggers an automatic render.
5. The browser shows a low-quality preview as soon as it is ready, then updates with the final HD video.

---

## System Architecture

```
Browser (React + Excalidraw, port 3000)
  │  POST /api/v1/animation {excalidraw_json, prompt}
  ▼
layersense_agent (FastAPI, port 8000)
  │  AI Agent (OpenAI Agents SDK, gpt-4o-mini)
  │  → Manim Python code
  │  → written to layersense_scenes/generated_<id>.py
  │  returns {conversation_id, scene_path}
  │
  ▼ (filesystem event)
File Watcher (watchdog, co-located with controller)
  │  detects create/modify on layersense_scenes/*.py
  │  POST /render {scene_path}
  ▼
layersense_controller (FastAPI, port 8001)
  │  hash(file content) → check layersense_artifacts/
  │  cache hit:  broadcast artifact URL via WebSocket
  │  cache miss: BackgroundTask
  │    1. manim render -ql → store preview → broadcast preview_ready
  │    2. manim render -qh → store final  → broadcast render_ready
  │
  ├── GET /ws          WebSocket endpoint for browser
  └── GET /artifacts/  Serve rendered video files
  │
  ▼
layersense_artifacts/ (local filesystem, hash-keyed)
```

Key insight: the file-watcher is the single render trigger for both AI-generated writes
and user IDE saves. Both paths are identical from the controller's perspective.

---

## Components

### `layersense_frontend/` (React + Vite, TypeScript)

- Embeds `@excalidraw/excalidraw` React component
- Text prompt textarea + "Generate" button
- On generate: `POST layersense_agent /api/v1/animation`
- Opens WebSocket to `layersense_controller /ws`
- Video player: updates first with low-quality preview, then HD
- No in-browser code editor — generated file is edited in the user's local IDE

### `layersense_agent/` (FastAPI, port 8000)

Endpoints:
- `POST /api/v1/animation` — takes `{prompt: str, json_data: str}`
  1. Validate payload as `ExcalidrawScene` (Pydantic model already exists)
  2. Run AI agent via OpenAI Agents SDK → Manim Python code string
  3. Write `layersense_scenes/generated_<conversation_id>.py`
  4. Return `{conversation_id: str, scene_path: str}`
- `GET /health`
- `GET /info`

AI agent uses few-shot prompting with an Excalidraw → Manim example already in place.

### `layersense_controller/` (FastAPI, port 8001)

Endpoints:
- `POST /render {scene_path: str}` — triggered by file-watcher
  1. Read file, compute SHA-256 hash
  2. Check `layersense_artifacts/{hash}_preview.mp4` and `{hash}_final.mp4`
  3. Cache hit: push `{type: "artifact_ready", preview_url, final_url}` via WebSocket
  4. Cache miss: launch `BackgroundTask`
     - Pass 1: `manim render -ql {scene_path} {SceneName}` → store `{hash}_preview.mp4`
     - Broadcast `{type: "preview_ready", url: ...}`
     - Pass 2: `manim render -qh {scene_path} {SceneName}` → store `{hash}_final.mp4`
     - Broadcast `{type: "render_ready", url: ...}`
- `GET /ws` — WebSocket for browser
- `GET /artifacts/{filename}` — serve rendered videos as static files
- `GET /health`

The controller container includes Manim Community, ffmpeg, LaTeX, Cairo/Pango.

### File Watcher (co-located with `layersense_controller/`)

- Python process using `watchdog`
- Watches `layersense_scenes/*.py` for `created` and `modified` events
- On event: `POST http://localhost:8001/render {scene_path}`
- Started alongside the controller (e.g., as a background thread or separate entrypoint)

### `layersense_scenes/` (shared volume)

- Source of truth for Manim scene files
- Written by the agent, edited by the user's IDE, read by the controller
- Mounted as a shared Docker volume

### `layersense_artifacts/` (shared volume)

- Rendered video files, keyed by content hash
- Written by the controller, served by the controller, read by the browser via HTTP

---

## Docker Compose

```yaml
services:
  layersense_frontend:   # React + Vite, port 3000
  layersense_agent:      # FastAPI, port 8000
  layersense_controller: # FastAPI + Manim + watchdog, port 8001

volumes:
  layersense_scenes:     # shared: agent writes, controller reads
  layersense_artifacts:  # shared: controller writes + serves
```

Redis and Celery are intentionally excluded. `FastAPI BackgroundTasks` is sufficient for
a single local developer and avoids operational overhead.

---

## Open Questions / Future Work

- **Scene class name extraction**: The controller needs to know which Manim `Scene` class
  to render from the generated `.py` file. Options: parse the AST, use a naming convention
  (e.g., always `GeneratedScene`), or have the agent output it explicitly.

- **Multi-turn conversations**: The `conversation_id` is generated but not yet used for
  conversation history. Multi-turn iteration ("make the circle red instead") is deferred.

- **Error handling**: What does the browser see if the AI produces invalid Manim code?
  The controller should broadcast a `render_failed` event with stderr.

- **WebSocket fanout**: For simplicity, a single WebSocket connection per session is assumed.
  If multiple tabs are open, each should receive its own events (keyed by `conversation_id`).

- **Scaling**: The current implementation path favors a simpler local-first stack. A queued/distributed render architecture remains a future option if the project later needs multi-user or remote GPU rendering.
