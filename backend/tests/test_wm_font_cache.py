import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.config import WM_FONT_MARKER_NAME


class WatermarkFontCacheTests(unittest.TestCase):
    def test_font_change_invalidates_stale_public_thumbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            thumb_dir = Path(tmp)
            stale = thumb_dir / "pub_abc.webp"
            stale.write_bytes(b"tofu")
            (thumb_dir / WM_FONT_MARKER_NAME).write_text("/old/DejaVuSans.ttf", encoding="utf-8")

            with patch.object(main, "THUMB_DIR", thumb_dir), \
                 patch.object(main, "_wm_font_id", return_value="/new/NotoSansCJK.ttc"):
                main._sync_wm_font_cache()
                self.assertFalse(stale.exists())

                stale.write_bytes(b"fresh")
                main._sync_wm_font_cache()
                self.assertTrue(stale.exists())

    def test_wm_version_changes_with_font(self):
        with patch.object(main, "_wm_font_id", return_value="a"):
            v1 = main._wm_version("風嶺拍貼機")
        with patch.object(main, "_wm_font_id", return_value="b"):
            v2 = main._wm_version("風嶺拍貼機")
        self.assertNotEqual(v1, v2)
