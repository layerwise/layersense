from io import BytesIO

import pytest
from layersense_storage.errors import ObjectNotFoundError
from layersense_storage.object_store import LocalFSObjectStore

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_put_get_head_and_delete_roundtrip(tmp_path) -> None:
    """Store, inspect, read, and delete bytes through the local object-store API."""
    store = LocalFSObjectStore(tmp_path)

    store.put("renders/hash/source.py", b"source")

    assert store.get("renders/hash/source.py") == b"source"
    info = store.head("renders/hash/source.py")
    assert info is not None
    assert info.size == 6
    assert info.etag == "41cf6794ba4200b839c53531555f0f3998df4cbb01a4d5cb0b94e3ca5e23947d"

    store.delete("renders/hash/source.py")
    assert store.head("renders/hash/source.py") is None
    with pytest.raises(ObjectNotFoundError):
        store.get("renders/hash/source.py")


def test_put_stream_and_open_roundtrip(tmp_path) -> None:
    """Stream larger artifacts without requiring callers to hold destination files directly."""
    store = LocalFSObjectStore(tmp_path)
    data = b"abc" * 500_000

    store.put_stream("renders/hash/final.mp4", BytesIO(data))

    with store.open("renders/hash/final.mp4") as handle:
        assert handle.read() == data


def test_list_prefix_returns_sorted_matching_keys(tmp_path) -> None:
    """List only keys below the requested prefix in deterministic order."""
    store = LocalFSObjectStore(tmp_path)
    store.put("renders/b/final.mp4", b"b")
    store.put("renders/a/final.mp4", b"a")
    store.put("projects/a/source.py", b"p")

    assert list(store.list_prefix("renders/")) == [
        "renders/a/final.mp4",
        "renders/b/final.mp4",
    ]


def test_missing_get_and_open_raise_not_found(tmp_path) -> None:
    """Report missing objects through the storage-specific exception."""
    store = LocalFSObjectStore(tmp_path)

    with pytest.raises(ObjectNotFoundError):
        store.get("renders/missing/final.mp4")
    with pytest.raises(ObjectNotFoundError):
        store.open("renders/missing/final.mp4")
