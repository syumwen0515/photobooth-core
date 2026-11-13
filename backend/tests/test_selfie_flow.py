import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # httpx 為測試專用依賴
    TestClient = None
from PIL import Image, ImageDraw

from app import main


def _template_png() -> bytes:
    img = Image.new("RGBA", (300, 400), (10, 20, 30, 255))
    ImageDraw.Draw(img).rectangle([20, 30, 219, 229], fill=(0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


@unittest.skipIf(TestClient is None, "需要 httpx 才能使用 TestClient")
class SelfieFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for d in ("templates", "incoming"):
            (root / d).mkdir()
        self.patches = [
            patch.object(main, "TEMPLATES_DIR", root / "templates"),
            patch.object(main, "TEMPLATES_META_FILE", root / "templates.json"),
            patch.object(main, "SELFIE_CONFIG_FILE", root / "selfie.json"),
            patch.object(main, "INCOMING_DIR", root / "incoming"),
            patch.object(main, "PHOTO_CODES_FILE", root / "codes.json"),
            patch.object(main, "_templates_cache", None),
            patch.object(main, "_selfie_config_cache", None),
            patch.object(main.auth, "validate_session", return_value="admin"),
        ]
        for p in self.patches:
            p.start()
        main._selfie_request_log.clear()
        main._code_request_log.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _upload_template(self):
        res = self.client.post(
            f"{main.API_ADMIN_PREFIX}/templates",
            files={"file": ("tpl.png", _template_png(), "image/png")},
            data={"name": "demo"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_upload_detects_slot_and_rejects_bad_slot_update(self):
        tpl = self._upload_template()
        self.assertEqual(tpl["slots"], [{"slot_id": 1, "x": 20, "y": 30, "width": 200, "height": 200}])
        bad = self.client.post(
            f"{main.API_ADMIN_PREFIX}/templates/{tpl['id']}/slots",
            json={"slots": [{"slot_id": 1, "x": 250, "y": 0, "width": 100, "height": 100}]},
        )
        self.assertEqual(bad.status_code, 400)

    def test_template_id_path_traversal_rejected(self):
        res = self.client.get(f"{main.API_ADMIN_PREFIX}/templates/..%2F..%2Fetc/image")
        self.assertEqual(res.status_code, 404)

    def test_customer_composite_requires_enabled_switch(self):
        tpl = self._upload_template()
        res = self.client.post(
            f"{main.API_CUSTOMER_PREFIX}/composite",
            data={"template_id": tpl["id"]},
            files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
        )
        self.assertEqual(res.status_code, 403)

    def test_customer_composite_creates_pickup_code_and_rate_limits(self):
        tpl = self._upload_template()
        self.client.post(f"{main.API_ADMIN_PREFIX}/selfie-settings", json={"enabled": True})

        def submit():
            return self.client.post(
                f"{main.API_CUSTOMER_PREFIX}/composite",
                data={"template_id": tpl["id"]},
                files=[("files", ("a.jpg", _jpeg(), "image/jpeg"))],
            )

        res = submit()
        self.assertEqual(res.status_code, 200, res.text)
        code = res.json()["code"]
        self.assertEqual(res.json()["download_url"], f"/download/{code}")
        self.assertEqual(len(list(main.INCOMING_DIR.glob("*_selfie*.jpg"))), 1)
        self.assertIsNotNone(main._lookup_code(code))

        wrong_count = self.client.post(
            f"{main.API_CUSTOMER_PREFIX}/composite",
            data={"template_id": tpl["id"]},
            files=[("files", ("a.jpg", _jpeg(), "image/jpeg")), ("files", ("b.jpg", _jpeg(), "image/jpeg"))],
        )
        self.assertEqual(wrong_count.status_code, 400)
        garbage = self.client.post(
            f"{main.API_CUSTOMER_PREFIX}/composite",
            data={"template_id": tpl["id"]},
            files=[("files", ("a.jpg", b"not an image", "image/jpeg"))],
        )
        self.assertEqual(garbage.status_code, 400)

        with patch.object(main, "SELFIE_RATE_LIMIT", 1):
            self.assertEqual(submit().status_code, 429)

    def test_selfie_page_allows_camera_only_on_app_route(self):
        app_res = self.client.get(main.SELFIE_PAGE_ROUTE)
        self.assertIn("camera=(self)", app_res.headers["Permissions-Policy"])
        self.assertNotIn("unsafe-inline", app_res.headers["Content-Security-Policy"])
        other = self.client.get("/login")
        self.assertIn("camera=()", other.headers["Permissions-Policy"])

    def test_mirrored_template_needs_one_photo_per_row(self):
        img = Image.new("RGBA", (300, 400), (10, 20, 30, 255))
        draw = ImageDraw.Draw(img)
        for y in (20, 120, 220):
            for x in (10, 160):
                draw.rectangle([x, y, x + 119, y + 79], fill=(0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        res = self.client.post(
            f"{main.API_ADMIN_PREFIX}/templates",
            files={"file": ("tpl.png", buf.getvalue(), "image/png")},
        )
        tpl = res.json()
        self.assertEqual(len(tpl["slots"]), 6)
        self.assertTrue(tpl["mirror_rows"])
        self.client.post(f"{main.API_ADMIN_PREFIX}/selfie-settings", json={"enabled": True})
        listed = self.client.get(f"{main.API_CUSTOMER_PREFIX}/templates").json()["templates"]
        self.assertEqual(len(listed[0]["slots"]), 3)

        def submit(n):
            return self.client.post(
                f"{main.API_CUSTOMER_PREFIX}/composite",
                data={"template_id": tpl["id"]},
                files=[("files", (f"{i}.jpg", _jpeg(), "image/jpeg")) for i in range(n)],
            )

        self.assertEqual(submit(6).status_code, 400)
        self.assertEqual(submit(3).status_code, 200)
