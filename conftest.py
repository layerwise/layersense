from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration-mode",
        action="store",
        default="replay",
        choices=("replay", "record"),
        help="Control cassette-backed integration tests.",
    )
