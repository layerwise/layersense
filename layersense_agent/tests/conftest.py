from __future__ import annotations

from pathlib import Path

import pytest


def pytest_recording_configure(config: pytest.Config, vcr: object) -> None:
    integration_mode = config.getoption("integration_mode")
    vcr.record_mode = "none" if integration_mode == "replay" else "once"
    vcr.filter_headers = [
        ("authorization", "<redacted>"),
        ("cookie", "<redacted>"),
        ("set-cookie", "<redacted>"),
        ("x-api-key", "<redacted>"),
    ]


@pytest.fixture(scope="session")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> Path:
    del request
    return Path(__file__).parent / "cassettes"
