import hashlib

from layersense_controller.cache import hash_file
from layersense_controller.cache import is_cached
from layersense_controller.config import settings


def test_hash_file_is_sha256(tmp_path):
    input_file = tmp_path / "scene.py"
    contents = b"print('hello')\n"
    input_file.write_bytes(contents)

    expected = hashlib.sha256(contents).hexdigest()

    assert hash_file(input_file) == expected


def test_is_cached_false_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)

    assert is_cached("abc123") == (False, False)


def test_is_cached_preview_true(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    (tmp_path / "abc123_preview.mp4").write_bytes(b"preview")

    assert is_cached("abc123") == (True, False)
