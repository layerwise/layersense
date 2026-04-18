# Python Testing Taxonomy Implementation Plan

> Historical plan note: this plan was written before the rollout completed. The current repo state differs in several concrete ways: repo-level Python meta-tests now live under `global_tests/python/`, `puc_evaluate` tests are already marked under the taxonomy, and the final VCR implementation keeps package-specific runtime helpers in `puc_agent/tests/conftest.py` while using top-level tests to verify repo-wide behavior.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a clean pytest marker taxonomy, VCR-backed integration workflow, and assistant test-marking convention for the Python workspace, while keeping the default Python test entrypoint limited to `unit` tests.

**Architecture:** Keep test taxonomy semantic and centralized in the root pytest config. Implement replay versus refresh as execution modes for one `integration` marker, with package-local runtime helpers and repo-level meta-tests under `global_tests/python/`. Migrate existing tests conservatively: classify them, add `ai` to assistant-authored tests, and copy only representative true boundary tests into VCR-backed integration coverage in the first pass.

**Tech Stack:** `pytest`, `pytest-asyncio`, `pytest-vcr`, workspace `uv`, root `justfile`, `puc_agent/tests/conftest.py`

---

### Task 1: Add repo-level marker taxonomy and test dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the failing configuration target**

Decide the exact pytest configuration additions needed in `pyproject.toml`:

- register `unit`, `integration`, `e2e`, `ai`
- enable strict marker checking
- add `pytest-vcr` to `[dependency-groups].dev`

The goal of this step is to make pytest aware of the marker taxonomy before any test files are updated.

**Step 2: Run pytest marker discovery to confirm current state**

Run: `uv run --all-packages pytest --markers`

Expected: pytest output does not yet list the new markers before the config change.

**Step 3: Implement the minimal config change**

Update `pyproject.toml` so the new markers are registered centrally and `pytest-vcr` is available in the dev dependency group.

**Step 4: Run pytest marker discovery again**

Run: `uv run --all-packages pytest --markers`

Expected: pytest lists `unit`, `integration`, `e2e`, and `ai`.

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "test: register python test markers"
```

### Task 2: Add `puc_agent` pytest mode switching and VCR scaffolding

**Files:**
- Modify: `puc_agent/tests/conftest.py`
- Create: `puc_agent/tests/cassettes/.gitkeep`

**Step 1: Write the failing test**

Add or extend focused coverage for the package-specific pytest/VCR behavior. In the final implementation, this coverage moved to `global_tests/python/test_python_vcr_setup.py` so repo-level meta-tests do not live under `puc_agent/tests/`.

Suggested test shape:

```python
def test_integration_mode_defaults_to_replay(pytester):
    result = pytester.runpytest("--help")
    result.stdout.fnmatch_lines(["*integration-mode*"])
```
```

If using `pytester` feels too invasive for the current repo, instead write a direct unit test for any helper function introduced in `conftest.py`.

**Step 2: Run the test to verify it fails**

Run a focused Python test target for the package-specific VCR behavior.

Expected: FAIL because the mode-switching helper or option does not exist yet.

**Step 3: Write minimal implementation**

In `puc_agent/tests/conftest.py`:

- add a pytest option for integration mode, defaulting to `replay`
- wire `pytest-vcr` defaults so replay mode does not silently hit the network
- provide a stable cassette directory policy under `puc_agent/tests/cassettes/`
- add filtering for secrets or obviously volatile headers

Keep the implementation small and package-scoped. Do not over-generalize to `puc_evaluate` yet.

**Step 4: Run the focused tests to verify they pass**

Run the focused Python meta-test target again.

Expected: PASS.

**Step 5: Commit**

```bash
git add puc_agent/tests/conftest.py puc_agent/tests/test_pytest_modes.py puc_agent/tests/cassettes/.gitkeep
git commit -m "test(puc_agent): add integration mode and vcr scaffolding"
```

### Task 3: Add root test entrypoints for `unit`, `integration`, and refresh workflow

**Files:**
- Modify: `justfile`

**Step 1: Write the failing workflow expectation**

Document the exact command targets to add before editing:

- keep `test_python` focused on `unit`
- add explicit integration replay target
- add explicit integration refresh target
- reserve an explicit `e2e` target if useful, even if not yet wired deeply

This step is complete when you can state the exact commands to implement.

**Step 2: Verify the current command behavior**

Run: `just test_python`

Expected: it currently runs all Python tests without marker filtering.

**Step 3: Implement the minimal command changes**

Update `justfile` so:

- `test_python` runs only `unit`
- `test_python_integration` runs `integration` in replay mode
- `test_python_integration_refresh` runs `integration` in refresh mode
- optionally `test_python_e2e` selects `e2e`

Use `uv run --all-packages pytest` consistently.

**Step 4: Run the commands to verify marker selection**

Run:

- `just test_python`
- `just test_python_integration`

Expected:

- unit command selects only `unit`
- integration command selects only `integration`

**Step 5: Commit**

```bash
git add justfile
git commit -m "test: add python test entrypoints by marker"
```

### Task 4: Classify existing `puc_agent` tests and add `ai`

**Files:**
- Modify: `puc_agent/tests/test_agent.py`
- Modify: `puc_agent/tests/test_answer_streamed.py`
- Modify: `puc_agent/tests/test_app_startup_state.py`
- Modify: `puc_agent/tests/test_app_state.py`
- Modify: `puc_agent/tests/test_dev_oauth_jwt.py`
- Modify: `puc_agent/tests/test_endpoints_tracing.py`
- Modify: `puc_agent/tests/test_html_tools.py`
- Modify: `puc_agent/tests/test_models.py`
- Modify: `puc_agent/tests/test_prompt.py`
- Modify: `puc_agent/tests/test_tool_context_access.py`
- Modify: `puc_agent/tests/test_tracing.py`
- Modify: `puc_agent/tests/test_ui_components.py`
- Modify: `puc_agent/tests/test_utils.py`

**Step 1: Create the classification map**

Review every existing `puc_agent/tests/*.py` file and write down whether each test should be `unit`, `integration`, or `e2e`.

Bias toward `unit` unless the test truly exercises a real HTTP boundary that should later be cassette-backed.

**Step 2: Run the targeted suite with strict markers in mind**

Run: `uv run --all-packages pytest puc_agent/tests -v`

Expected: current suite passes without semantic markers, providing a baseline before edits.

**Step 3: Implement the smallest marker edits**

Add module-level or function-level markers as appropriate:

- every existing test gets `ai`
- every existing test gets exactly one primary marker from `unit`, `integration`, `e2e`

Prefer module-level markers when a whole file belongs to one class.

**Step 4: Run unit and integration selection checks**

Run:

- `uv run --all-packages pytest puc_agent/tests -m unit -v`
- `uv run --all-packages pytest puc_agent/tests -m integration -v`

Expected: the suite splits cleanly with no unmarked tests.

**Step 5: Commit**

```bash
git add puc_agent/tests
git commit -m "test(puc_agent): classify existing tests"
```

### Task 5: Convert representative boundary tests to VCR-backed integration coverage

**Files:**
- Keep existing unit tests in place
- Create new integration-focused test modules
- Create: `puc_agent/tests/cassettes/`

**Step 1: Write the failing integration test behavior**

Pick one or two representative HTTP-boundary tests in `puc_agent` that should become true VCR-backed `integration` coverage.

Suggested candidates depend on actual code paths discovered during implementation, but likely involve:

- outbound HTML fetching or transformation paths
- OAuth/JWT helper HTTP exchanges
- tool context access that performs real HTTP calls

For each chosen test, copy a representative unit scenario into a new integration-focused test so the original fast unit coverage remains intact.

**Step 2: Run the chosen tests in replay mode to confirm missing cassette failure**

Run: `uv run --all-packages pytest <selected-tests> -m integration --integration-mode=replay -v`

Expected: FAIL because the required cassettes do not exist yet.

**Step 3: Record the minimal initial cassettes**

Bring up the required local docker-compose services, then run the refresh entrypoint to record cassettes for the selected tests.

Run: `just up` as needed, then `just test_python_integration_refresh`

Expected: selected integration tests PASS and cassette files are written.

**Step 4: Verify replay mode works without live outbound network**

Run: `just test_python_integration`

Expected: PASS using cassettes only.

**Step 5: Commit**

```bash
git add puc_agent/tests
git commit -m "test(puc_agent): add vcr-backed integration coverage"
```

### Task 6: Document the taxonomy, commands, and assistant convention

**Files:**
- Modify: `puc_agent/README.md`
- Modify: `README.md`
- Create: `docs/python-testing-layout.md`

**Step 1: Write the failing documentation gap list**

List the user-facing docs gaps created by the new behavior:

- marker meanings
- default unit-only test command
- integration replay versus refresh workflow
- local stack requirement for cassette refresh
- `ai` marker convention for assistant-authored tests

**Step 2: Confirm the current docs are incomplete**

Read:

- `puc_agent/README.md`
- `README.md`

Expected: they do not currently document the new taxonomy or commands.

**Step 3: Implement the minimal documentation changes**

Update docs so a new contributor can answer:

- which marker to use for a new test
- how to run unit tests
- how to run integration replay
- how to refresh cassettes
- why replay mode fails on unexpected outbound requests

Keep the detailed workflow in `docs/python-testing-layout.md` and add brief pointers from the package and repo READMEs.

**Step 4: Run a quick docs verification pass**

Run: `grep` or targeted file reads to confirm the commands and marker names in docs match the implemented `justfile` and pytest config.

Expected: docs and commands align.

**Step 5: Commit**

```bash
git add puc_agent/README.md README.md docs/python-testing.md
git commit -m "docs: document python test taxonomy and workflow"
```

### Task 7: Verify the rollout end-to-end

**Files:**
- No code changes expected unless verification reveals gaps.

**Step 1: Run formatting and linting**

Run:

- `cargo fmt`
- `just lint_python`

Expected: PASS.

**Step 2: Run marker-specific Python verification**

Run:

- `just test_python`
- `just test_python_integration`

If integration coverage exists:

- `just test_python_integration_refresh`

Expected:

- unit default works
- integration replay works from cassettes
- refresh updates recordings when local services are available

**Step 3: Run full project verification required by repo policy**

Run:

- `just lint`
- `just test`

Expected: PASS, or stop and present options if lint warnings require a suppression decision.

**Step 4: Review changed files for stale docs or dead code**

Check whether any helper comments, old test instructions, or unused fixtures should now be removed.

Expected: no stale instructions remain.

**Step 5: Commit final verification fixups if needed**

```bash
git add <any follow-up files>
git commit -m "chore: finalize python test taxonomy rollout"
```

## Notes For Execution

- Do not convert every plausible boundary test to VCR in the first pass. One or two representative integrations are enough to validate the workflow.
- Prefer module-level markers to reduce annotation churn.
- Keep `puc_evaluate` untouched except for shared repo-level pytest configuration.
- If a test seems to need a database or service but is still heavily monkeypatched, keep it `unit` until a real VCR-backed integration case is worth the maintenance cost.
- Do not create commits unless the human explicitly asks for them; the commit steps above describe logical checkpoints for execution sessions.
