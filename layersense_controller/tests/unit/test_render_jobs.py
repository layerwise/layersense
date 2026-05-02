import pytest
from layersense_controller.render_jobs import RenderJobSnapshot, RenderJobStore

pytestmark = [pytest.mark.unit, pytest.mark.ai]


class FakePubSub:
    def __init__(self, messages: list[dict[str, str]] | None = None) -> None:
        self._messages = messages or []

    async def subscribe(self, *_args: str) -> None:
        return None

    async def unsubscribe(self, *_args: str) -> None:
        return None

    async def get_message(self, **_kwargs: object) -> dict[str, str] | None:
        if self._messages:
            return self._messages.pop(0)
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self.pubsub_instance = FakePubSub()

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_create_queued_job_persists_snapshot_and_version() -> None:
    """Persist queued render jobs with their initial snapshot version."""
    redis = FakeRedis()
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    assert job == RenderJobSnapshot(
        job_id="job-1",
        conversation_id="conv-1",
        status="queued",
        version=1,
        preview_url=None,
        final_url=None,
        error=None,
        stderr=None,
    )


@pytest.mark.asyncio
async def test_mark_succeeded_publishes_notification() -> None:
    """Publish a version notification when a render job succeeds."""
    redis = FakeRedis()
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    job = await store.update_job(
        job_id="job-1",
        status="succeeded",
        preview_url="/artifacts/by-hash/hash/preview",
        final_url="/artifacts/by-hash/hash/final",
    )

    assert job.version == 2
    assert redis.published == [("layersense:render-jobs:job-1:events", "2")]


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_current_snapshot_after_pubsub_message() -> None:
    """Return updated snapshots after a pubsub version notification arrives."""
    redis = FakeRedis()
    redis.pubsub_instance = FakePubSub(messages=[{"data": "2"}])
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=1)

    assert job.version == 2
    assert job.status == "preview_rendering"
