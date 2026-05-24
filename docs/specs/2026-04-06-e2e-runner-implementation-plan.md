# E2E Runner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `just test-e2e` as a single-command, assistant-friendly full-suite test entrypoint that launches a runner container, provisions the Dockerized app stack through the host Docker socket, runs non-`e2e` and `e2e` tests, and tears the stack down.

**Architecture:** A new outer `e2e-runner` container will mount the current workspace and host Docker socket, then use a dedicated inner compose file to launch frontend, agent, and controller in an isolated project namespace. The `e2e` suite will be made environment-driven so the same tests continue to work for `just e2e` against localhost and for `just test-e2e` against the runner-managed stack, including nested git worktrees.

**Tech Stack:** Docker Compose, shell scripting, just, pytest, uv, Bun, existing LayerSense Docker services

---

### Task 1: Add smoke helper coverage for worktrees and environment overrides

**Files:**
- Modify: `tests/test_dev_stack_config.py`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing tests**

Add focused tests that codify the new smoke-helper contract:

- smoke config can be overridden by environment variables
- repo-root discovery prefers `git rev-parse --show-toplevel`
- smoke helper behavior has a non-git fallback path

Use mocking for subprocess and environment access rather than invoking real git.

Example coverage shape:

```python
from pathlib import Path

from tests.smoke import test_dev_stack_smoke as smoke


def test_repo_root_uses_env_override(monkeypatch):
    monkeypatch.setenv("LAYERSENSE_SMOKE_REPO_ROOT", "/tmp/worktree")
    assert smoke._repo_root() == Path("/tmp/worktree")
```

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the helper behavior is not implemented yet.

**Step 3: Write minimal implementation target in mind**

Keep the tests narrow:

- no Docker setup here
- no end-to-end execution yet
- just prove the smoke helpers will behave correctly in normal checkouts and worktrees

**Step 4: Run test to verify failure shape is correct**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py::test_repo_root_uses_env_override -v`

Expected: FAIL with assertion or missing helper behavior, not import/setup breakage.

**Step 5: Commit**

Do not commit unless asked.

### Task 2: Refactor e2e tests to be environment-driven and worktree-safe

**Files:**
- Modify: `tests/e2e/test_dev_stack_e2e.py`
- Test: `tests/test_dev_stack_config.py`
- Test: `tests/e2e/test_dev_stack_e2e.py`

**Step 1: Implement the minimal helper changes**

Update the smoke module so:

- base URLs are read from environment variables with existing localhost defaults preserved
- `_repo_root()` uses:
  1. `LAYERSENSE_SMOKE_REPO_ROOT`
  2. `git rev-parse --show-toplevel`
  3. `Path(__file__).resolve().parents[2]`
- `_scenes_dir()` keeps honoring `LAYERSENSE_SMOKE_SCENES_DIR`, otherwise derives from `_repo_root()`

Keep the helper names unchanged.

**Step 2: Run the focused unit tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 3: Run the smoke file collection check**

Run: `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py --collect-only -q`

Expected: `e2e` tests collect successfully with no import errors.

**Step 4: Run the existing non-`e2e` suite that touches stack config**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py layersense_controller/tests/test_main.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 3: Add the outer e2e runner definition

**Files:**
- Create: `docker-compose.e2e.yml`
- Create: `Dockerfile.e2e`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing config tests**

Extend `tests/test_dev_stack_config.py` to assert:

- `docker-compose.e2e.yml` exists
- it defines an `e2e-runner` service
- it mounts the Docker socket
- it passes through the required provider env vars
- it mounts the active workspace into the runner

Also assert `Dockerfile.e2e` exists.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the e2e files do not exist yet.

**Step 3: Create the outer runner config**

Add `docker-compose.e2e.yml` with one service:

- `e2e-runner`
- build from `Dockerfile.e2e`
- mount `/var/run/docker.sock`
- mount the repo at a stable path like `/workspace`
- set `working_dir: /workspace`
- pass through `OPENAI_API_KEY`
- optionally pass through a workspace-root variable if helpful for the entrypoint

Create `Dockerfile.e2e` with the minimal toolchain needed:

- Docker CLI with Compose support
- Python 3.14 with `uv`
- Bun
- any small shell utilities needed for readiness polling and cleanup

Prefer a single runner image over multiple helper containers.

**Step 4: Run the config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS for the new file-existence and content assertions.

**Step 5: Commit**

Do not commit unless asked.

### Task 4: Add the inner compose stack definition for the app under test

**Files:**
- Create: `docker-compose.e2e.inner.yml`
- Modify: `tests/test_dev_stack_config.py`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing config tests**

Add assertions that the inner compose file:

- defines `frontend`, `agent`, and `controller`
- exposes the same service ports inside the compose project
- uses the repo-local build contexts already used by the existing stack
- wires the same artifact/code-sharing semantics needed by the `e2e` suite

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the inner compose file does not exist yet.

**Step 3: Create the inner compose file**

Model it closely on the current `docker-compose.yml`, but tune it for runner-managed execution:

- keep the same three services
- use the same build contexts and core environment variables
- preserve shared scene/artifact volumes needed by the stack
- prefer named volumes inside the Docker project over depending on host paths where possible
- keep service names stable so smoke environment variables can target them predictably from the runner

**Step 4: Run the config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 5: Add the runner orchestration script

**Files:**
- Create: `scripts/run_e2e.sh`
- Modify: `tests/test_dev_stack_config.py`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing config tests**

Add assertions that `scripts/run_e2e.sh` exists and includes the core orchestration behaviors:

- fail fast for missing provider env vars
- generate a unique compose project name
- run `docker compose -f docker-compose.e2e.inner.yml ... up --build -d`
- run `docker compose ... down -v` in cleanup
- invoke non-`e2e` tests, frontend tests, and `e2e` tests
- set smoke environment overrides for repo root and service base URLs

Keep these assertions text-based and focused on contract, not shell implementation details.

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the script does not exist yet.

**Step 3: Create the orchestration script**

Implement a small shell script that:

- uses `set -eu` or stricter shell safety compatible with the chosen shell
- validates API key env vars
- derives a stable workspace path inside the runner
- computes a unique project name, for example from timestamp and PID
- starts the inner stack
- polls readiness for frontend root and service health endpoints
- exports smoke env vars like:
  - `LAYERSENSE_SMOKE_FRONTEND_BASE`
  - `LAYERSENSE_SMOKE_AGENT_BASE`
  - `LAYERSENSE_SMOKE_CONTROLLER_BASE`
  - `LAYERSENSE_SMOKE_CONTROLLER_WS_URL`
  - `LAYERSENSE_SMOKE_REPO_ROOT`
- runs:
  - `uv run --all-packages pytest -m "not smoke"`
- `bun run --cwd layersense_frontend test`
- `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e`
- captures compose status/logs on failure
- always tears the stack down

Keep the script linear and minimal rather than abstracting into many shell helpers.

**Step 4: Run the config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 6: Wire `just test-e2e`

**Files:**
- Modify: `justfile`
- Modify: `tests/test_dev_stack_config.py`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing contract test**

Add a test asserting the root `justfile` contains a `test-e2e` recipe that invokes the outer runner compose file.

Example expectation shape:

```python
content = (ROOT / "justfile").read_text()
assert "test-e2e:" in content
assert "docker compose -f docker-compose.e2e.yml run --rm e2e-runner" in content
```

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the recipe is not present.

**Step 3: Add the recipe**

Add `test-e2e` to the root `justfile`.

Use a single non-interactive command that runs the outer runner and removes it afterward. Prefer `run --rm` over `up` for the outer runner because the command is batch-oriented.

**Step 4: Run the config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 7: Document the new workflow

**Files:**
- Modify: `README.md`
- Test: `tests/test_dev_stack_config.py`

**Step 1: Write the failing doc contract test**

Add assertions that `README.md` documents:

- `just e2e` remains for an already-running local stack
- `just test-e2e` provisions its own runner-managed stack
- the new command requires provider env vars
- the new command is intended for assistant-friendly reproducible execution

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: FAIL because the README does not mention `test-e2e` yet.

**Step 3: Update the README minimally**

Add a short section under local testing or Docker workflow.

Keep the documentation concise:

- when to use `just e2e`
- when to use `just test-e2e`
- required API key env vars
- note that the e2e runner uses the host Docker socket to provision its own stack

Do not add a long operational manual.

**Step 4: Run the config tests**

Run: `uv run --all-packages pytest tests/test_dev_stack_config.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit unless asked.

### Task 8: Verify compose and runner plumbing locally

**Files:**
- Verify only

**Step 1: Verify compose rendering**

Run: `docker compose -f docker-compose.e2e.yml config`

Expected: exit `0` with valid rendered outer compose config.

**Step 2: Verify inner compose rendering**

Run: `docker compose -f docker-compose.e2e.inner.yml config`

Expected: exit `0` with valid rendered inner compose config.

**Step 3: Verify runner image builds**

Run: `docker compose -f docker-compose.e2e.yml build e2e-runner`

Expected: exit `0`.

**Step 4: Verify smoke test collection in runner context assumptions**

Run: `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py --collect-only -q`

Expected: exit `0`.

**Step 5: Commit**

Do not commit unless asked.

### Task 9: Run the full repository verification plus new e2e path

**Files:**
- Verify only

**Step 1: Run formatting if needed**

Run: `just format`

Expected: exit `0` if any Python formatting adjustments were needed.

**Step 2: Run required lint verification**

Run: `just lint`

Expected: exit `0`.

**Step 3: Run required test verification**

Run: `just test`

Expected: exit `0`, and `e2e` tests are still excluded.

**Step 4: Run workspace verification**

Run: `just verify_workspace`

Expected: exit `0`.

**Step 5: Run the new end-to-end command**

Run: `just test-e2e`

Expected: exit `0`, with the runner provisioning the inner stack, executing the full suite including `e2e` tests, and tearing the stack down afterward.

**Step 6: Record any residual issues**

If provider nondeterminism or long-running render variability shows up, document it in the final summary and consider whether a follow-up design note is needed.

**Step 7: Commit**

Do not commit unless asked.
