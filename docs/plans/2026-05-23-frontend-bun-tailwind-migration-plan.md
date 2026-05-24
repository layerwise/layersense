# Frontend Bun/Bunx + Tailwind Migration — Implementation Plan

**Status:** Implemented 2026-05-23.
**Purpose:** Establish the Bun/Tailwind frontend baseline required before executing `docs/plans/2026-05-21-frontend-revamp-and-project-scene-crud-plan.md`.
**Unblocks:** Frontend revamp work in Step 4 and follow-on frontend route/component work.

---

## Implemented baseline

- `layersense_frontend` is now Bun-managed with `packageManager: "bun@1.3.5"`.
- `layersense_frontend/package-lock.json` was removed.
- `layersense_frontend/bun.lock` is the frontend lockfile.
- Tailwind v4 is wired through `@tailwindcss/vite` in `layersense_frontend/vite.config.ts`.
- `layersense_frontend/src/index.css` is the Tailwind/global stylesheet entrypoint.
- `layersense_frontend/src/App.css` was removed; the current app shell uses Tailwind utilities in React components.
- Frontend Docker dev/build stages use `oven/bun:1.3.5-debian`; production still serves static assets through nginx.
- Root Just recipes and e2e runner scripts use Bun frontend commands.

---

## Files intentionally affected

### Frontend toolchain

- `layersense_frontend/package.json`
- `layersense_frontend/bun.lock`
- `layersense_frontend/vite.config.ts`
- `layersense_frontend/Dockerfile`

### Frontend styling

- `layersense_frontend/src/main.tsx`
- `layersense_frontend/src/index.css`
- `layersense_frontend/src/App.tsx`
- `layersense_frontend/src/components/Canvas.tsx`
- `layersense_frontend/src/components/VideoPlayer.tsx`
- `layersense_frontend/src/App.css` deleted

### Repo workflows

- `justfile`
- `scripts/run_e2e.sh`
- `Dockerfile.e2e`
- `docker-compose.yml`

### Docs/instructions

- `README.md`
- `AGENTS.md`
- active frontend/agent plan docs and historical implementation/spec docs with frontend package-manager command examples

---

## Bun command conventions

Use Bun’s supported cwd form:

```bash
bun install --cwd layersense_frontend --frozen-lockfile
bun run --cwd layersense_frontend test
bun run --cwd layersense_frontend build
bun run --cwd layersense_frontend dev -- --host 0.0.0.0 --port 3000
```

Do not use `bun --cwd layersense_frontend run ...`; Bun `1.3.5` treats that as invalid for package scripts.

---

## Verification targets

Minimum checks for future edits to this migration baseline:

1. `bun install --cwd layersense_frontend --frozen-lockfile`
2. `bun run --cwd layersense_frontend test`
3. `bun run --cwd layersense_frontend build`
4. `OPENAI_API_KEY="dummy-api-key" docker compose config`
5. `OPENAI_API_KEY="dummy-api-key" docker compose -f docker-compose.yml -f docker-compose.e2e.yml config`

For full-stack confidence, run `just test-e2e` when live/compose e2e verification is appropriate.

---

## Remaining risks

- Vite build still emits pre-existing large chunk warnings from Excalidraw/Mermaid-heavy bundles.
- Browser visual parity should be checked whenever the app shell layout changes, especially Excalidraw canvas fill behavior.
- The nginx prod stage still uses default nginx behavior; SPA refresh routing is unchanged from before this migration.
