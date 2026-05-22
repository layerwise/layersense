import importlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_packages_are_importable() -> None:
    """Guard the workspace package wiring through the normal unit-test loop."""
    assert importlib.import_module("layersense_agent") is not None
    assert importlib.import_module("layersense_controller") is not None
    assert importlib.import_module("layersense_domain") is not None
    assert importlib.import_module("layersense_persistence") is not None
