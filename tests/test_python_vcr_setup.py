import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.ai]
ROOT = Path(__file__).resolve().parents[1]


def test_pytest_help_lists_integration_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--integration-mode" in result.stdout
