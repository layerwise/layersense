from concurrent.futures import ThreadPoolExecutor

import pytest
from layersense_storage.object_store import LocalFSObjectStore

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_concurrent_same_key_writes_leave_complete_object(tmp_path) -> None:
    """Allow identical concurrent writes without exposing partial final content."""
    store = LocalFSObjectStore(tmp_path)
    data = b"same" * 100_000

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.put, "renders/hash/final.mp4", data) for _ in range(2)]
        for future in futures:
            future.result()

    assert store.get("renders/hash/final.mp4") == data


def test_concurrent_different_key_writes_do_not_cross_talk(tmp_path) -> None:
    """Write independent objects concurrently without losing either object."""
    store = LocalFSObjectStore(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(store.put, "renders/a/final.mp4", b"a")
        second = executor.submit(store.put, "renders/b/final.mp4", b"b")
        first.result()
        second.result()

    assert store.get("renders/a/final.mp4") == b"a"
    assert store.get("renders/b/final.mp4") == b"b"
