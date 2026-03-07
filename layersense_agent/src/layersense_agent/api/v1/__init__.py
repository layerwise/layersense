from fastapi import APIRouter

from .endpoints import animate_scene

api_router = APIRouter()
api_router.include_router(animate_scene.router, tags=["Scenes"])
