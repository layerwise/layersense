# Python Testing Taxonomy Design

## Goal

Define a clean pytest taxonomy and execution model for the Python workspace, starting with `puc_agent`, so developers can distinguish fast isolated tests from VCR-backed integration coverage and stack-bound end-to-end coverage.

> Historical plan note: this design captures the intended direction from 2026-04-09. The current repo state now implements the taxonomy across both `puc_agent` and `puc_evaluate`, uses `global_tests/python/` for repo-level Python meta-tests, and keeps package-specific runtime fixtures in package-local `conftest.py` files.

## Context

- The workspace currently configures pytest centrally in the root `pyproject.toml`.
- `puc_agent/tests/` contained the initial Python test suite at planning time.
- Existing `puc_agent` tests were mostly unit-style because they monkeypatched external calls and used in-process FastAPI fixtures.
- VCR tooling and cassette workflow had not yet been wired into the repo at planning time.
- The repo-level default Python test command then ran all Python tests via `uv run --all-packages pytest`.
- The initial rollout focus was `puc_agent`, with `puc_evaluate` to follow later.

## Decision

Use four semantic pytest markers:

- `unit`
- `integration`
- `e2e`
- `ai`

Use a single `integration` marker with two execution modes:

- replay mode: run against existing VCR cassettes and fail when a test attempts unmatched live outbound traffic
- refresh mode: run the same tests against the local docker-compose service stack and update cassettes

The default Python test command should run `unit` tests only for now.

Current state:

- `just test_python` delegates to `just test_python_unit`
- `just test_python_unit` runs `uv run --all-packages pytest -m unit`
- `puc_evaluate` tests are now also marked under the same taxonomy
- repo-level Python meta-tests live in `global_tests/python/`

## Marker Taxonomy

### `unit`

`unit` is for fast tests with no real external dependencies. Any dependency boundary such as HTTP, LLM calls, Qdrant access, or service lookups must be replaced with fakes, monkeypatches, or in-process doubles.

This should remain the default category for normal developer feedback and CI smoke confidence.

### `integration`

`integration` is for tests that exercise real boundary behavior in `puc_agent` while replaying external HTTP interactions from VCR cassettes.

These tests should validate request shape, response handling, auth/header propagation, parsing, and similar cross-boundary behavior without requiring the live stack during normal runs.

The same tests must support a refresh mode that records updated cassettes against the local docker-compose service stack.

### `e2e`

`e2e` is reserved for tests that only make sense inside a Docker environment matching the deployed dev stack and production network topology.

These tests are intentionally excluded from normal local runs and from VCR replay because their value depends on the real multi-service network setup.

### `ai`

`ai` is an orthogonal provenance marker applied to all assistant-authored tests.

For the current rollout, all existing `puc_agent` tests should be marked `ai` because they were created by coding assistants. Future assistant-authored tests must continue this convention.

## Execution Model

### Default mode

The default Python test entrypoint should select `unit` tests only.

This keeps the day-to-day feedback loop fast and avoids surprising failures from cassette drift or missing local services.

### Integration replay mode

Replay mode runs `integration` tests using existing cassettes. If a test attempts unmatched outbound traffic, the test should fail naturally at the point of the request.

This is not a separate pre-run network scan. The policy is simply that replay mode must not silently fall through to the network.

### Integration refresh mode

Refresh mode runs the same `integration` tests while the local docker-compose service stack is available and updates cassettes from live interactions.

This mode should be explicit so developers only opt into it when intentionally refreshing recordings after architecture or contract changes.

### End-to-end mode

`e2e` tests should have a separate explicit entrypoint and remain out of scope for the first rollout except for marker registration and documentation.

## Configuration Shape

### Central pytest configuration

Keep marker registration centralized in the root `pyproject.toml` so the taxonomy applies consistently across Python packages.

The configuration should:

- register the four markers
- enable strict marker handling
- make it easy for helper commands to select `unit`, `integration`, or `e2e` suites explicitly

### Package-level test infrastructure

Use package-local `conftest.py` files for package-specific integration helpers. In the first rollout this meant `puc_agent/tests/conftest.py`.

- VCR configuration
- cassette path conventions
- replay vs refresh mode switching
- any request filtering or normalization needed to keep cassettes stable

## Cassette Strategy

Store cassettes under the package-local cassette tree. In the current implementation this is `puc_agent/tests/cassettes/`, with a stable layout derived from the test module location.

The cassette workflow should include normalization for noisy or sensitive fields such as:

- authorization headers
- API keys
- timestamps
- request IDs or similar non-deterministic fields

Replay failures should tell the developer that the recording no longer matches reality and that the refresh entrypoint should be used.

## Migration Scope

### Phase 1: `puc_agent`

The first rollout should cover:

- marker registration and enforcement
- classification of all existing `puc_agent` tests as `unit`, `integration`, or `e2e`
- marking all existing `puc_agent` tests with `ai`
- adding the replay/refresh integration infrastructure
- copying a representative subset of true boundary tests into VCR-backed `integration` coverage while preserving the original fast unit tests
- documenting the workflow and assistant convention

### Phase 2: `puc_evaluate`

After the `puc_agent` structure settles, apply the same taxonomy and workflow to `puc_evaluate`.

Current state: `puc_evaluate` has already adopted the shared marker taxonomy for its existing unit tests, while package-specific VCR/runtime helper logic remains centered in `puc_agent`.

## Commands And Entry Points

The intended command model is:

- default Python test command: run `unit`
- explicit unit command: `just test_python_unit`
- explicit integration replay command: run `integration` against cassettes
- explicit integration refresh command: run `integration` against the local docker stack and update cassettes
- explicit `e2e` command: reserved for dockerized deployed-topology runs

Current concrete commands are now defined in the root `justfile`.

## Risks And Tradeoffs

- VCR is best suited to HTTP boundaries. Not every dependency belongs in `integration` just because it is external.
- Some current tests that touch Qdrant-related types or app state may still remain `unit` if the dependency itself is mocked.
- Cassette churn is likely when auth, service topology, or payload shapes change. The design embraces this by making refresh explicit.
- Over-classifying tests as `integration` would slow maintenance and increase cassette noise; the rollout should stay conservative.

## Out Of Scope

- Full migration of `puc_evaluate`
- Automatic preflight detection of outbound traffic before tests run
- Broad redesign of non-Python test commands
- Introducing separate marker variants such as `integration_vcr`

## Open Questions Resolved

- `integration` should remain a single semantic marker.
- Replay versus refresh should be controlled by execution mode, not by markers.
- Replay mode should fail when unmatched outbound traffic is attempted.
- The default Python test command should run `unit` only for now.
