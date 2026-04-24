from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]


PRIMARY_MARKERS = {"unit", "integration", "e2e"}
EXPECTED_SHARED_MARKERS = {"ai"}


def _python_test_modules() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return sorted(
        list((root / "layersense_controller" / "tests").glob("test_*.py"))
        + list((root / "layersense_agent" / "tests").glob("test_*.py"))
        + list((root / "tests").glob("test_*.py"))
    )


def _marker_names(module_path: Path) -> set[str]:
    content = module_path.read_text()
    return {
        marker
        for marker in EXPECTED_SHARED_MARKERS | PRIMARY_MARKERS
        if f"pytest.mark.{marker}" in content
    }


def test_python_test_modules_have_one_primary_marker():
    """Keep every Python test module classified under one primary test marker."""
    for module_path in _python_test_modules():
        marker_names = _marker_names(module_path)
        primary = marker_names & PRIMARY_MARKERS

        assert len(primary) == 1, module_path.name
