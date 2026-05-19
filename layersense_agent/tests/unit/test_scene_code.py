from __future__ import annotations

import pytest
from layersense_agent.services.scene_code import apply_background_color_to_scene_code

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_apply_background_color_to_scene_code_injects_background_after_future_imports() -> None:
    """Insert background config after module prologue and before scene imports."""
    source = (
        '"""Example scene."""\n'
        "from __future__ import annotations\n\n"
        "from manim import Scene\n\n"
        "class GeneratedScene(Scene):\n"
        "    def construct(self):\n"
        "        pass\n"
    )

    updated = apply_background_color_to_scene_code(source, "#334455")

    assert updated == (
        '"""Example scene."""\n'
        "from __future__ import annotations\n\n"
        "from manim import config\n"
        'config.background_color = "#334455"\n\n'
        "from manim import Scene\n\n"
        "class GeneratedScene(Scene):\n"
        "    def construct(self):\n"
        "        pass\n"
    )


def test_apply_background_color_to_scene_code_leaves_source_unchanged_without_background() -> None:
    """Skip source rewriting when no explicit background color is requested."""
    source = "from manim import Scene\n"

    assert apply_background_color_to_scene_code(source, None) == source
