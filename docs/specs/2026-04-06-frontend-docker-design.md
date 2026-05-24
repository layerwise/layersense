# Frontend Docker Design

## Goal

Refactor the frontend container setup into a proper multi-stage Docker build that cleanly supports both local development and production-style serving, without runtime `bun install` behavior and without mixing build-time and runtime concerns.

## Decision

Adopt a multi-stage Dockerfile with a shared dependency-install layer and separate downstream stages for:

- development (`dev`)
- production asset build (`build`)
- production asset serving (`prod`)

Compose will choose the appropriate target for each workflow instead of relying on one container image to behave differently at runtime.

## Why This Approach

### Chosen Approach: Multi-Stage Frontend Dockerfile

- Install dependencies once in a shared base stage using the lockfile.
- Reuse that layer for both local dev and production build stages.
- Run the Vite dev server only in the `dev` stage.
- Build static assets in the `build` stage.
- Serve static assets from a small dedicated runtime image in the `prod` stage.

This separates responsibilities cleanly and removes the current anti-patterns:

- `bun install` during image build and again at runtime
- one image trying to be both dev server and production runtime
- bind mounts masking the intended dependency layout without a clear model

### Rejected Alternative: Production-Only Dockerfile With Dev Compose Hacks

- This would keep production clean.
- It pushes too much frontend build logic out of the Dockerfile and into compose.
- It is less self-contained and weaker as a long-term repo pattern.

### Rejected Alternative: Conditional Single-Stage Runtime Logic

- This preserves the current mixed-responsibility structure.
- It makes behavior implicit and harder to reason about.
- It does not solve the root issue of build-time versus runtime responsibilities.

## Architecture

### Stage Layout

Proposed Dockerfile stages:

1. `deps`
   - base image: oven/bun
   - copy `package.json` and `bun.lock`
   - run `bun install --frozen-lockfile`

2. `dev`
   - inherit from `deps`
   - copy the frontend source tree
   - expose port `3000`
   - run `bun run dev --host 0.0.0.0 --port 3000`

3. `build`
   - inherit from `deps`
   - copy the frontend source tree
   - run `bun run build`

4. `prod`
   - use a small runtime image such as `nginx:alpine`
   - copy built assets from the `build` stage
   - serve the static site

## Dependency Strategy

Use `bun install --frozen-lockfile`, not `bun install`, in the Docker build.

Reasons:

- lockfile-respecting and deterministic
- better suited to container builds
- avoids drifting dependency trees between local runs and images

The container should never perform package installation in `CMD` or `ENTRYPOINT`.

## Dev Compose Model

The local dev stack should use the `dev` target.

Recommended compose behavior for the frontend service:

- build with `target: dev`
- bind mount the source tree into `/app`
- use a named volume for `/app/node_modules` (Bun-managed)
- start Vite directly with no runtime install step

Important nuance:

- a bind mount over `/app` hides files that were copied into the image
- the named `node_modules` volume should therefore remain mounted at `/app/node_modules` even when using Bun.
- the service should rely on the dependency installation that occurred during image build, not on reinstalling packages when the container starts

If the current compose pattern does not correctly preserve that dependency state, it should be adjusted as part of implementation.

## Production Model

The production-style image should use the `prod` target and serve built artifacts from `nginx:alpine`.

Reasons:

- static files do not need a Node runtime server
- smaller and clearer runtime image
- standard deployment shape

This does not imply the repo is production-ready overall. It just means the frontend image has a sane production form.

## Expected Compose Responsibilities

Compose should decide which Docker target to build and run.

Examples:

- local dev stack: `target: dev`
- future production-like stack or CI check: `target: prod` or `target: build`

The Dockerfile should not contain runtime conditionals to switch between these modes.

## Impact On E2E Work

This cleanup is intentionally broader than the current e2e failure, but it should help it indirectly.

Most importantly, it should remove:

- runtime `bun install`
- dependency state that varies based on container boot timing

It may not fully solve the e2e frontend issue by itself if the e2e overlay still needs different mount behavior, but it gives the repo a cleaner and more predictable frontend container baseline.

## Files To Modify

Expected changes:

- `layersense_frontend/Dockerfile`
- `docker-compose.yml`
- `docker-compose.e2e.yml` only if needed later, but not as the primary target of this change
- `README.md`
- frontend-related config tests if appropriate

Potential additions:

- `.dockerignore` for the frontend if missing and useful
- optional nginx config only if needed for static serving behavior

## Testing Strategy

Implementation should verify:

- frontend unit tests still pass
- the frontend dev image builds successfully
- the dev stack still serves the app on `localhost:3000`
- the production target builds successfully
- no runtime `bun install` remains in the frontend container path

## Risks

- bind mounts and named volumes can still be subtle in the dev target if not wired carefully
- Vite or optional native dependencies may require ensuring the lockfile-resolved platform packages are installed correctly in the image
- adding a production stage may require a tiny nginx config if SPA fallback behavior matters later

## Success Criteria

- The frontend Dockerfile cleanly supports both development and production-style usage.
- Dependency installation happens during image build, not at runtime.
- Local development still works with Vite live reload.
- The repo has a sane production-style frontend image shape available for future use.
