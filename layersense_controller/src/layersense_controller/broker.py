from functools import lru_cache

from redis import asyncio as redis_asyncio
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from layersense_controller.config import settings
from layersense_controller.render_jobs import RenderJobStore

broker = RedisStreamBroker(url=str(settings.redis_url)).with_result_backend(
    RedisAsyncResultBackend(redis_url=str(settings.redis_url))
)


# Keep runtime access behind cached accessor functions so tests can monkeypatch
# accessors instead of relying on module reload to refresh import-time singletons.
@lru_cache
def create_redis_client() -> redis_asyncio.Redis:
    return redis_asyncio.from_url(str(settings.redis_url), decode_responses=True)


@lru_cache
def get_job_store() -> RenderJobStore:
    return RenderJobStore(create_redis_client(), ttl_seconds=settings.render_job_ttl_seconds)
