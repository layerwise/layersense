from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class PersistenceSettings(BaseSettings):
    db_path: Path = Path("./layersense_artifacts/db/layersense.sqlite")
    sqlite_echo: bool = False

    model_config = SettingsConfigDict(env_prefix="LAYERSENSE_")


settings = PersistenceSettings()
