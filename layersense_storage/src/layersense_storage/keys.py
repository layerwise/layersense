from pathlib import PurePosixPath


def validate_key(key: str) -> str:
    path = PurePosixPath(key)
    if key == "" or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe object key: {key!r}")
    return path.as_posix()


def render_source_key(content_hash: str) -> str:
    return validate_key(f"renders/{content_hash}/source.py")


def render_preview_key(content_hash: str) -> str:
    return validate_key(f"renders/{content_hash}/preview.mp4")


def render_final_key(content_hash: str) -> str:
    return validate_key(f"renders/{content_hash}/final.mp4")


def render_log_key(content_hash: str) -> str:
    return validate_key(f"renders/{content_hash}/manim.log")


def render_thumbnail_key(content_hash: str) -> str:
    return validate_key(f"renders/{content_hash}/thumbnail.png")
