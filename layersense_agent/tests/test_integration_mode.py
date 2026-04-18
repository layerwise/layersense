import pytest

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_integration_mode_defaults_to_replay(request: pytest.FixtureRequest) -> None:
    assert request.config.getoption("integration_mode") == "replay"
