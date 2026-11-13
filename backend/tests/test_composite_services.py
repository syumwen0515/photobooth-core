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


class MirroredRowsTests(unittest.TestCase):
    HOLES = tuple((x, y, 80, 60) for y in (20, 120, 220, 320) for x in (10, 210))

    def test_two_column_layout_needs_one_photo_per_row(self):
        slots = template_service.detect_transparent_slots(_template_png((300, 420), self.HOLES))
        self.assertEqual(len(slots), 8)
        self.assertTrue(template_service.looks_mirrored(slots))
        groups = template_service.photo_groups({"slots": slots, "mirror_rows": True})
        self.assertEqual([len(g) for g in groups], [2, 2, 2, 2])
        self.assertEqual([g[0]["x"] for g in groups], [10] * 4)
        self.assertEqual(len(template_service.photo_groups({"slots": slots})), 8)

    def test_single_column_is_not_mirrored(self):
        slots = template_service.detect_transparent_slots(_template_png((300, 420), self.HOLES[::2]))
        self.assertFalse(template_service.looks_mirrored(slots))


class EdgeFilterTests(unittest.TestCase):
    def test_edge_connected_transparent_region_is_dropped_when_inner_slots_exist(self):
        img = Image.new("RGBA", (300, 300), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 149, 149], fill=(0, 0, 0, 0))
        draw.rectangle([0, 250, 299, 299], fill=(0, 0, 0, 0))  # 底部整條透明留白
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        slots = template_service.detect_transparent_slots(buf.getvalue())
        self.assertEqual(slots, [{"slot_id": 1, "x": 50, "y": 50, "width": 100, "height": 100}])

    def test_full_bleed_slot_is_kept_when_nothing_else_detected(self):
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
        ImageDraw.Draw(img).rectangle([0, 0, 199, 99], fill=(0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        slots = template_service.detect_transparent_slots(buf.getvalue())
        self.assertEqual(len(slots), 1)
