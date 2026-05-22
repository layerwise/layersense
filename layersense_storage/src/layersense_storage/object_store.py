from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from layersense_storage.errors import ObjectNotFoundError, ObjectStoreError
from layersense_storage.keys import validate_key


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None
    etag: str


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    def put_stream(
        self, key: str, source: BinaryIO, *, content_type: str | None = None
    ) -> None: ...

    def get(self, key: str) -> bytes: ...

    def open(self, key: str) -> BinaryIO: ...

    def head(self, key: str) -> ObjectInfo | None: ...

    def delete(self, key: str) -> None: ...

    def list_prefix(self, prefix: str) -> Iterator[str]: ...

    def url_for(self, key: str) -> str: ...


class LocalFSObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        del content_type
        self._atomic_write(key, data)

    def put_stream(self, key: str, source: BinaryIO, *, content_type: str | None = None) -> None:
        del content_type
        destination = self._path_for_write(key)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                while chunk := source.read(1024 * 1024):
                    tmp.write(chunk)
            os.replace(tmp_path, destination)
        except OSError as exc:
            raise ObjectStoreError(str(exc)) from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def get(self, key: str) -> bytes:
        path = self._path_for_read(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    def open(self, key: str) -> BinaryIO:
        path = self._path_for_read(key)
        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc

    def head(self, key: str) -> ObjectInfo | None:
        path = self._path_for_read(key)
        if not path.exists() or not path.is_file():
            return None
        data = path.read_bytes()
        return ObjectInfo(size=len(data), content_type=None, etag=hashlib.sha256(data).hexdigest())

    def delete(self, key: str) -> None:
        self._path_for_read(key).unlink(missing_ok=True)

    def list_prefix(self, prefix: str) -> Iterator[str]:
        safe_prefix = validate_key(prefix)
        root = self.root.resolve()
        if not root.exists():
            return iter(())
        keys = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(root).as_posix()
            if key.startswith(safe_prefix):
                keys.append(key)
        return iter(sorted(set(keys)))

    def url_for(self, key: str) -> str:
        return str(self._path_for_read(key))

    def _atomic_write(self, key: str, data: bytes) -> None:
        destination = self._path_for_write(key)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(data)
            os.replace(tmp_path, destination)
        except OSError as exc:
            raise ObjectStoreError(str(exc)) from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _path_for_write(self, key: str) -> Path:
        path = self._path_for_read(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _path_for_read(self, key: str) -> Path:
        safe_key = validate_key(key)
        return self.root.resolve() / safe_key
