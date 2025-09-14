import json
from uuid import uuid4

from agents import Runner
from fastapi import APIRouter
from fastapi.params import Body

from layersense.agents.agent import ManimAgentContext, manim_generator
from layersense.models.base import AnimationInputs, ConversationCreatedResponse
from layersense.models.scene import ExcalidrawScene

router = APIRouter()


@router.post("/animation", response_model=ConversationCreatedResponse)
async def create_animation(inputs: AnimationInputs):
    """Create an animation.

    This endpoint creates an animation based on the given inputs,
    including the prompt and the json data.

    Args:
        inputs (AnimationInputs): The inputs for the animation including the prompt and the json data.

    Returns:
        A JSON object with a single key, `"conversation_id"`, which is a
        unique identifier for the conversation. This id can be used to
        retrieve the animation once it is complete.
    """
    conversation_id = str(uuid4())

    user_prompt = inputs.prompt + "\n" + inputs.json_data

    with open("assets/example_json/example_circle_rectangle_freeform.json") as f:
        json_example = json.load(f)

    context = ManimAgentContext(json_example=json_example)

    __ = await Runner.run(manim_generator, user_prompt, context=context)

    # do I need to debug

    return ConversationCreatedResponse(conversation_id=conversation_id)
