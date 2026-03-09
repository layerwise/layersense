from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    scenes_dir: Path = Path("./layersense_scenes")
    artifacts_dir: Path = Path("./layersense_artifacts")
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "LAYERSENSE_"}


settings = Settings()
