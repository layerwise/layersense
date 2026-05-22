from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """Store controller cassettes under the package test tree."""
    del request
    return str(Path(__file__).parent / "cassettes")
