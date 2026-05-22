from __future__ import annotations

from pathlib import Path

import fakeredis
import layersense_controller.cache as cache_module
import pytest


@pytest.fixture(scope="session")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """Store controller cassettes under the package test tree."""
    del request
    return str(Path(__file__).parent / "cassettes")


@pytest.fixture(autouse=True)
def fake_cache_lock_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cache-index lock tests isolated from a live Redis service."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        cache_module,
        "_cache_redis_client",
        lambda: fakeredis.FakeRedis(server=server, decode_responses=True),
    )
