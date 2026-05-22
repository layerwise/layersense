from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    root: Path = Path("./layersense_artifacts/storage")

    model_config = SettingsConfigDict(env_prefix="LAYERSENSE_STORAGE_")


settings = StorageSettings()
