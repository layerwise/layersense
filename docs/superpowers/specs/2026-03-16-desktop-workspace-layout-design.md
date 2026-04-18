# Desktop Workspace Layout Design

Date: 2026-03-16
Status: Partially superseded by implementation
Scope: `layersense_frontend` desktop UX only

## Why This Document Still Exists

This document captures the original rationale for making the canvas the dominant workspace surface and moving prompt/render controls into a desktop inspector.

Some implementation details in the shipped frontend now differ from the original design:

- the inspector is now collapsible
- responsive behavior was added
- header compaction evolved beyond the first draft

Use this file as historical design context, not as a source of truth for current UI behavior.

## Still-Relevant Decisions

- Canvas should remain the primary visual focus.
- Desktop layout should minimize wasted outer margins.
- Prompt and render output should remain close to the canvas workflow.
- Backend integration and render-state behavior should remain unchanged during layout-only work.

## Current Source of Truth

For the current state of the frontend milestone, read:

- `docs/2026-03-22-stock-excalidraw-milestone-result.md`
- `docs/plans/2026-03-22-stock-excalidraw-milestone-result.md`
- `docs/plans/2026-03-16-frontend-stock-excalidraw-integration-plan.md`
- `layersense_frontend/src/App.tsx`
- `layersense_frontend/src/App.css`
