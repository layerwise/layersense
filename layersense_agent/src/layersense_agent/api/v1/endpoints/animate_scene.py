import json
import os
from pathlib import Path
from uuid import uuid4

from agents import Runner, set_tracing_disabled
from fastapi import APIRouter, HTTPException
from layersense_agent.agents.agent import ManimAgentContext, manim_generator, strip_code_fences
from layersense_agent.models.base import AnimationCreatedResponse, AnimationInputs
from layersense_agent.services.scene_normalizer import normalize_scene
from layersense_agent.utils import EXAMPLE_JSON
from layersense_domain.models import RenderOptions

router = APIRouter()
set_tracing_disabled(True)

LAYERSENSE_SCENES_DIR = Path(os.getenv("LAYERSENSE_SCENES_DIR", "./layersense_artifacts/code"))


@router.post("/animation", response_model=AnimationCreatedResponse)
async def create_animation(inputs: AnimationInputs) -> AnimationCreatedResponse:
    """Translate an Excalidraw canvas + prompt into a Manim scene file."""
    conversation_id = str(uuid4())

    context = ManimAgentContext(json_example=EXAMPLE_JSON)
    try:
        normalized_scene = normalize_scene(inputs.scene)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Scene must contain at least one supported element.",
        ) from exc
    render_options = RenderOptions(
        background_color=normalized_scene.appState.viewBackgroundColor,
    )
    scene_json = normalized_scene.model_dump_json(exclude={"appState": {"viewBackgroundColor"}})
    user_prompt = inputs.prompt + "\n" + scene_json

    result = await Runner.run(manim_generator, user_prompt, context=context)
    # TODO: add error handling for failed generation, invalid code, etc.
    scene_code = strip_code_fences(result.final_output)

    LAYERSENSE_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    scene_path = LAYERSENSE_SCENES_DIR / f"generated_{conversation_id}.py"
    scene_path.write_text(scene_code)

    return AnimationCreatedResponse(
        conversation_id=conversation_id,
        scene_path=str(scene_path),
        render_options=render_options,
    )
