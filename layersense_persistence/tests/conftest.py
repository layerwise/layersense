from collections.abc import Iterator

import pytest
from layersense_persistence.config import PersistenceSettings
from layersense_persistence.database import create_engine, get_session, init_db
from sqlalchemy import Engine


@pytest.fixture
def sqlite_engine(tmp_path) -> Engine:
    """Create an isolated SQLite engine with production pragmas enabled."""
    engine = create_engine(PersistenceSettings(db_path=tmp_path / "test.sqlite"))
    init_db(engine)
    return engine


@pytest.fixture
def session(sqlite_engine: Engine) -> Iterator:
    """Yield one transactional repository session."""
    with get_session(sqlite_engine) as active_session:
        yield active_session
