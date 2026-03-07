# AI-augmented Visual Manim Animator with Distributed Manim Rendering Pipeline

This project provides an automated and scalable rendering pipeline for **Manim Community** animations to undergird an Excalidraw-powered frontend for intuitive,
visual animation design with a Manim backend.

In a typical video animation workflow, a digital artist will use UI-heavy tools like After Effects or Blender to create and render animations. However, these tools can be complex and require significant manual effort to iterate on designs, and they
do not afford the precise, mathematical control that Manim provides.

On the other hand, Manim allows for programmatic animation creation with fine-grained control, but it lacks a visual interface and can be slow to render, especially for complex scenes.

An AI-augmented visual animator can bridge this gap by providing a user-friendly interface for designing animations while leveraging Manim's powerful rendering capabilities. The system can automatically translate visual designs into Manim code, and then manage the rendering process efficiently.

The distributed Manim Rendering Pipeline removes the manual render loop (`edit → render → wait → tweak → repeat`) by introducing automatic file watching, task queuing, and parallelized rendering using containerized workers.

The system is designed for **fast iteration during development** and **scalable batch rendering** when needed.

---

# Overview

The architecture consists of the following components:

Developer edits scene
│
▼
File Watcher (watchdog)
│
▼
Render Controller API
│
▼
Task Queue (Redis)
│
▼
Render Workers (Docker + Manim)
│
▼
Artifacts Storage


This pipeline allows code changes to automatically trigger renders, which are executed asynchronously and in parallel.

---

# Goals

The system aims to:

- Automate rendering when scene code changes
- Parallelize rendering workloads
- Reduce developer wait time
- Provide reproducible rendering environments
- Enable scaling across multiple machines or GPUs
- Cache identical renders to avoid redundant work

---

# Core Components

## File Watcher

A local watcher monitors the animation repository for changes.

**Technology**

- `watchdog` (Python)

**Behavior**

- Detects file changes (`*.py`, `*.tex`, etc.)
- Sends a render request to the controller API

This removes the need to manually invoke the Manim CLI.

---

## Controller API

The controller coordinates rendering requests.

**Responsibilities**

- Receives render requests
- Computes a content hash of the scene
- Checks whether the scene was already rendered
- Enqueues new render tasks if needed

**Desired frameworks**

- FastAPI

---

## Task Queue

Rendering jobs are dispatched through a message queue.

**Technology**

- Redis (message broker)
- Celery or Taskiq (task execution)

This allows:

- asynchronous rendering
- parallel workers
- retry policies
- distributed scaling

---

## Render Workers

Workers are Docker containers that execute Manim renders.

Each task:

1. Creates an isolated working directory
2. Runs the Manim CLI
3. Captures logs and output
4. Stores artifacts

Workers can run in parallel across multiple CPU cores or machines.

**Key dependencies**

- Manim Community
- ffmpeg
- LaTeX
- Cairo / Pango

---

## Artifact Storage

Rendered videos and frames are stored for reuse.

Options include:

- Local filesystem
- NFS
- S3-compatible storage (MinIO / AWS S3)

Artifacts are keyed by a **content hash**, enabling caching.

---

# Render Caching

To prevent redundant rendering, a content hash is computed from:

- scene source code
- rendering arguments
- Manim version

If the same hash already exists in storage, rendering is skipped.

---

# Parallel Execution

Multiple render workers can run simultaneously.

Example:
