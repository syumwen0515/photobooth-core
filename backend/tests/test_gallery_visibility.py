import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class GalleryVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.incoming_dir = self.root / "incoming"
        self.thumb_dir = self.root / "thumbs"
        self.incoming_dir.mkdir()
        self.thumb_dir.mkdir()
        (self.incoming_dir / "sample.jpg").write_bytes(b"source")
        (self.thumb_dir / "cached.webp").write_bytes(b"thumbnail")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_disabled_gallery_rejects_cached_public_thumbnail(self):
        with patch.object(main, "INCOMING_DIR", self.incoming_dir), \
             patch.object(main, "THUMB_DIR", self.thumb_dir), \
             patch.object(main, "_pub_thumb_path", return_value=self.thumb_dir / "cached.webp"), \
             patch.object(main, "_load_gallery_config", return_value={"enabled": False}):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main.get_gallery_thumb_public("sample.jpg"))

        self.assertEqual(raised.exception.status_code, 404)

    def test_enabled_gallery_serves_cached_public_thumbnail(self):
        with patch.object(main, "INCOMING_DIR", self.incoming_dir), \
             patch.object(main, "THUMB_DIR", self.thumb_dir), \
             patch.object(main, "_pub_thumb_path", return_value=self.thumb_dir / "cached.webp"), \
             patch.object(main, "_load_gallery_config", return_value={"enabled": True}):
            response = asyncio.run(main.get_gallery_thumb_public("sample.jpg"))

        self.assertEqual(response.path, str(self.thumb_dir / "cached.webp"))


if __name__ == "__main__":
    unittest.main()