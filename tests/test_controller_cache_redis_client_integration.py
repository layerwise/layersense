import layersense_controller.cache as cache_module
import pytest
from layersense_controller.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_cache_redis_client_constructs_sync_client(monkeypatch) -> None:
    """Build the production sync Redis client from configured settings without connecting."""
    cache_module._cache_redis_client.cache_clear()
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/15")

    client = cache_module._cache_redis_client()

    assert client.connection_pool.connection_kwargs["db"] == 15
