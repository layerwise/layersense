import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]


PRIMARY_MARKERS = {"unit", "integration", "e2e"}
EXPECTED_SHARED_MARKERS = {"ai"}


def _python_test_modules() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted(
        list((root / "layersense_controller" / "tests").rglob("test_*.py"))
        + list((root / "layersense_agent" / "tests").rglob("test_*.py"))
        + list((root / "tests").rglob("test_*.py"))
    )


def _marker_names(module_path: Path) -> set[str]:
    content = module_path.read_text()
    return {
        marker
        for marker in EXPECTED_SHARED_MARKERS | PRIMARY_MARKERS
        if f"pytest.mark.{marker}" in content
    }


def _test_function_nodes(module_path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(module_path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def test_python_test_inventory_includes_nested_package_modules() -> None:
    """Track nested package tests so taxonomy checks cover the real suite."""
    module_paths = _python_test_modules()

    assert any("/layersense_agent/tests/unit/" in path.as_posix() for path in module_paths)
    assert any("/layersense_controller/tests/unit/" in path.as_posix() for path in module_paths)
    assert any("/tests/e2e/" in path.as_posix() for path in module_paths)


def test_python_test_modules_have_one_primary_marker() -> None:
    """Keep every Python test module classified under one primary test marker."""
    for module_path in _python_test_modules():
        marker_names = _marker_names(module_path)
        primary = marker_names & PRIMARY_MARKERS

        assert len(primary) == 1, module_path.name


def test_python_test_functions_have_one_line_docstrings() -> None:
    """Require concise one-line docstrings on every Python test function."""
    for module_path in _python_test_modules():
        for test_node in _test_function_nodes(module_path):
            docstring = ast.get_docstring(test_node, clean=False)

            assert docstring, f"{module_path}:{test_node.lineno}"
            assert "\n" not in docstring, f"{module_path}:{test_node.lineno}"
            assert docstring == docstring.strip(), f"{module_path}:{test_node.lineno}"


def test_core_packages_have_integration_test_modules() -> None:
    """Require at least one integration module for each core Python package."""
    root = Path(__file__).resolve().parents[1]

    assert sorted((root / "layersense_agent" / "tests" / "integration").glob("test_*.py"))
    assert sorted((root / "layersense_controller" / "tests" / "integration").glob("test_*.py"))
