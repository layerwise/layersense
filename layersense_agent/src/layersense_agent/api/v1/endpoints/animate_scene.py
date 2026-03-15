import json
import os
from pathlib import Path
from uuid import uuid4

from agents import Runner
from fastapi import APIRouter
from layersense_agent.agents.agent import ManimAgentContext, manim_generator, strip_code_fences
from layersense_agent.models.base import AnimationCreatedResponse, AnimationInputs

router = APIRouter()

SCENES_DIR = Path(os.getenv("SCENES_DIR", "./layersense_scenes"))
EXAMPLE_JSON_PATH = Path("assets/example_json/example_circle_rectangle_freeform.json")


@router.post("/animation", response_model=AnimationCreatedResponse)
async def create_animation(inputs: AnimationInputs) -> AnimationCreatedResponse:
    """Translate an Excalidraw canvas + prompt into a Manim scene file."""
    conversation_id = str(uuid4())

    with open(EXAMPLE_JSON_PATH) as f:
        json_example = json.dumps(json.load(f))

    context = ManimAgentContext(json_example=json_example)
    user_prompt = inputs.prompt + "\n" + inputs.json_data

    result = await Runner.run(manim_generator, user_prompt, context=context)
    scene_code = strip_code_fences(result.final_output)

    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    scene_path = SCENES_DIR / f"generated_{conversation_id}.py"
    scene_path.write_text(scene_code)

    return AnimationCreatedResponse(
        conversation_id=conversation_id,
        scene_path=str(scene_path),
    )
