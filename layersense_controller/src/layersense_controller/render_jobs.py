import asyncio
from typing import Literal

from pydantic import BaseModel

RenderJobStatus = Literal[
    "queued",
    "preview_rendering",
    "waiting_for_final",
    "final_rendering",
    "succeeded",
    "failed",
]


class RenderJobSnapshot(BaseModel):
    job_id: str
    conversation_id: str
    status: RenderJobStatus
    version: int
    preview_url: str | None
    final_url: str | None
    error: str | None
    stderr: str | None


class RenderJobStore:
    def __init__(self, redis_client, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def _job_key(self, job_id: str) -> str:
        return f"layersense:render-jobs:{job_id}"

    def _channel(self, job_id: str) -> str:
        return f"layersense:render-jobs:{job_id}:events"

    async def get_job(self, job_id: str) -> RenderJobSnapshot | None:
        raw = await self._redis.get(self._job_key(job_id))
        if raw is None:
            return None
        return RenderJobSnapshot.model_validate_json(raw)

    async def _save(self, snapshot: RenderJobSnapshot) -> RenderJobSnapshot:
        await self._redis.set(
            self._job_key(snapshot.job_id),
            snapshot.model_dump_json(),
            ex=self._ttl_seconds,
        )
        return snapshot

    async def create_queued_job(self, job_id: str, conversation_id: str) -> RenderJobSnapshot:
        return await self._save(
            RenderJobSnapshot(
                job_id=job_id,
                conversation_id=conversation_id,
                status="queued",
                version=1,
                preview_url=None,
                final_url=None,
                error=None,
                stderr=None,
            )
        )

    async def create_completed_job(
        self, job_id: str, conversation_id: str, preview_url: str, final_url: str
    ) -> RenderJobSnapshot:
        return await self._save(
            RenderJobSnapshot(
                job_id=job_id,
                conversation_id=conversation_id,
                status="succeeded",
                version=1,
                preview_url=preview_url,
                final_url=final_url,
                error=None,
                stderr=None,
            )
        )

    async def update_job(
        self, job_id: str, status: RenderJobStatus, **changes: str | None
    ) -> RenderJobSnapshot:
        current = await self.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        next_snapshot = current.model_copy(
            update={
                "status": status,
                "version": current.version + 1,
                "preview_url": changes.get("preview_url", current.preview_url),
                "final_url": changes.get("final_url", current.final_url),
                "error": changes.get("error", current.error),
                "stderr": changes.get("stderr", current.stderr),
            }
        )
        await self._save(next_snapshot)
        await self._redis.publish(self._channel(job_id), str(next_snapshot.version))
        return next_snapshot

    async def wait_for_newer_version(
        self, job_id: str, after_version: int | None, wait_seconds: int
    ) -> RenderJobSnapshot | None:
        current = await self.get_job(job_id)
        if current is None:
            return None
        if after_version is None or current.version > after_version:
            return current

        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(job_id))
        deadline = asyncio.get_running_loop().time() + wait_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    break
            return await self.get_job(job_id)
        finally:
            await pubsub.unsubscribe(self._channel(job_id))
