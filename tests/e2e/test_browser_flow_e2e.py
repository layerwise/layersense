from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ai]

BROWSER_RENDER_TIMEOUT_MS = 120_000


def _frontend_base() -> str:
    return os.getenv("LAYERSENSE_E2E_FRONTEND_BASE", "http://localhost:3000")


def _controller_base() -> str:
    return os.getenv("LAYERSENSE_E2E_CONTROLLER_BASE", "http://localhost:8001")


def test_browser_generate_flow_reaches_final_video(page: Page) -> None:
    """Drive the real browser generate flow until the final artifact is visible."""
    page.goto(_frontend_base())

    canvas = page.get_by_test_id("canvas-host")
    expect(canvas).to_be_visible()
    page.get_by_test_id("toolbar-rectangle").click(force=True)
    drawing_canvas = page.locator("canvas").first
    box = drawing_canvas.bounding_box()
    assert box is not None, "Excalidraw canvas did not expose a browser bounding box"
    start_x = box["x"] + box["width"] * 0.35
    start_y = box["y"] + box["height"] * 0.35
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 120, start_y + 80)
    page.mouse.up()

    prompt = page.get_by_label("Describe the animation sequence")
    prompt.fill("Generate and render a simple smoke test animation.")

    generate = page.get_by_role("button", name="Generate")
    generate.click()
    expect(generate).to_be_disabled(timeout=5_000)

    video = page.get_by_test_id("render-video")
    expect(video).to_have_attribute(
        "src",
        re.compile(rf"^{re.escape(_controller_base())}/artifacts/by-hash/.+/final$"),
        timeout=BROWSER_RENDER_TIMEOUT_MS,
    )
    expect(page.get_by_text("Final render ready")).to_be_visible()
    expect(page.get_by_text("Error")).not_to_be_visible()
