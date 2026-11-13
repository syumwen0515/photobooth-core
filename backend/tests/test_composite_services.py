import io
import unittest

from PIL import Image, ImageDraw

from app.services import composite_service, template_service


def _template_png(size=(300, 500), holes=((20, 30, 120, 90), (160, 200, 100, 150))) -> bytes:
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    draw = ImageDraw.Draw(img)
    for x, y, w, h in holes:
        draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TemplateDetectionTests(unittest.TestCase):
    def test_detects_slots_sorted_top_to_bottom(self):
        slots = template_service.detect_transparent_slots(_template_png())
        self.assertEqual(slots, [
            {"slot_id": 1, "x": 20, "y": 30, "width": 120, "height": 90},
            {"slot_id": 2, "x": 160, "y": 200, "width": 100, "height": 150},
        ])

    def test_ignores_tiny_noise_and_keeps_l_shape_as_one_slot(self):
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 109, 59], fill=(0, 0, 0, 0))
        draw.rectangle([10, 60, 59, 159], fill=(0, 0, 0, 0))
        draw.rectangle([150, 150, 154, 154], fill=(0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        slots = template_service.detect_transparent_slots(buf.getvalue())
        self.assertEqual(slots, [{"slot_id": 1, "x": 10, "y": 10, "width": 100, "height": 150}])

    def test_rejects_non_png(self):
        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="JPEG")
        with self.assertRaises(ValueError):
            template_service.detect_transparent_slots(buf.getvalue())


class CompositeTests(unittest.TestCase):
    def test_photo_fills_slot_without_gaps_and_template_overlays(self):
        tpl = template_service.open_template(_template_png())
        slots = template_service.detect_transparent_slots(_template_png())
        photo = Image.new("RGB", (400, 100), (255, 0, 0))
        out = composite_service.compose(tpl, slots, {1: photo})
        self.assertEqual(out.size, (300, 500))
        self.assertEqual(out.getpixel((30, 40)), (255, 0, 0))
        self.assertEqual(out.getpixel((30, 115)), (255, 0, 0))
        self.assertEqual(out.getpixel((5, 5)), (10, 20, 30))
        self.assertEqual(out.getpixel((200, 250)), (255, 255, 255))

    def test_decode_rejects_garbage(self):
        with self.assertRaises(ValueError):
            composite_service.decode_photo(b"not an image")
