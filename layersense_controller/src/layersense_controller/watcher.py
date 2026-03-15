import logging
import threading
from pathlib import Path

import httpx
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from layersense_controller.config import settings

logger = logging.getLogger(__name__)


class SceneFileHandler(FileSystemEventHandler):
    def _handle(self, path: str) -> None:
        scene_path = Path(path)
        if scene_path.suffix != ".py":
            return

        conversation_id = scene_path.stem.removeprefix("generated_")
        try:
            httpx.post(
                f"http://localhost:{settings.port}/render",
                json={"scene_path": path, "conversation_id": conversation_id},
                timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to enqueue render for %s: %s", path, exc)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path)


def start_watcher() -> threading.Thread:
    settings.scenes_dir.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    observer.schedule(SceneFileHandler(), str(settings.scenes_dir), recursive=False)
    observer.start()
    logger.info("watcher started for %s", settings.scenes_dir)
    return observer
