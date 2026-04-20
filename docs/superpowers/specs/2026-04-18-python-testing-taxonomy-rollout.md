# Python Testing Taxonomy Rollout Implementation Plan

> Historical rollout note: this plan captures the intended April 18 taxonomy migration. The current repo now uses `e2e` terminology in active docs and command guidance; treat this file as rollout history rather than the canonical quick-start.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll out LayerSense's Python test taxonomy with `unit`, `integration`, `e2e`, and `ai`, rename `smoke` to `e2e`, and add conservative VCR scaffolding without depending on live refresh runs until the end.

**Architecture:** Keep taxonomy centralized in root pytest config and root `justfile`, classify current package tests conservatively as `unit`, move live-stack coverage to explicit `e2e`, and add package-local VCR setup in `layersense_agent/tests/conftest.py`. Defer the first cassette recording run until the rest of the repo is green and only if the user wants that final live step.

**Tech Stack:** `pytest`, `pytest-asyncio`, `pytest-recording`, workspace `uv`, root `justfile`, package-local `conftest.py`

---

### Task 1: Register the shared pytest taxonomy

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing expectation**

```python
# desired marker config in pyproject.toml
markers = [
    "unit: fast isolated tests",
    "integration: cassette-backed boundary tests",
    "e2e: live-stack end-to-end tests",
    "ai: assistant-authored tests",
]
addopts = ["--strict-markers"]
```

- [ ] **Step 2: Run marker discovery before the change**

Run: `uv run --all-packages pytest --markers`
Expected: `smoke` exists, `unit` / `integration` / `e2e` / `ai` are not all registered correctly yet.

- [ ] **Step 3: Implement the minimal config change**

```toml
[tool.pytest.ini_options]
testpaths = ["layersense_agent/tests", "layersense_controller/tests", "tests"]
addopts = ["--strict-markers"]
markers = [
    "unit: fast isolated tests",
    "integration: cassette-backed boundary tests",
    "e2e: live-stack end-to-end tests",
    "ai: assistant-authored tests",
]
```

- [ ] **Step 4: Run marker discovery after the change**

Run: `uv run --all-packages pytest --markers`
Expected: pytest lists `unit`, `integration`, `e2e`, and `ai`.

### Task 2: Make root test entrypoints match the taxonomy

**Files:**
- Modify: `justfile`

- [ ] **Step 1: Write the failing workflow expectation**

```text
test_python -> unit only
test_python_integration -> integration replay only
test_python_integration_refresh -> integration record only
test_python_e2e -> e2e only
e2e -> explicit live-stack suite path and e2e marker
```

- [ ] **Step 2: Run the current commands before editing**

Run: `just test_python_unit`
Expected: current suite will not yet split cleanly because markers are not fully applied.

- [ ] **Step 3: Implement the minimal justfile changes**

```just
test_python:
    @echo "Python Tests"
    just test_python_unit

test_python_integration_refresh:
    @echo "Python Integration Tests (refresh)"
    uv run --all-packages pytest -m integration --integration-mode=record

e2e:
    uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e
```

- [ ] **Step 4: Run command selection checks**

Run:
- `just test_python_unit`
- `just test_python_integration`

Expected:
- unit command selects only unit-marked tests
- integration command only selects integration-marked tests, even if zero tests are selected at this point

### Task 3: Add package-local integration mode scaffolding

**Files:**
- Create: `layersense_agent/tests/conftest.py`
- Create: `layersense_agent/tests/cassettes/.gitkeep`
- Create: `tests/test_python_vcr_setup.py`

- [ ] **Step 1: Write the failing test**

```python
def test_pytest_help_lists_integration_mode(pytester):
    result = pytester.runpytest("--help")
    result.stdout.fnmatch_lines(["*--integration-mode*"])
```

- [ ] **Step 2: Run the focused test to verify failure**

Run: `uv run --all-packages pytest tests/test_python_vcr_setup.py::test_pytest_help_lists_integration_mode -v`
Expected: FAIL because `--integration-mode` does not exist yet.

- [ ] **Step 3: Implement the smallest VCR setup**

```python
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration-mode",
        action="store",
        default="replay",
        choices=("replay", "record"),
        help="Control cassette-backed integration tests.",
    )


def pytest_recording_configure(config: pytest.Config, vcr: VCR) -> None:
    mode = config.getoption("integration_mode")
    vcr.record_mode = "none" if mode == "replay" else "once"
    vcr.filter_headers = [("authorization", "<redacted>"), ("cookie", "<redacted>")]
```

- [ ] **Step 4: Run the focused test again**

Run: `uv run --all-packages pytest tests/test_python_vcr_setup.py -v`
Expected: PASS.

### Task 4: Reclassify current tests and rename live-stack suite to e2e

**Files:**
- Modify: `layersense_agent/tests/test_animate_scene.py`
- Modify: `layersense_controller/tests/test_cache.py`
- Modify: `layersense_controller/tests/test_main.py`
- Modify: `layersense_controller/tests/test_render.py`
- Modify: `layersense_controller/tests/test_router.py`
- Modify: `layersense_controller/tests/test_watcher.py`
- Modify: `layersense_controller/tests/test_websocket_manager.py`
- Move: `tests/smoke/test_dev_stack_smoke.py` -> `tests/e2e/test_dev_stack_e2e.py`
- Modify: `tests/test_dev_stack_config.py`

- [ ] **Step 1: Write the classification map**

```text
layersense_agent/tests/test_animate_scene.py -> unit + ai
layersense_controller/tests/*.py -> unit + ai
tests/e2e/test_dev_stack_e2e.py -> e2e + ai
tests/test_dev_stack_config.py -> unit + ai
```

- [ ] **Step 2: Run a focused package slice before edits**

Run: `uv run --all-packages pytest layersense_agent/tests layersense_controller/tests tests/test_dev_stack_config.py -v`
Expected: PASS before marker enforcement is fully relied upon.

- [ ] **Step 3: Implement minimal marker edits and file rename**

```python
pytestmark = [pytest.mark.unit, pytest.mark.ai]
```

```python
pytestmark = [pytest.mark.e2e, pytest.mark.ai]
```

- [ ] **Step 4: Run marker selection checks**

Run:
- `uv run --all-packages pytest -m unit -q`
- `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e -q`

Expected:
- unit selection runs only non-live tests
- e2e selection collects only the renamed live-stack suite and still fails if services are absent

### Task 5: Add one conservative integration test without live refresh yet

**Files:**
- Create: `layersense_agent/tests/test_integration_mode.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_integration_mode_is_visible(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("integration_mode") == "replay"
```

- [ ] **Step 2: Run the focused test to verify failure**

Run: `uv run --all-packages pytest layersense_agent/tests/test_integration_mode.py -m integration -v`
Expected: FAIL before the conftest wiring exists or before the marker is registered.

- [ ] **Step 3: Keep the first integration test truthful but non-live**

```python
pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_integration_mode_defaults_to_replay(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("integration_mode") == "replay"
```

This task proves the marker/entrypoint/wiring path now. Do not add cassette-dependent live requests yet.

- [ ] **Step 4: Run the integration slice**

Run: `uv run --all-packages pytest layersense_agent/tests/test_integration_mode.py -m integration --integration-mode=replay -v`
Expected: PASS.

### Task 6: Update docs and references from smoke to e2e

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `AGENTS.md`
- Modify: `docs/2026-04-06-docs-hygiene-followups.md`
- Modify: relevant current-behavior docs under `docs/superpowers/specs/`

- [ ] **Step 1: Write the docs gap list**

```text
README still says just smoke
ROADMAP still points to just smoke
AGENTS still instructs just smoke
historical docs that describe current behavior still use smoke terminology
```

- [ ] **Step 2: Confirm the current docs mismatch**

Run: `rg -n "just smoke|tests/smoke|pytest\.mark\.smoke| -m smoke|smoke tests" README.md docs AGENTS.md`
Expected: matches still exist.

- [ ] **Step 3: Implement minimal doc changes**

```md
- `just e2e`: run black-box end-to-end tests against an already-running local stack
```

```md
LayerSense now uses `e2e` as the live-stack Python test taxonomy term instead of `smoke`.
```

- [ ] **Step 4: Re-run the docs search**

Run: `rg -n "just smoke|tests/smoke|pytest\.mark\.smoke| -m smoke" README.md docs AGENTS.md tests pyproject.toml justfile`
Expected: no current-behavior references remain.

### Task 7: Run required verification, deferring live refresh

**Files:**
- No planned edits unless verification reveals a gap

- [ ] **Step 1: Run focused taxonomy verification**

Run:
- `uv run --all-packages pytest tests/test_python_vcr_setup.py -v`
- `uv run --all-packages pytest layersense_agent/tests layersense_controller/tests tests/test_dev_stack_config.py -m unit -v`
- `uv run --all-packages pytest layersense_agent/tests/test_integration_mode.py -m integration --integration-mode=replay -v`

Expected: PASS.

- [ ] **Step 2: Run repo-required verification**

Run:
- `just lint`
- `just test`
- `just verify_workspace`

Expected: PASS.

- [ ] **Step 3: Run e2e command selection without requiring a live stack claim**

Run: `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py --collect-only -q`
Expected: PASS collection from the renamed path.

- [ ] **Step 4: Stop before live refresh unless the user asks**

Do not run:
- `just test_python_integration_refresh`
- `just e2e`

until the user confirms the live stack is ready and wants that final step.

## Notes

- This plan intentionally delays cassette recording and live-stack verification.
- The first integration test proves the taxonomy plumbing, not the final real-boundary cassette workflow.
- After this plan is complete, the next incremental step is adding one real recorded integration case once the user says the stack is ready.

Unresolved questions:
- none
