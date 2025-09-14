import json
from uuid import uuid4

from agents import Agent, Runner
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware

# import JSONResponse
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from layersense.agents.agent import ManimAgentContext, manim_generator
from layersense.api.v1 import api_router as v1_router

app = FastAPI(name="LayerSense")


# Include API routers
app.include_router(v1_router, prefix="/api/v1")

# Add this middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # or ["*"] for all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/info")
async def info():
    """Return information about the API.

    This endpoint simply returns a JSON object with a single key-value pair,
    `"app_name"`, which is a human-readable name for the API.
    """
    return {"app_name": "Layersense: an AI-powered manim backend."}


@app.get("/health")
async def health():
    """Return OK."""
    return PlainTextResponse("OK")
