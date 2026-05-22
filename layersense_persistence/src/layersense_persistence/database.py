from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, event
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.orm import Session, sessionmaker

from layersense_persistence.config import PersistenceSettings, settings
from layersense_persistence.models import Base


def _sqlite_url(db_path: Path | str) -> str:
    if str(db_path) == ":memory:":
        return "sqlite+pysqlite:///:memory:"
    return f"sqlite+pysqlite:///{Path(db_path)}"


def create_engine(config: PersistenceSettings = settings) -> Engine:
    if config.db_path != Path(":memory:"):
        config.db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = sqlalchemy_create_engine(
        _sqlite_url(config.db_path),
        connect_args={"check_same_thread": False},
        echo=config.sqlite_echo,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


@contextmanager
def get_session(engine: Engine | None = None) -> Iterator[Session]:
    active_engine = engine or create_engine()
    session_factory = sessionmaker(bind=active_engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    active_engine = engine or create_engine()
    Base.metadata.create_all(active_engine)
