import layersense_controller.broker as broker_module
import pytest
from layersense_controller.config import settings
from layersense_controller.render_jobs import RenderJobStore

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_broker_accessors_construct_redis_client_and_job_store(monkeypatch) -> None:
    """Construct cached Redis and render-job store accessors from settings."""
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/14")
    broker_module.create_redis_client.cache_clear()
    broker_module.get_job_store.cache_clear()

    client = broker_module.create_redis_client()
    store = broker_module.get_job_store()

    assert client.connection_pool.connection_kwargs["db"] == 14
    assert isinstance(store, RenderJobStore)
