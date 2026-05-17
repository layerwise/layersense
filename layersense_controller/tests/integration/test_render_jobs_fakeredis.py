import asyncio

import fakeredis
import pytest
from layersense_controller.render_jobs import RenderJobStore

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_create_queued_job_persists_snapshot_and_version() -> None:
    """Persist queued render jobs with their initial snapshot version."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    assert job.status == "queued"
    assert job.version == 1
    assert (await store.get_job("job-1")) == job


@pytest.mark.asyncio
async def test_create_completed_job_persists_succeeded_snapshot() -> None:
    """Persist succeeded render jobs with preview and final URLs."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_completed_job(
        job_id="job-1",
        conversation_id="conv-1",
        preview_url="/artifacts/by-hash/hash/preview",
        final_url="/artifacts/by-hash/hash/final",
    )

    assert job.status == "succeeded"
    assert job.preview_url == "/artifacts/by-hash/hash/preview"
    assert job.final_url == "/artifacts/by-hash/hash/final"


@pytest.mark.asyncio
async def test_update_job_bumps_version_and_publishes_event() -> None:
    """Publish an event when a render job snapshot version changes."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    subscriber = redis.pubsub()
    await subscriber.subscribe("layersense:render-jobs:job-1:events")
    await subscriber.get_message(ignore_subscribe_messages=False, timeout=1.0)

    updated = await store.update_job(job_id="job-1", status="preview_rendering")
    message = await subscriber.get_message(ignore_subscribe_messages=True, timeout=1.0)

    assert updated.version == 2
    assert updated.status == "preview_rendering"
    assert message is not None
    assert message["data"] == "2"


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_current_snapshot_immediately() -> None:
    """Return the current snapshot immediately when it is already newer than requested."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=1)

    assert job is not None
    assert job.version == 2
    assert job.status == "preview_rendering"


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_none_for_missing_job() -> None:
    """Return no snapshot when the requested render job does not exist."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.wait_for_newer_version(job_id="missing-job", after_version=1, wait_seconds=1)

    assert job is None


@pytest.mark.asyncio
async def test_wait_for_newer_version_unblocks_after_publish() -> None:
    """Wake a waiting long-poll read after a newer snapshot is published."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    waiter = asyncio.create_task(
        store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=2)
    )
    await asyncio.sleep(0)
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await asyncio.wait_for(waiter, timeout=2)

    assert job is not None
    assert job.version == 2
    assert job.status == "preview_rendering"
