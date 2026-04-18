# E2E Runner Design

## Goal

Add a new `just test-e2e` entrypoint that lets coding assistants run the full test suite, including smoke tests, through a single reproducible containerized runner that manages the application stack lifecycle itself.

## Decision

Use a dedicated `e2e-runner` container that talks to the host Docker daemon through the Docker socket instead of implementing a fully nested Docker-in-Docker daemon.

This is intentionally the simpler option. It gives assistants a hermetic command surface and a reproducible runner environment without the operational complexity of true DinD.

## Why This Approach

### Chosen Approach: Host-Socket Runner

- `just test-e2e` starts one outer runner container.
- The runner has the repo mounted and the host Docker socket mounted.
- Inside the runner, a small entrypoint script uses `docker compose` to build and run a dedicated inner application stack for frontend, agent, and controller.
- The runner waits for readiness, executes the full test suite, captures logs, tears the stack down, and returns the combined test exit code.

### Rejected Alternative: True DinD

- A full Docker-in-Docker daemon inside the runner would provide stronger isolation.
- The gains are small for this repo because the desired outcome is a single assistant-friendly entrypoint, not multi-tenant container isolation.
- True DinD adds privileged daemon startup, more networking complexity, slower startup, and more debugging surface.

### Rejected Alternative: Host-Side Wrapper Only

- A plain host-side script around `docker compose` would be the smallest implementation.
- It does not solve the assistant ergonomics problem as well because the runner environment would still be host-defined instead of container-defined.

## Scope

- Add `just test-e2e` as a new command.
- Keep `just smoke` unchanged as the existing host-driven workflow.
- Use real model providers inside the e2e path.
- Pass required API keys through from the caller environment into the runner and inner stack.
- Run the non-smoke Python tests, frontend tests, and smoke tests from one orchestrated flow.

## Non-Goals

- Do not replace `just test`.
- Do not remove or redesign the current local developer stack.
- Do not introduce provider stubs or fake agent behavior for the e2e path.
- Do not implement true DinD unless the simpler host-socket runner proves insufficient.

## Architecture

### Outer Layer

`just test-e2e` launches an outer compose service named `e2e-runner`.

The outer runner image contains:

- Docker CLI with Compose support
- `uv`
- Python test dependencies
- Node and npm for frontend tests, or access to them through a prebuilt runner image
- a small orchestration entrypoint script

The outer runner mounts:

- the current repo checkout or worktree
- the host Docker socket

### Inner Layer

The runner uses a dedicated compose file to launch the application-under-test stack against the host daemon.

That inner stack contains:

- `frontend`
- `agent`
- `controller`

The runner assigns a unique compose project name per invocation so concurrent runs do not collide.

## Execution Flow

`just test-e2e` performs the following steps through the runner:

1. Validate required environment variables for real model providers are present.
2. Start the `e2e-runner` container.
3. Inside the runner, invoke `docker compose -f docker-compose.e2e.inner.yml -p <unique-project> up --build -d`.
4. Wait for frontend, agent, and controller readiness.
5. Run the default Python test suite excluding smoke.
6. Run frontend tests.
7. Run the smoke suite against the runner-managed stack.
8. Collect nested stack logs on failure and optionally on success.
9. Tear down the nested stack with volumes.
10. Exit with the combined test result.

Smoke tests should run last because they are the slowest and depend on a healthy inner stack.

## Smoke-Test Configuration Changes

The current smoke suite assumes:

- `localhost:3000`
- `localhost:8000`
- `localhost:8001`
- repo-root artifact layout inferred from git common-dir behavior

That is too brittle for worktrees and for the runner-managed environment.

### Required Change

Make the smoke suite environment-driven while preserving current defaults.

Base URLs should continue to default to the existing localhost values, but allow overrides through environment variables set by the runner.

### `_repo_root()` Robustification

Replace the current `git rev-parse --git-common-dir` logic with this order:

1. Honor `LAYERSENSE_SMOKE_REPO_ROOT` if set.
2. Otherwise use `git rev-parse --show-toplevel`.
3. If git discovery fails, fall back to `Path(__file__).resolve().parents[2]`.

This fixes nested git worktree resolution because `--show-toplevel` returns the actual worktree root instead of the shared repository root.

### `_scenes_dir()` Behavior

Keep `_scenes_dir()` derived from `_repo_root()` unless `LAYERSENSE_SMOKE_SCENES_DIR` is explicitly set.

This preserves `just smoke` behavior while allowing the e2e runner to inject deterministic mounted paths.

## Worktree Compatibility

The host-socket runner should work with repo checkouts and nested git worktrees as long as the runner mounts the active workspace path and explicitly sets:

- `LAYERSENSE_SMOKE_REPO_ROOT`
- optionally `LAYERSENSE_SMOKE_SCENES_DIR` when a more explicit mount path is useful

This prevents incorrect artifact-path resolution caused by shared `.git` common-dir discovery in worktree setups.

## Runner Responsibilities

The runner entrypoint script should:

- fail fast when required API keys are absent
- generate a unique inner compose project name
- launch the inner stack with `up --build -d`
- poll service readiness with clear timeout errors
- run tests in a deterministic order
- preserve the original failing exit code
- collect `docker compose ps` and `docker compose logs` on failure
- always execute `down -v` in a `trap`/cleanup path

## Logging And Failure Handling

If the inner stack fails to build or start:

- fail with an explicit runner-level error
- print nested compose status and logs

If readiness checks fail:

- report which service failed
- print nested compose status and logs

If a test command fails:

- stop the pipeline
- preserve that exit code
- still dump nested logs and tear the stack down

If teardown fails:

- report teardown failure separately
- do not mask the original test failure

## Files To Add Or Modify

Expected additions:

- `docker-compose.e2e.yml` for the outer runner
- `docker-compose.e2e.inner.yml` for the inner stack under test
- `Dockerfile.e2e` or similar for the runner image
- a runner entrypoint script under a scripts directory

Expected modifications:

- `justfile`
- `tests/smoke/test_dev_stack_smoke.py`
- `README.md`
- any test configuration files needed to support the new command cleanly

## Testing Strategy

Verification should prove both old and new workflows remain valid:

- `just smoke` still works against an already-running host stack
- `just test` still excludes smoke
- `just test-e2e` provisions the stack, runs all tests, and tears it down
- smoke tests work correctly from nested worktrees

## Risks

- Real provider-backed e2e runs will remain partially nondeterministic due to upstream API behavior.
- Sharing the host Docker socket means the approach is not true isolation and still depends on a healthy local Docker daemon.
- Runner image composition may grow if Python and Node tooling are both installed directly into the same image.

## Success Criteria

- Coding assistants can run `just test-e2e` without inspecting or managing an already-running stack.
- The command fully owns stack startup, readiness checks, test execution, log collection, and teardown.
- The smoke suite works both in normal checkouts and nested git worktrees.
- `just smoke` remains unchanged for the existing human workflow.
