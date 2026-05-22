import asyncio

import fakeredis
import pytest
from layersense_controller.locks import (
    LockAcquisitionError,
    RenewableLock,
    _matches_token,
    _renew_async,
    redis_lock,
    redis_lock_sync,
)
from redis.exceptions import ResponseError, WatchError

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_async_redis_lock_waits_times_out_and_releases_by_token() -> None:
    """Exercise async Redis lock acquisition, contention, timeout, and token release."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    release = asyncio.Event()
    order: list[str] = []

    async def first_holder() -> None:
        async with redis_lock(redis, key="locks:integration", ttl_ms=1_000, poll_interval_ms=5):
            order.append("first")
            await release.wait()

    async def second_holder() -> None:
        async with redis_lock(redis, key="locks:integration", ttl_ms=1_000, poll_interval_ms=5):
            order.append("second")

    first = asyncio.create_task(first_holder())
    await asyncio.sleep(0)
    second = asyncio.create_task(second_holder())
    await asyncio.sleep(0.02)
    assert order == ["first"]

    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
    assert order == ["first", "second"]

    await redis.set("locks:integration", "foreign", px=1_000)
    with pytest.raises(LockAcquisitionError):
        async with redis_lock(
            redis,
            key="locks:integration",
            ttl_ms=1_000,
            acquire_timeout_ms=20,
            poll_interval_ms=5,
        ):
            pass

    async with redis_lock(redis, key="locks:foreign", ttl_ms=1_000):
        await redis.set("locks:foreign", "foreign", px=1_000)
    assert await redis.get("locks:foreign") == "foreign"

    await redis.set("locks:expired", "foreign", px=10)
    await asyncio.sleep(0.02)
    async with redis_lock(redis, key="locks:expired", ttl_ms=1_000):
        assert await redis.get("locks:expired") != "foreign"


def test_sync_redis_lock_times_out_releases_by_token_and_reraises_eval_errors() -> None:
    """Exercise sync Redis lock acquisition, timeout, token release, and error propagation."""
    redis = fakeredis.FakeRedis(decode_responses=True)

    with redis_lock_sync(redis, key="locks:integration", ttl_ms=1_000):
        assert redis.get("locks:integration") is not None
    assert redis.get("locks:integration") is None

    redis.set("locks:integration", "foreign", px=1_000)
    with pytest.raises(LockAcquisitionError):
        with redis_lock_sync(
            redis,
            key="locks:integration",
            ttl_ms=1_000,
            acquire_timeout_ms=20,
            poll_interval_ms=5,
        ):
            pass

    with redis_lock_sync(redis, key="locks:foreign", ttl_ms=1_000):
        redis.set("locks:foreign", "foreign", px=1_000)
    assert redis.get("locks:foreign") == "foreign"

    def broken_eval(*args: object, **kwargs: object) -> object:
        raise ResponseError("syntax error")

    redis.eval = broken_eval
    with pytest.raises(ResponseError, match="syntax error"):
        with redis_lock_sync(redis, key="locks:error", ttl_ms=1_000):
            pass


@pytest.mark.asyncio
async def test_async_redis_lock_reraises_unexpected_eval_response_error() -> None:
    """Propagate unexpected Redis script errors from async release and renewal."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def broken_eval(*args: object, **kwargs: object) -> object:
        raise ResponseError("syntax error")

    redis.eval = broken_eval

    with pytest.raises(ResponseError, match="syntax error"):
        async with redis_lock(redis, key="locks:error", ttl_ms=1_000):
            pass
    with pytest.raises(ResponseError, match="syntax error"):
        await _renew_async(redis, key="locks:error", token="token", ttl_ms=100)


@pytest.mark.asyncio
async def test_renewable_lock_renews_reports_loss_and_cleans_up() -> None:
    """Exercise renewable lock heartbeat, lock loss, cancellation cleanup, and validation."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async with RenewableLock(redis, key="locks:render", ttl_ms=120, heartbeat_interval_ms=20):
        await asyncio.sleep(0.16)
        assert await redis.get("locks:render") is not None
    assert await redis.get("locks:render") is None

    original_eval = redis.eval
    calls = 0

    async def flaky_eval(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient redis hiccup")
        return await original_eval(*args, **kwargs)

    redis.eval = flaky_eval
    async with RenewableLock(redis, key="locks:flaky", ttl_ms=140, heartbeat_interval_ms=30):
        await asyncio.sleep(0.11)
        assert await redis.get("locks:flaky") is not None
    redis.eval = original_eval

    async with RenewableLock(
        redis, key="locks:lost", ttl_ms=100, heartbeat_interval_ms=20
    ) as lock:
        await redis.set("locks:lost", "foreign", px=1_000)
        await asyncio.sleep(0.05)
        assert lock.lock_lost is True
    assert await redis.get("locks:lost") == "foreign"

    async def locked_body() -> None:
        async with RenewableLock(
            redis, key="locks:cancelled", ttl_ms=100, heartbeat_interval_ms=20
        ):
            await asyncio.sleep(1)

    task = asyncio.create_task(locked_body())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await redis.get("locks:cancelled") is None

    lock = RenewableLock(redis, key="locks:noop", ttl_ms=100, heartbeat_interval_ms=20)
    await lock._heartbeat()
    assert lock.lock_lost is False

    with pytest.raises(ValueError, match="heartbeat_interval_ms"):
        RenewableLock(redis, key="locks:invalid", ttl_ms=100, heartbeat_interval_ms=50)


@pytest.mark.asyncio
async def test_async_watch_fallback_retries_release_and_renew_conflicts(monkeypatch) -> None:
    """Retry async WATCH fallbacks after Redis transaction conflicts."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    original_pipeline = redis.pipeline
    conflicts_remaining = 2

    def conflict_pipeline(*args: object, **kwargs: object) -> object:
        nonlocal conflicts_remaining
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute

        async def execute_with_conflicts(*exec_args: object, **exec_kwargs: object) -> object:
            nonlocal conflicts_remaining
            if conflicts_remaining:
                conflicts_remaining -= 1
                raise WatchError("conflict")
            return await original_execute(*exec_args, **exec_kwargs)

        pipeline.execute = execute_with_conflicts
        return pipeline

    monkeypatch.setattr(redis, "pipeline", conflict_pipeline)

    async with redis_lock(redis, key="locks:release-conflict", ttl_ms=1_000):
        pass
    async with RenewableLock(
        redis,
        key="locks:renew-conflict",
        ttl_ms=140,
        heartbeat_interval_ms=20,
    ):
        await asyncio.sleep(0.05)

    assert await redis.get("locks:release-conflict") is None
    assert await redis.get("locks:renew-conflict") is None


def test_sync_watch_fallback_retries_release_conflicts(monkeypatch) -> None:
    """Retry sync WATCH release fallback after Redis transaction conflicts."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    original_pipeline = redis.pipeline
    conflicts_remaining = 1

    def conflict_pipeline(*args: object, **kwargs: object) -> object:
        nonlocal conflicts_remaining
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute

        def execute_with_conflict(*exec_args: object, **exec_kwargs: object) -> object:
            nonlocal conflicts_remaining
            if conflicts_remaining:
                conflicts_remaining -= 1
                raise WatchError("conflict")
            return original_execute(*exec_args, **exec_kwargs)

        pipeline.execute = execute_with_conflict
        return pipeline

    monkeypatch.setattr(redis, "pipeline", conflict_pipeline)

    with redis_lock_sync(redis, key="locks:release-conflict", ttl_ms=1_000):
        pass

    assert redis.get("locks:release-conflict") is None


def test_matches_token_accepts_bytes_values() -> None:
    """Compare byte-valued Redis responses against string lock tokens."""
    assert _matches_token(b"token", "token") is True
