# Desktop Workspace Layout Design

Date: 2026-03-16
Status: Approved
Scope: `layersense_frontend` desktop UX only

## Goal

Improve the frontend workspace layout so the Excalidraw canvas is clearly dominant, side margins are reduced, and prompt/render controls are always available in a fixed desktop inspector.

## Confirmed Decisions

1. Use a desktop-first, non-collapsible right inspector.
2. Defer mobile layout changes entirely.
3. Keep prompt and render output visible at the same time.
4. Keep existing interaction flow and backend integration unchanged.

## Chosen Approach

Adopt a full-width desktop workspace with a fixed right inspector.

- Main grid: `minmax(0, 1fr) 360px`
- Canvas as primary stage (left, dominant)
- Prompt and render output stacked in inspector (right)
- Minimal outer padding and reduced decorative visual weight

## Why This Approach

- Maximizes drawing area, which is the primary task surface.
- Preserves fast prompt iteration without hiding render feedback.
- Avoids mode switching and collapse/expand friction.
- Requires mostly CSS/layout refactoring, not architecture changes.

## Layout Specification

## 1) Shell and Header

- App shell uses full viewport width (`100vw`) instead of centered max-width layout.
- Outer spacing: compact desktop padding (`12px 16px` target range).
- Header remains visible but compact:
  - Smaller title/subtitle footprint than current version
  - Tight vertical spacing

## 2) Workspace Geometry

- Two-column desktop grid:
  - Left: fluid canvas column (`minmax(0, 1fr)`)
  - Right: fixed inspector (`~360px`, acceptable range `340-380px`)
- Inter-column gap around `12px`.
- Workspace height tracks viewport remaining space after header.

## 3) Canvas Stage

- Canvas panel fills left column height.
- Internal chrome is minimal.
- Canvas frame should scale with viewport and avoid arbitrary small max-height caps.
- Excalidraw remains fully interactive and sized to frame bounds.

## 4) Inspector

- Prompt card at top, render card beneath.
- Inspector stays visible on desktop and may scroll independently if needed.
- Generate button remains obvious and quickly reachable.
- Prompt remains editable during rendering; existing button disable logic remains as-is.

## Visual Direction

- Keep current visual language but reduce decorative dominance.
- Ensure neutral card surfaces and high legibility around canvas tools.
- Maintain existing generate CTA color semantics.

## Non-Goals

- No mobile responsiveness work in this change.
- No collapsible sidebar behavior.
- No websocket/connectivity behavior changes.
- No API/data flow/state-machine redesign.

## Implementation Boundaries

- Primary changes in `layersense_frontend/src/App.css`.
- Minimal markup adjustments in `layersense_frontend/src/App.tsx` only if required for layout semantics.
- No behavior changes in:
  - `layersense_frontend/src/api.ts`
  - `layersense_frontend/src/hooks/useRenderEvents.ts`
  - `layersense_frontend/src/components/Canvas.tsx`
  - `layersense_frontend/src/components/VideoPlayer.tsx`

## Acceptance Criteria

1. Side margins are visibly reduced versus current centered layout.
2. Canvas occupies clear majority of desktop viewport width and height.
3. Prompt and render output are both visible in a fixed right inspector.
4. Layout is stable at common desktop sizes (1440x900 and 1920x1080).
5. Existing frontend tests continue to pass.

## Verification Plan

1. Visual verification via Playwright screenshots before/after at desktop viewport(s).
2. Run frontend tests (`npm run test`).
3. Run frontend build (`npm run build`).
4. Keep repository-level checks (`just lint`, `just test`) green before completion.
