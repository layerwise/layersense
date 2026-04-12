---
name: write-python-tests
description: Use when adding, modifying, classifying, or duplicating Python tests in this repository, especially when choosing between unit, integration, and e2e coverage, wiring VCR-backed tests, or deciding how the workspace Python packages should follow the repo's pytest conventions.
---

# Write Python Tests

## Overview

Write Python tests to match this repo's taxonomy and execution model, not generic pytest taste.

Core principle: prefer the fastest truthful test, mark it correctly, and preserve fast mocked coverage even when adding slower boundary coverage.

Before writing or changing tests, use `superpowers:test-driven-development`.

## When to Use

Use this skill when:

- adding new tests under `<python_package>/tests`
- reclassifying existing Python tests
- deciding whether a test should be `unit`, `integration`, or `e2e`
- adding or refreshing VCR-backed tests
- touching Python test helpers, `conftest.py`, cassettes, or `just` entrypoints

Do not use this skill for Rust tests or non-repo Python projects.

## Repo Rules

- Run Python commands with `uv run --all-packages ...`
- New assistant-authored tests must always include `ai` marker
- Every test must have exactly one primary marker: `unit`, `integration`, or `e2e`
- Prefer module-level markers when a whole file belongs to one class
- Default to `unit` unless the test intentionally exercises a real external boundary
- Do not convert a fast mocked unit test into integration coverage by default; copy a representative boundary test into a new integration module and keep the existing unit test

## Marker Taxonomy

### `unit`

Use `unit` for fast tests with no real external dependencies.

Allowed patterns:

- monkeypatched HTTP clients
- fake Qdrant or RAG helpers
- in-process FastAPI fixtures
- direct model, parser, prompt, utils, and settings tests

If the test would still pass on an airplane with no services running, it is probably `unit`.

### `integration`

Use `integration` for real boundary behavior replayed through VCR cassettes.

In this repo, `integration` means one semantic marker with two execution modes:

- replay: run against cassettes and fail if a request is not matched
- record: run against the local docker-compose-backed service and refresh the cassette

Good candidates:

- real HTTP probes to local Keycloak, Qdrant, or similar local-stack services
- request/response contract checks where mocks would hide integration mistakes

Bad candidates:

- tests that still monkeypatch the boundary anyway
- tests that only validate pure parsing or model logic

### `e2e`

Use `e2e` only for tests that require the dockerized deployed-dev topology matching production networking.

Do not use VCR for `e2e`.

### `ai`

Apply `ai` to every assistant-authored test. It overlaps with any primary marker.

## Choosing the Test Type

Use this decision order:

1. Can the behavior be tested truthfully with mocks or in-process doubles?
   - Yes: `unit`
2. Does the value come from exercising a real HTTP or service boundary that can be recorded and replayed?
   - Yes: `integration`
3. Does the behavior only make sense in the deployed-style multi-container topology?
   - Yes: `e2e`

When uncertain, bias toward `unit` and add a copied `integration` test later if boundary realism proves valuable.

## Adding New Tests

### In general

- Ask yourself: does this test assess an actual function or just a specific implementation detail? If the latter, can it be rewritten to test functional behavior instead?
- Write a docstring that justifies the test's existence and what function it tests. If nothing comes to mind, don't write the test.

### For new `unit` tests

- Add `pytestmark = [pytest.mark.unit, pytest.mark.ai]` at module scope when the whole file is unit-only
- Keep dependencies mocked, monkeypatched, or local to the process
- Verify with the narrowest test target first

### For new `integration` tests

- Put them in a separate test module from the unit version when practical
- Mark the module `pytestmark = [pytest.mark.integration, pytest.mark.ai, pytest.mark.vcr]`
- Use local docker-compose-backed services as the recording source
- Store cassettes under the package's `tests/cassettes/` tree
- Filter secrets and noisy headers in package `conftest.py`
- Fail clearly in record mode when required env vars or local services are missing

### For new `e2e` tests

- Keep them separate from unit/integration files
- Assume they are opt-in and environment-coupled
- Do not make them part of the default Python test loop

## Copy, Don't Convert

When a mocked boundary test already exists and you need real boundary coverage:

- keep the existing mocked test as `unit`
- copy the representative scenario into a new integration test file
- replace mocked transport with the real local-stack boundary
- record a cassette for the new integration test

Why: the unit test preserves speed and local debugging value, while the integration test proves the real contract.

## VCR Rules

- One `integration` marker, two modes; do not invent `integration_vcr`
- Replay mode must not silently fall through to real outbound network access
- Refresh mode is explicit and updates cassettes against local services
- Filter secrets such as `authorization`, `api-key`, `x-api-key`, `cookie`, and `set-cookie`
- Normalize volatile fields when needed to keep cassettes stable
- Replay failures should point developers toward the refresh command

Avoid brittle imports in integration tests. Do not rely on bare `import conftest` if multiple test packages exist in the repo.

## Commands

Use these entrypoints when they exist:

- `just test_python_unit` -> unit tests
- `just test_python_integration` -> integration replay
- `just test_python_integration_refresh` -> integration record/refresh (use only when instructed or you know for sure the dev stack is running)
- `just test_python_e2e` -> e2e tests, use only when instructed

Don't use:

- `just test_python` -> this is a user and CI facing entrypoint that includes some or all of the other commands
and might change at any point at the user's discretion

For targeted work, prefer:

- `uv run --all-packages pytest <test-path> -v`
- `uv run --all-packages pytest <test-path> --integration-mode=replay -v`
- `uv run --all-packages pytest <test-path> --integration-mode=record -v`

## Package Appendices

- For `layersense_controller`, also follow `appendix-layersense-controller.md`
- For `layersense_agent`, also follow `appendix-layersense-agent.md`

## Common Mistakes

- Forgetting `ai`
- Leaving tests unmarked
- Marking mocked tests as `integration`
- Replacing existing unit tests instead of copying representative cases into new integration modules
- Using generic Python commands instead of `uv run --all-packages ...`
- Using replay mode before a cassette exists and then treating the failure as a code bug
- Importing helpers through ambiguous top-level `conftest` resolution when multiple test packages exist

## Minimum Verification

For test work, verify in this order:

1. narrow target test file
2. relevant package test slice
3. repo entrypoint (`just test_python_unit` and `just test_python_integration`)

If you changed shared Python test infrastructure, also verify the affected marker entrypoints.
