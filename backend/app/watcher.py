import time
import asyncio
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from app.config import (
    SUPPORTED_IMAGE_FORMATS,
    WATCHER_STABILITY_INTERVAL,
    WATCHER_STABILITY_CHECKS,
    WATCHER_STABILITY_TIMEOUT,
    WS_MESSAGE_TYPE_NEW_INCOMING,
)

logger = logging.getLogger(__name__)


async def _wait_for_stable_file(filepath: Path) -> bool:
    deadline = time.monotonic() + WATCHER_STABILITY_TIMEOUT
    previous_size = None
    stable_checks = 0

    while time.monotonic() < deadline:
        await asyncio.sleep(WATCHER_STABILITY_INTERVAL)
        try:
            current_size = filepath.stat().st_size
        except OSError:
            return False

        if current_size == previous_size:
            stable_checks += 1
            if stable_checks >= WATCHER_STABILITY_CHECKS:
                return True
        else:
            stable_checks = 0
        previous_size = current_size

    return False


class PhotoHandler(FileSystemEventHandler):
    """監聽 incoming 資料夾，偵測到新照片時產生取件碼並透過 WebSocket 通知前端。"""

    def __init__(self, manager, loop: asyncio.AbstractEventLoop, code_assigner=None):
        self.manager = manager
        self.loop = loop
        self.code_assigner = code_assigner  # callable: filename -> code str

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        filepath = Path(event.src_path)
        filename = filepath.name

        if not any(filename.lower().endswith(fmt) for fmt in SUPPORTED_IMAGE_FORMATS):
            return

        logger.info(f"📸 偵測到新照片: {filename}")

        asyncio.run_coroutine_threadsafe(
            self._delayed_broadcast(str(filepath)),
            self.loop,
        )

    async def _delayed_broadcast(self, filename: str) -> None:
        filepath = Path(filename)
        if not await _wait_for_stable_file(filepath):
            logger.warning(f"照片檔案未完成寫入或已消失，略過推播: {filepath.name}")
            return
        try:
            code = self.code_assigner(filepath.name) if self.code_assigner else None
            await self.manager.broadcast({
                "type": WS_MESSAGE_TYPE_NEW_INCOMING,
                "filename": filepath.name,
                "url": f"/static/incoming/{filepath.name}",
                "code": code,
                "timestamp": time.time(),
            })
            if code:
                logger.info(f"🎫 取件碼已指派: {filename} → {code}")
        except Exception as e:
            logger.error(f"WebSocket 廣播失敗: {e}")


def start_watcher(
    incoming_dir: str | Path,
    manager,
    loop: asyncio.AbstractEventLoop,
    code_assigner=None,
) -> Observer:
    """
    啟動資料夾監聽服務。

    Args:
        incoming_dir: 相片來源資料夾
        manager: WebSocket 連接管理器
        loop: FastAPI 的 asyncio event loop
    """
    incoming_dir = Path(incoming_dir)
    event_handler = PhotoHandler(manager, loop, code_assigner=code_assigner)
    observer = Observer()
    observer.schedule(event_handler, path=str(incoming_dir), recursive=False)
    observer.start()
    logger.info(f"📡 資料夾監聽服務已啟動，正在監控: {incoming_dir}")
    return observer
