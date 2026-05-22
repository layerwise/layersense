import pytest
from layersense_storage.keys import (
    render_final_key,
    render_log_key,
    render_preview_key,
    render_source_key,
    render_thumbnail_key,
    validate_key,
)

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_render_keys_are_stable_content_addressed_paths() -> None:
    """Derive canonical render object keys from a content hash."""
    assert render_source_key("abc") == "renders/abc/source.py"
    assert render_preview_key("abc") == "renders/abc/preview.mp4"
    assert render_final_key("abc") == "renders/abc/final.mp4"
    assert render_log_key("abc") == "renders/abc/manim.log"
    assert render_thumbnail_key("abc") == "renders/abc/thumbnail.png"


@pytest.mark.parametrize("key", ["", "/absolute", "renders/../escape", "../escape"])
def test_validate_key_rejects_unsafe_paths(key: str) -> None:
    """Reject object keys that could escape the configured storage root."""
    with pytest.raises(ValueError):
        validate_key(key)
