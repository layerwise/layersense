from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from layersense_controller.router import router
from layersense_controller.watcher import start_watcher


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    observer = start_watcher()
    try:
        yield
    finally:
        observer.stop()
        observer.join()


app = FastAPI(title="LayerSense Controller", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
