# Frontend Docker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the frontend container setup into a clean multi-stage Docker build that supports both dev and production targets without runtime package installation.

**Architecture:** Replace the current single-stage frontend Dockerfile with a multi-stage Dockerfile built around a shared dependency-install stage, plus dedicated `dev`, `build`, and `prod` stages. Update compose to select the `dev` target for local development and document the new container model.

**Tech Stack:** Docker, Docker Compose, Node.js, npm, Vite, nginx, Vitest

---

### Task 1: Add contract tests for the new frontend Docker shape

**Files:**
- Modify: `tests/test_dev_stack_config.py`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing tests**

Add focused assertions that describe the intended frontend Docker model:

- `layersense_frontend/Dockerfile` contains multiple stages
- it uses `npm ci`, not runtime `npm install`
- it defines `dev`, `build`, and `prod` stages
- the final production stage is based on `nginx:alpine`
- the Dockerfile no longer has `CMD ["sh", "-c", "npm install ..."]`

Also assert that `docker-compose.yml` builds the frontend service with the `dev` target.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the current frontend Dockerfile is still single-stage and the compose file does not select a target.

**Step 3: Verify failure shape**

Confirm failures point to the frontend Dockerfile and compose assumptions, not unrelated config issues.

**Step 4: Commit**

Do not commit unless asked.

### Task 2: Implement the multi-stage frontend Dockerfile

**Files:**
- Modify: `layersense_frontend/Dockerfile`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Replace the Dockerfile minimally**

Implement the stage layout:

- `deps` stage
  - copy `package.json` and `package-lock.json`
  - run `npm ci`
- `dev` stage
  - inherit from `deps`
  - copy source tree
  - run Vite dev server on `0.0.0.0:3000`
- `build` stage
  - inherit from `deps`
  - copy source tree
  - run `npm run build`
- `prod` stage
  - use `nginx:alpine`
  - copy built assets from the `build` stage

Do not add extra tooling or optimization layers beyond what this change needs.

**Step 2: Run config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: the new Dockerfile-related assertions pass, while compose-target assertions may still fail until the next task.

**Step 3: Inspect the Dockerfile for runtime install regressions**

Ensure there is no `npm install` in `CMD` or `ENTRYPOINT`.

**Step 4: Commit**

Do not commit unless asked.

### Task 3: Update dev compose to use the `dev` target cleanly

**Files:**
- Modify: `docker-compose.yml`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Update the frontend service build config**

Change the frontend service so it builds with `target: dev`.

Keep the current bind mount and `node_modules` volume shape unless a small correction is required for the new model.

The service should still support local Vite development on port `3000`.

**Step 2: Run config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS for the frontend Docker/compose contract tests.

**Step 3: Render compose config**

Run: `docker compose -f docker-compose.yml config`

Expected: exit `0` and rendered frontend build config includes the `dev` target.

**Step 4: Commit**

Do not commit unless asked.

### Task 4: Document the frontend container model

**Files:**
- Modify: `README.md`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Add a failing documentation test if needed**

Extend existing README assertions so they require a brief note that the frontend Docker setup now uses a multi-stage build with a dev target for local compose.

Keep the assertion narrow and text-based.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL if the README does not yet mention the new frontend container model.

**Step 3: Update the README minimally**

Document:

- local Docker dev stack uses the frontend `dev` target
- the frontend Dockerfile now has separate dev and production-style targets
- runtime package installation is no longer part of the frontend container startup path

Keep this concise.

**Step 4: Run config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 5: Verify the frontend Docker targets

**Files:**
- Verify only

**Step 1: Build the frontend dev target**

Run: `docker compose -f docker-compose.yml build frontend`

Expected: exit `0`.

**Step 2: Build the production target directly**

Run: `docker build --target prod -f layersense_frontend/Dockerfile layersense_frontend`

Expected: exit `0`.

**Step 3: Run frontend tests**

Run: `npm --prefix layersense_frontend test`

Expected: exit `0`.

**Step 4: Verify no smoke regressions at collection level**

Run: `uv run --all-packages pytest tests/smoke/test_dev_stack_smoke.py --collect-only -q`

Expected: exit `0`.

**Step 5: Commit**

Do not commit unless asked.

### Task 6: Run repository verification

**Files:**
- Verify only

**Step 1: Run formatting if needed**

Run: `just format`

Expected: exit `0` if formatting updates were needed.

**Step 2: Run lint**

Run: `just lint`

Expected: exit `0`.

**Step 3: Run tests**

Run: `just test`

Expected: exit `0`.

**Step 4: Run workspace verification**

Run: `just verify_workspace`

Expected: exit `0`.

**Step 5: Record residual frontend Docker concerns**

If the new Docker model still leaves e2e-specific frontend mount issues, note them explicitly as a separate follow-up instead of folding them into this change.

**Step 6: Commit**

Do not commit unless asked.
