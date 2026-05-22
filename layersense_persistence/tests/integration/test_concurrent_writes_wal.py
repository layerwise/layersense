from concurrent.futures import ThreadPoolExecutor

import pytest
from layersense_persistence.config import PersistenceSettings
from layersense_persistence.database import create_engine, get_session, init_db
from layersense_persistence.repositories.projects import ProjectsRepository

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_concurrent_writes_succeed_with_separate_wal_connections(tmp_path) -> None:
    """Allow two separate SQLite connections to commit disjoint writes under WAL."""
    engine = create_engine(PersistenceSettings(db_path=tmp_path / "wal.sqlite"))
    init_db(engine)

    def write_project(name: str) -> str:
        with get_session(engine) as session:
            return ProjectsRepository(session).create(name=name).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(write_project, ["Project A", "Project B"]))

    assert len(set(ids)) == 2
