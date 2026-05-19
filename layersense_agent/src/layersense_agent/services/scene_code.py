from __future__ import annotations

import ast
import json


def apply_background_color_to_scene_code(
    scene_code: str,
    background_color: str | None,
) -> str:
    if background_color is None:
        return scene_code

    background_assignment = f"config.background_color = {json.dumps(background_color)}"
    if background_assignment in scene_code:
        return scene_code

    lines = scene_code.splitlines()
    insertion_index = _insertion_index(scene_code)
    injected_lines = ["from manim import config", background_assignment]

    updated_lines = [
        *lines[:insertion_index],
        *injected_lines,
        "",
        *lines[insertion_index:],
    ]
    return "\n".join(updated_lines).rstrip() + "\n"


def _insertion_index(scene_code: str) -> int:
    lines = scene_code.splitlines()

    try:
        module = ast.parse(scene_code)
    except SyntaxError:
        return 0

    insertion_line = 1
    body = module.body

    if body and _is_module_docstring(body[0]):
        insertion_line = body[0].end_lineno + 1

    while insertion_line <= len(lines):
        current_line = lines[insertion_line - 1].strip()
        if not current_line:
            insertion_line += 1
            continue
        if current_line.startswith("from __future__ import "):
            insertion_line += 1
            continue
        break

    return insertion_line - 1


def _is_module_docstring(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    value = node.value
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str)
    return False
