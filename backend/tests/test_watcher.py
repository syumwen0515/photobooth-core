import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import watcher


class WatcherFileStabilityTests(unittest.TestCase):
    def test_handler_broadcasts_stable_photo_by_filename(self):
        class RecordingManager:
            def __init__(self):
                self.messages = []

            async def broadcast(self, message):
                self.messages.append(message)

        with tempfile.TemporaryDirectory() as temp_dir:
            photo = Path(temp_dir) / "photo.jpg"
            photo.write_bytes(b"complete")
            manager = RecordingManager()

            async def exercise():
                handler = watcher.PhotoHandler(
                    manager,
                    asyncio.get_running_loop(),
                    code_assigner=lambda filename: f"code-for-{filename}",
                )
                await handler._delayed_broadcast(str(photo))

            with patch.object(watcher, "WATCHER_STABILITY_INTERVAL", 0.01), \
                 patch.object(watcher, "WATCHER_STABILITY_CHECKS", 1), \
                 patch.object(watcher, "WATCHER_STABILITY_TIMEOUT", 0.5):
                asyncio.run(exercise())

        self.assertEqual(len(manager.messages), 1)
        self.assertEqual(manager.messages[0]["filename"], "photo.jpg")
        self.assertEqual(manager.messages[0]["code"], "code-for-photo.jpg")

    def test_waits_until_file_size_stops_changing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            photo = Path(temp_dir) / "photo.jpg"
            photo.write_bytes(b"first")

            async def write_remaining_data():
                await asyncio.sleep(0.025)
                photo.write_bytes(b"first-and-final")

            async def exercise():
                writer = asyncio.create_task(write_remaining_data())
                started = time.monotonic()
                stable = await watcher._wait_for_stable_file(photo)
                elapsed = time.monotonic() - started
                await writer
                return stable, elapsed

            with patch.object(watcher, "WATCHER_STABILITY_INTERVAL", 0.01), \
                 patch.object(watcher, "WATCHER_STABILITY_CHECKS", 2), \
                 patch.object(watcher, "WATCHER_STABILITY_TIMEOUT", 0.5):
                stable, elapsed = asyncio.run(exercise())

        self.assertTrue(stable)
        self.assertGreaterEqual(elapsed, 0.04)

    def test_missing_file_is_not_reported_as_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_photo = Path(temp_dir) / "missing.jpg"
            with patch.object(watcher, "WATCHER_STABILITY_INTERVAL", 0.01), \
                 patch.object(watcher, "WATCHER_STABILITY_CHECKS", 2), \
                 patch.object(watcher, "WATCHER_STABILITY_TIMEOUT", 0.5):
                stable = asyncio.run(watcher._wait_for_stable_file(missing_photo))

        self.assertFalse(stable)


if __name__ == "__main__":
    unittest.main()