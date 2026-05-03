import os
from pathlib import Path

import pytest

SENSITIVE_VCR_HEADERS = {
    "authorization",
    "api-key",
    "x-api-key",
    "cookie",
    "set-cookie",
}

SENSITIVE_VCR_PARAMETERS = {
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "code",
    "id_token",
    "key",
    "refresh_token",
    "state",
    "token",
    "openai_api_key",
    "openai-project",
    "openai-organization",
    "x-request-id",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration-mode",
        action="store",
        default="replay",
        choices=("replay", "record"),
        help="Control cassette-backed integration tests.",
    )


def _pytest_integration_mode(config: pytest.Config | None) -> str:
    """Integration mode normalizer for pytest config or None input."""
    if config is None:
        return "replay"
    return str(config.getoption("integration_mode"))


def _vcr_record_mode_for_pytest_mode(mode: str) -> str:
    """Pytest recording mode to VCR record mode mapping."""
    return "rewrite" if mode == "record" else "none"


def _is_sensitive_vcr_field(name: str) -> bool:
    return name.lower() in SENSITIVE_VCR_PARAMETERS.union(SENSITIVE_VCR_HEADERS)


def _redact_vcr_response(response: dict):
    """Additional response scrubber."""
    headers = response.get("headers")
    if not isinstance(headers, dict):
        return response

    redacted_headers = {}
    for key, value in headers.items():
        if _is_sensitive_vcr_field(key):
            redacted_headers[key] = ["<redacted>"]
        else:
            redacted_headers[key] = value
    response["headers"] = redacted_headers
    return response


@pytest.fixture(scope="session")
def vcr_config(request: pytest.FixtureRequest) -> dict[str, object]:
    return {
        "record_mode": _vcr_record_mode_for_pytest_mode(_pytest_integration_mode(request.config)),
        # NOTE: we over-redact by merging headers and parameters
        "filter_headers": [
            (field, "<redacted>")
            for field in SENSITIVE_VCR_HEADERS.union(SENSITIVE_VCR_PARAMETERS)
        ],
        "filter_query_parameters": [
            (field, "<redacted>")
            for field in SENSITIVE_VCR_HEADERS.union(SENSITIVE_VCR_PARAMETERS)
        ],
        "filter_post_data_parameters": [
            (field, "<redacted>")
            for field in SENSITIVE_VCR_HEADERS.union(SENSITIVE_VCR_PARAMETERS)
        ],
        "before_record_response": _redact_vcr_response,
        # NOTE: this can become necessary if we need custom redaction logic
        # "before_record_request": _redact_vcr_request,
    }


@pytest.fixture(autouse=True)
def fail_fast_on_missing_vcr_cassette(request: pytest.FixtureRequest) -> None:
    """Fail replay-mode VCR tests before execution when the cassette is missing."""
    if request.config.getoption("integration_mode") != "replay":
        return
    if request.node.get_closest_marker("vcr") is None:
        return
    cassette_dir = request.getfixturevalue("vcr_cassette_dir")
    cassette_path = Path(cassette_dir) / f"{request.node.name}.yaml"
    if cassette_path.exists():
        return
    pytest.fail(
        f"Missing VCR cassette for replay mode: {cassette_path}. Run in refresh mode first."
    )


@pytest.fixture(autouse=True)
def normalize_vcr_secrets(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalize credential env vars for cassette-backed tests by integration mode."""
    if request.node.get_closest_marker("vcr") is None:
        return

    if _pytest_integration_mode(request.config) == "record":
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            pytest.fail("Set OPENAI_API_KEY to record integration cassettes.")
        monkeypatch.setenv("OPENAI_API_KEY", openai_api_key)
        return

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
