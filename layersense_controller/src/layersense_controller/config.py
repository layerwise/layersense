from pathlib import Path

from pydantic import AnyUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    storage_root: Path = Path("./layersense_artifacts/storage")
    render_workdir: Path = Path("/tmp/layersense-renders")
    host: str = "0.0.0.0"
    port: int = 8001
    redis_url: AnyUrl = AnyUrl("redis://localhost:6379/0")
    render_job_ttl_seconds: int = 86400
    render_job_wait_seconds: int = 20
    render_job_max_wait_seconds: int = 30

    model_config = {"env_prefix": "LAYERSENSE_"}


settings = Settings()
