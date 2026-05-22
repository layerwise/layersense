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

pytestmark = [pytest.mark.unit, pytest.mark.ai]


@pytest.mark.asyncio
async def test_redis_lock_acquires_and_releases_unset_key() -> None:
    """Acquire and release an async Redis mutex around a short critical section."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async with redis_lock(redis, key="locks:test", ttl_ms=1_000):
        assert await redis.get("locks:test") is not None

    assert await redis.get("locks:test") is None


@pytest.mark.asyncio
async def test_redis_lock_waits_for_held_key_then_proceeds() -> None:
    """Wait for an async lock holder to release before acquiring the key."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    release = asyncio.Event()
    order: list[str] = []

    async def first_holder() -> None:
        async with redis_lock(redis, key="locks:test", ttl_ms=1_000, poll_interval_ms=5):
            order.append("first")
            await release.wait()

    async def second_holder() -> None:
        async with redis_lock(redis, key="locks:test", ttl_ms=1_000, poll_interval_ms=5):
            order.append("second")

    first = asyncio.create_task(first_holder())
    await asyncio.sleep(0)
    second = asyncio.create_task(second_holder())
    await asyncio.sleep(0.02)

    assert order == ["first"]

    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
    assert order == ["first", "second"]


@pytest.mark.asyncio
async def test_redis_lock_raises_when_acquire_timeout_elapses() -> None:
    """Raise clearly when an async Redis lock remains occupied too long."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    await redis.set("locks:test", "foreign", px=1_000)

    with pytest.raises(LockAcquisitionError):
        async with redis_lock(
            redis,
            key="locks:test",
            ttl_ms=1_000,
            acquire_timeout_ms=20,
            poll_interval_ms=5,
        ):
            pass


@pytest.mark.asyncio
async def test_redis_lock_can_reacquire_after_ttl_expiry() -> None:
    """Acquire a lock after a stale holder expires naturally."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    await redis.set("locks:test", "foreign", px=10)
    await asyncio.sleep(0.02)

    async with redis_lock(redis, key="locks:test", ttl_ms=1_000):
        assert await redis.get("locks:test") != "foreign"


@pytest.mark.asyncio
async def test_redis_lock_release_does_not_delete_foreign_holder() -> None:
    """Release by token comparison so an expired holder cannot delete a new owner."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async with redis_lock(redis, key="locks:test", ttl_ms=1_000):
        await redis.set("locks:test", "foreign", px=1_000)

    assert await redis.get("locks:test") == "foreign"


def test_redis_lock_sync_acquires_and_releases_unset_key() -> None:
    """Acquire and release a sync Redis mutex around a short critical section."""
    redis = fakeredis.FakeRedis(decode_responses=True)

    with redis_lock_sync(redis, key="locks:test", ttl_ms=1_000):
        assert redis.get("locks:test") is not None

    assert redis.get("locks:test") is None


def test_redis_lock_sync_raises_when_acquire_timeout_elapses() -> None:
    """Raise clearly when a sync Redis lock remains occupied too long."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    redis.set("locks:test", "foreign", px=1_000)

    with pytest.raises(LockAcquisitionError):
        with redis_lock_sync(
            redis,
            key="locks:test",
            ttl_ms=1_000,
            acquire_timeout_ms=20,
            poll_interval_ms=5,
        ):
            pass


def test_redis_lock_sync_release_does_not_delete_foreign_holder() -> None:
    """Release sync locks by token comparison so foreign holders survive."""
    redis = fakeredis.FakeRedis(decode_responses=True)

    with redis_lock_sync(redis, key="locks:test", ttl_ms=1_000):
        redis.set("locks:test", "foreign", px=1_000)

    assert redis.get("locks:test") == "foreign"


@pytest.mark.asyncio
async def test_redis_lock_reraises_unexpected_eval_response_error() -> None:
    """Propagate non-fakeredis Redis script errors instead of hiding them."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def broken_eval(*args: object, **kwargs: object) -> object:
        raise ResponseError("syntax error")

    redis.eval = broken_eval

    with pytest.raises(ResponseError, match="syntax error"):
        async with redis_lock(redis, key="locks:test", ttl_ms=1_000):
            pass


def test_redis_lock_sync_reraises_unexpected_eval_response_error() -> None:
    """Propagate non-fakeredis Redis script errors from the sync API."""
    redis = fakeredis.FakeRedis(decode_responses=True)

    def broken_eval(*args: object, **kwargs: object) -> object:
        raise ResponseError("syntax error")

    redis.eval = broken_eval

    with pytest.raises(ResponseError, match="syntax error"):
        with redis_lock_sync(redis, key="locks:test", ttl_ms=1_000):
            pass


@pytest.mark.asyncio
async def test_renewable_lock_heartbeat_extends_ttl_and_releases() -> None:
    """Keep a long-lived lock alive past its initial TTL, then release it."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async with RenewableLock(redis, key="locks:render", ttl_ms=120, heartbeat_interval_ms=20):
        await asyncio.sleep(0.16)
        assert await redis.get("locks:render") is not None

    assert await redis.get("locks:render") is None


@pytest.mark.asyncio
async def test_renewable_lock_heartbeat_survives_one_transient_error() -> None:
    """Ignore one heartbeat error and renew on the next heartbeat."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    original_eval = redis.eval
    calls = 0

    async def flaky_eval(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient redis hiccup")
        return await original_eval(*args, **kwargs)

    redis.eval = flaky_eval

    async with RenewableLock(redis, key="locks:render", ttl_ms=140, heartbeat_interval_ms=30):
        await asyncio.sleep(0.11)
        assert await redis.get("locks:render") is not None


@pytest.mark.asyncio
async def test_renewable_lock_reports_lock_lost_when_foreign_holder_replaces_token() -> None:
    """Report lock loss when renewal sees another holder's token."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async with RenewableLock(
        redis,
        key="locks:render",
        ttl_ms=100,
        heartbeat_interval_ms=20,
    ) as lock:
        await redis.set("locks:render", "foreign", px=1_000)
        await asyncio.sleep(0.05)
        assert lock.lock_lost is True

    assert await redis.get("locks:render") == "foreign"


@pytest.mark.asyncio
async def test_renewable_lock_cancels_heartbeat_when_body_is_cancelled() -> None:
    """Clean up the heartbeat task when a lock body exits by cancellation."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def locked_body() -> None:
        async with RenewableLock(redis, key="locks:render", ttl_ms=100, heartbeat_interval_ms=20):
            await asyncio.sleep(1)

    task = asyncio.create_task(locked_body())
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert await redis.get("locks:render") is None


@pytest.mark.asyncio
async def test_renewable_lock_heartbeat_returns_when_not_acquired() -> None:
    """Treat direct heartbeat calls before acquisition as a no-op."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    lock = RenewableLock(redis, key="locks:render", ttl_ms=100, heartbeat_interval_ms=20)

    await lock._heartbeat()

    assert lock.lock_lost is False


@pytest.mark.asyncio
async def test_renewable_lock_reraises_unexpected_renew_response_error() -> None:
    """Propagate non-fakeredis Redis script errors from heartbeat renewal."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def broken_eval(*args: object, **kwargs: object) -> object:
        raise ResponseError("syntax error")

    redis.eval = broken_eval

    with pytest.raises(ResponseError, match="syntax error"):
        await _renew_async(redis, key="locks:render", token="token", ttl_ms=100)


@pytest.mark.asyncio
async def test_async_watch_fallback_retries_after_release_conflict(monkeypatch) -> None:
    """Retry async WATCH release fallback when Redis reports a transaction conflict."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    original_pipeline = redis.pipeline
    conflicts_remaining = 1

    def conflict_once_pipeline(*args: object, **kwargs: object) -> object:
        nonlocal conflicts_remaining
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute

        async def execute_with_one_conflict(*exec_args: object, **exec_kwargs: object) -> object:
            nonlocal conflicts_remaining
            if conflicts_remaining:
                conflicts_remaining -= 1
                raise WatchError("conflict")
            return await original_execute(*exec_args, **exec_kwargs)

        pipeline.execute = execute_with_one_conflict
        return pipeline

    monkeypatch.setattr(redis, "pipeline", conflict_once_pipeline)

    async with redis_lock(redis, key="locks:test", ttl_ms=1_000):
        pass

    assert await redis.get("locks:test") is None


def test_sync_watch_fallback_retries_after_release_conflict(monkeypatch) -> None:
    """Retry sync WATCH release fallback when Redis reports a transaction conflict."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    original_pipeline = redis.pipeline
    conflicts_remaining = 1

    def conflict_once_pipeline(*args: object, **kwargs: object) -> object:
        nonlocal conflicts_remaining
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute

        def execute_with_one_conflict(*exec_args: object, **exec_kwargs: object) -> object:
            nonlocal conflicts_remaining
            if conflicts_remaining:
                conflicts_remaining -= 1
                raise WatchError("conflict")
            return original_execute(*exec_args, **exec_kwargs)

        pipeline.execute = execute_with_one_conflict
        return pipeline

    monkeypatch.setattr(redis, "pipeline", conflict_once_pipeline)

    with redis_lock_sync(redis, key="locks:test", ttl_ms=1_000):
        pass

    assert redis.get("locks:test") is None


@pytest.mark.asyncio
async def test_async_watch_fallback_retries_after_renew_conflict(monkeypatch) -> None:
    """Retry async WATCH renewal fallback when Redis reports a transaction conflict."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    original_pipeline = redis.pipeline
    conflicts_remaining = 1

    def conflict_once_pipeline(*args: object, **kwargs: object) -> object:
        nonlocal conflicts_remaining
        pipeline = original_pipeline(*args, **kwargs)
        original_execute = pipeline.execute

        async def execute_with_one_conflict(*exec_args: object, **exec_kwargs: object) -> object:
            nonlocal conflicts_remaining
            if conflicts_remaining:
                conflicts_remaining -= 1
                raise WatchError("conflict")
            return await original_execute(*exec_args, **exec_kwargs)

        pipeline.execute = execute_with_one_conflict
        return pipeline

    monkeypatch.setattr(redis, "pipeline", conflict_once_pipeline)

    async with RenewableLock(redis, key="locks:render", ttl_ms=140, heartbeat_interval_ms=20):
        await asyncio.sleep(0.05)

    assert await redis.get("locks:render") is None


def test_renewable_lock_rejects_unsafe_heartbeat_interval() -> None:
    """Reject heartbeat intervals that are too close to the lock TTL."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    with pytest.raises(ValueError, match="heartbeat_interval_ms"):
        RenewableLock(redis, key="locks:render", ttl_ms=100, heartbeat_interval_ms=50)


def test_matches_token_accepts_bytes_values() -> None:
    """Compare byte-valued Redis responses against string tokens."""
    assert _matches_token(b"abc", "abc") is True
