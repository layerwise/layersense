# Python Testing Taxonomy Design For LayerSense

> Historical rollout note: this design captures the April 18 taxonomy rollout rationale. Current command and contributor guidance should be taken from `README.md`, `AGENTS.md`, `justfile`, and `pyproject.toml`.

## Goal

Adopt a clean pytest taxonomy and execution model for LayerSense so contributors can distinguish fast isolated tests from cassette-backed boundary coverage and live-stack end-to-end coverage.

This rollout imports the core design from the 2026-04-09 testing taxonomy plans, but adapts it to LayerSense's current package structure and command surface.

## Current Repo Context

- Pytest configuration is centralized in the root `pyproject.toml`.
- Root commands already include partial taxonomy support in `justfile`, but the configuration and suite classification are inconsistent.
- Current Python packages are `layersense_agent` and `layersense_controller`.
- Existing package tests are primarily unit-style because they use monkeypatching, in-process FastAPI clients, and subprocess mocking.
- The repo's live-stack tests are selected with the `e2e` marker and documented through the root `justfile` command surface.
- The repo already includes `pytest-recording`, which should be used to implement cassette-backed `integration` coverage.

## Decision

Use four semantic pytest markers across the Python workspace:

- `unit`
- `integration`
- `e2e`
- `ai`

Use a single `integration` marker with two execution modes:

- replay mode: run against recorded cassettes and fail when outbound traffic is not matched
- record mode: run against the local stack and refresh cassettes intentionally

The default Python test entrypoint should run `unit` only.

LayerSense uses `e2e` as the live-stack taxonomy term everywhere: marker names, commands, docs, and paths.

## Marker Taxonomy

### `unit`

`unit` is for fast tests with no real external dependencies. HTTP, websocket, subprocess, and cross-service boundaries must be replaced with in-process doubles, monkeypatches, fixtures, or mocks.

This should be the default developer loop and the default Python suite selected by `just test_python`.

### `integration`

`integration` is for tests that exercise real boundary behavior while replaying HTTP interactions from cassettes.

In this repo, the first rollout should keep scope conservative and introduce only representative boundary coverage, most likely around `layersense_agent` HTTP-facing behavior where replayed requests provide durable value.

Integration tests must support two modes:

- replay: no silent fallthrough to live network
- record: refresh cassettes intentionally against the local dev stack

### `e2e`

`e2e` is for tests that only make sense against the live local stack and real multi-service topology.

The existing black-box stack tests currently called smoke tests should be reclassified as `e2e` and moved under an `e2e` path.

### `ai`

`ai` is an orthogonal provenance marker for assistant-authored tests.

Existing assistant-authored Python tests should be marked `ai`, and future assistant-authored tests should continue that convention.

## Execution Model

### Default mode

`just test_python` should run only `unit` tests.

This keeps the default feedback loop fast and prevents surprise failures from missing live services, cassette drift, or intentionally slow stack tests.

### Integration replay mode

Replay mode runs `integration` tests from existing cassettes. If a request is not matched, the test should fail at the request boundary rather than silently reaching the network.

### Integration record mode

Record mode runs the same `integration` tests while the local stack is available and refreshes cassette data. This must remain explicit.

### End-to-end mode

`e2e` tests should have a dedicated explicit entrypoint and should not run as part of the default Python suite.

## Configuration Shape

### Central pytest configuration

Root `pyproject.toml` should:

- register `unit`, `integration`, `e2e`, and `ai`
- enable strict marker handling
- point pytest at the actual Python test roots used in this repo

### Package-level test infrastructure

Use `layersense_agent/tests/conftest.py` for package-scoped integration mode and cassette helpers in the first rollout.

This conftest should own:

- the `--integration-mode` pytest option
- mode-sensitive recording defaults
- cassette directory policy
- basic scrubbing of obviously sensitive or unstable request fields

## Scope Of Migration

### Phase 1: Shared taxonomy and command cleanup

Implement the shared marker taxonomy and make commands consistent with it.

This includes:

- fixing central pytest marker registration
- ensuring `just test_python` runs only `unit`
- keeping explicit integration replay and record commands
- renaming `smoke` command usage to `e2e`
- renaming live-stack test paths from `smoke` to `e2e`

### Phase 2: Classify current tests

Classify existing Python tests conservatively.

- `layersense_agent/tests/*` should mostly be `unit`
- `layersense_controller/tests/*` should mostly be `unit`
- current live-stack tests become `e2e`
- assistant-authored tests receive `ai`

Bias toward `unit` unless a test truly exercises a real external boundary worth preserving via cassette replay.

### Phase 3: Add representative integration coverage

Add a small number of `integration` tests to validate the workflow end to end without converting large parts of the suite.

The goal is to prove the taxonomy and replay/record workflow, not to force every boundary test into VCR immediately.

## Commands

The intended command model for LayerSense is:

- `just test_python`: run `unit`
- `just test_python_unit`: run `unit`
- `just test_python_integration`: run `integration` in replay mode
- `just test_python_integration_refresh`: run `integration` in record mode
- `just test_python_e2e`: run `e2e`
- `just e2e`: run the live-stack black-box suite selected by `e2e`

If `just smoke` exists today, it should be renamed rather than preserved as a compatibility alias.

## Documentation Changes

Documentation should be updated in the same rollout so contributors can answer:

- which marker to use for a new test
- which commands run unit, integration, and e2e suites
- how replay differs from record mode
- why integration replay fails on unmatched outbound requests
- that LayerSense now uses `e2e`, not `smoke`, for live-stack Python tests

Affected docs likely include the root `README.md`, testing-related docs under `docs/`, and any references to smoke testing in `ROADMAP.md` or adjacent planning docs where current behavior is being described.

## Testing Strategy

Verification should cover:

- marker discovery via pytest
- command selection for `unit`, `integration`, and `e2e`
- focused VCR helper tests
- representative integration replay and record workflows if stack prerequisites are available
- repo-required checks: `just lint`, `just test`, `just verify_workspace`

## Risks And Tradeoffs

- Over-classifying tests as `integration` would increase maintenance cost and cassette churn.
- Replacing `smoke` with `e2e` everywhere will touch docs and command muscle memory, but avoids long-term naming drift.
- Current live-stack tests may still be referred to as smoke tests in historical docs; those references should be updated where they describe current behavior.
- `pytest-recording` is best suited to HTTP boundaries. Tests dominated by mocks should remain `unit`.

## Out Of Scope

- Broad redesign of frontend tests
- Converting every possible boundary test to cassette-backed coverage in one pass
- Backward-compatibility aliases for `smoke`
- Non-Python testing taxonomy changes beyond documentation alignment where they reference Python live-stack tests

## Implementation Direction

Use the existing 2026-04-09 implementation plan as the base execution model, but adapt file paths and package names to LayerSense:

- `puc_agent` -> `layersense_agent`
- `puc_evaluate` references are not applicable here
- `global_tests/python/` concepts should map to this repo's actual top-level test layout
- `smoke` references should become `e2e`

This should be implemented as a full taxonomy rollout now, with conservative VCR scope.
