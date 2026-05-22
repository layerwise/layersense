import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_migrations_upgrade_and_downgrade_round_trip(tmp_path, monkeypatch) -> None:
    """Apply and revert the initial Alembic schema on a fresh SQLite file."""
    db_path = tmp_path / "migrated.sqlite"
    monkeypatch.setenv("LAYERSENSE_DB_PATH", str(db_path))
    config = Config("layersense_persistence/alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) >= {"project", "scene", "frame", "render"}
    assert "refinement_prompt" in {column["name"] for column in inspector.get_columns("render")}

    command.downgrade(config, "base")

    assert inspect(engine).get_table_names() == ["alembic_version"]
