import hashlib
from pathlib import Path

from layersense_controller.config import settings


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preview_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_preview.mp4"


def final_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_final.mp4"


def is_cached(content_hash: str) -> tuple[bool, bool]:
    """Return (preview_exists, final_exists)."""
    return (
        preview_artifact(content_hash).exists(),
        final_artifact(content_hash).exists(),
    )
