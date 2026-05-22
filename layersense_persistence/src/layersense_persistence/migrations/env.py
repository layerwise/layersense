from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from layersense_persistence.config import PersistenceSettings
from layersense_persistence.models import Base

config = context.config

if config.config_file_name is not None:  # pragma: no branch
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    db_path = PersistenceSettings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{db_path}"


def run_migrations_offline() -> None:  # pragma: no cover
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine, event

    connectable = create_engine(
        _database_url(), connect_args={"check_same_thread": False}, pool_pre_ping=True
    )

    @event.listens_for(connectable, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
