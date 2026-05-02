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


def pytest_recording_configure(config: pytest.Config, vcr: object) -> None:
    integration_mode = config.getoption("integration_mode")
    vcr.record_mode = "none" if integration_mode == "replay" else "once"
    vcr.filter_headers = [
        ("authorization", "<redacted>"),
        ("cookie", "<redacted>"),
        ("set-cookie", "<redacted>"),
        ("x-api-key", "<redacted>"),
    ]
