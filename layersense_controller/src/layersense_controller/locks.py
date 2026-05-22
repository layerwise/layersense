from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import TracebackType
from uuid import uuid4

from redis import Redis as SyncRedis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import ResponseError, WatchError

CACHE_LOCK_TTL_MS = 30_000
CACHE_LOCK_ACQUIRE_TIMEOUT_MS = 10_000
CACHE_LOCK_POLL_INTERVAL_MS = 50
RENDER_LOCK_TTL_MS = 30_000
RENDER_LOCK_HEARTBEAT_INTERVAL_MS = 10_000
RENDER_LOCK_ACQUIRE_TIMEOUT_MS = 5_000

_RELEASE_IF_TOKEN_MATCHES = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""

_RENEW_IF_TOKEN_MATCHES = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""


class LockAcquisitionError(RuntimeError):
    """Raised when a lock cannot be acquired within the acquisition timeout."""


@asynccontextmanager
async def redis_lock(
    redis: AsyncRedis,
    *,
    key: str,
    ttl_ms: int = CACHE_LOCK_TTL_MS,
    acquire_timeout_ms: int = CACHE_LOCK_ACQUIRE_TIMEOUT_MS,
    poll_interval_ms: int = CACHE_LOCK_POLL_INTERVAL_MS,
) -> AsyncIterator[None]:
    """Acquire a Redis-backed mutex with an expiring safety TTL."""
    token = await _acquire_async(
        redis,
        key=key,
        ttl_ms=ttl_ms,
        acquire_timeout_ms=acquire_timeout_ms,
        poll_interval_ms=poll_interval_ms,
    )
    try:
        yield
    finally:
        await _release_async(redis, key=key, token=token)


@contextmanager
def redis_lock_sync(
    redis: SyncRedis,
    *,
    key: str,
    ttl_ms: int = CACHE_LOCK_TTL_MS,
    acquire_timeout_ms: int = CACHE_LOCK_ACQUIRE_TIMEOUT_MS,
    poll_interval_ms: int = CACHE_LOCK_POLL_INTERVAL_MS,
) -> Iterator[None]:
    """Synchronously acquire a Redis-backed mutex with an expiring safety TTL."""
    token = _acquire_sync(
        redis,
        key=key,
        ttl_ms=ttl_ms,
        acquire_timeout_ms=acquire_timeout_ms,
        poll_interval_ms=poll_interval_ms,
    )
    try:
        yield
    finally:
        _release_sync(redis, key=key, token=token)


class RenewableLock:
    """Long-lived async Redis lock with background heartbeat renewal."""

    def __init__(
        self,
        redis: AsyncRedis,
        *,
        key: str,
        ttl_ms: int = RENDER_LOCK_TTL_MS,
        heartbeat_interval_ms: int = RENDER_LOCK_HEARTBEAT_INTERVAL_MS,
        acquire_timeout_ms: int = RENDER_LOCK_ACQUIRE_TIMEOUT_MS,
    ) -> None:
        if heartbeat_interval_ms >= ttl_ms / 2:
            raise ValueError("heartbeat_interval_ms must be less than ttl_ms / 2")

        self._redis = redis
        self._key = key
        self._ttl_ms = ttl_ms
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._acquire_timeout_ms = acquire_timeout_ms
        self._token: str | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.lock_lost = False

    async def __aenter__(self) -> RenewableLock:
        self._token = await _acquire_async(
            self._redis,
            key=self._key,
            ttl_ms=self._ttl_ms,
            acquire_timeout_ms=self._acquire_timeout_ms,
            poll_interval_ms=CACHE_LOCK_POLL_INTERVAL_MS,
        )
        self.lock_lost = False
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._token is not None:
            await _release_async(self._redis, key=self._key, token=self._token)
            self._token = None

    async def _heartbeat(self) -> None:
        if self._token is None:
            return

        while True:
            await asyncio.sleep(self._heartbeat_interval_ms / 1000)
            try:
                renewed = await _renew_async(
                    self._redis,
                    key=self._key,
                    token=self._token,
                    ttl_ms=self._ttl_ms,
                )
            except Exception:
                continue

            if not renewed:
                self.lock_lost = True
                return


async def _acquire_async(
    redis: AsyncRedis,
    *,
    key: str,
    ttl_ms: int,
    acquire_timeout_ms: int,
    poll_interval_ms: int,
) -> str:
    token = uuid4().hex
    deadline = time.monotonic() + acquire_timeout_ms / 1000

    while True:
        acquired = await redis.set(key, token, nx=True, px=ttl_ms)
        if acquired:
            return token
        if time.monotonic() >= deadline:
            raise LockAcquisitionError(f"Could not acquire Redis lock {key!r}")
        await asyncio.sleep(poll_interval_ms / 1000)


def _acquire_sync(
    redis: SyncRedis,
    *,
    key: str,
    ttl_ms: int,
    acquire_timeout_ms: int,
    poll_interval_ms: int,
) -> str:
    token = uuid4().hex
    deadline = time.monotonic() + acquire_timeout_ms / 1000

    while True:
        acquired = redis.set(key, token, nx=True, px=ttl_ms)
        if acquired:
            return token
        if time.monotonic() >= deadline:
            raise LockAcquisitionError(f"Could not acquire Redis lock {key!r}")
        time.sleep(poll_interval_ms / 1000)


async def _release_async(redis: AsyncRedis, *, key: str, token: str) -> None:
    try:
        await redis.eval(_RELEASE_IF_TOKEN_MATCHES, 1, key, token)
    except ResponseError as error:
        if "unknown command" not in str(error).lower():
            raise
        await _release_with_watch_async(redis, key=key, token=token)


def _release_sync(redis: SyncRedis, *, key: str, token: str) -> None:
    try:
        redis.eval(_RELEASE_IF_TOKEN_MATCHES, 1, key, token)
    except ResponseError as error:
        if "unknown command" not in str(error).lower():
            raise
        _release_with_watch_sync(redis, key=key, token=token)


async def _renew_async(redis: AsyncRedis, *, key: str, token: str, ttl_ms: int) -> bool:
    try:
        return bool(await redis.eval(_RENEW_IF_TOKEN_MATCHES, 1, key, token, ttl_ms))
    except ResponseError as error:
        if "unknown command" not in str(error).lower():
            raise
        return await _renew_with_watch_async(redis, key=key, token=token, ttl_ms=ttl_ms)


async def _release_with_watch_async(redis: AsyncRedis, *, key: str, token: str) -> None:
    while True:
        async with redis.pipeline() as pipeline:
            try:
                await pipeline.watch(key)
                if not _matches_token(await pipeline.get(key), token):
                    await pipeline.unwatch()
                    return
                pipeline.multi()
                pipeline.delete(key)
                await pipeline.execute()
                return
            except WatchError:
                continue


def _release_with_watch_sync(redis: SyncRedis, *, key: str, token: str) -> None:
    while True:
        with redis.pipeline() as pipeline:
            try:
                pipeline.watch(key)
                if not _matches_token(pipeline.get(key), token):
                    pipeline.unwatch()
                    return
                pipeline.multi()
                pipeline.delete(key)
                pipeline.execute()
                return
            except WatchError:
                continue


async def _renew_with_watch_async(redis: AsyncRedis, *, key: str, token: str, ttl_ms: int) -> bool:
    while True:
        async with redis.pipeline() as pipeline:
            try:
                await pipeline.watch(key)
                if not _matches_token(await pipeline.get(key), token):
                    await pipeline.unwatch()
                    return False
                pipeline.multi()
                pipeline.pexpire(key, ttl_ms)
                await pipeline.execute()
                return True
            except WatchError:
                continue


def _matches_token(value: object, token: str) -> bool:
    if isinstance(value, bytes):
        return value.decode() == token
    return value == token
