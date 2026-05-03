import json

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
