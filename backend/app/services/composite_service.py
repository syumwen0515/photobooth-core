"""照片 + 模板合成：所有函式皆為同步 CPU 工作，呼叫端需以 run_in_executor 包裝。"""

import io
from typing import Dict, List

from PIL import Image, ImageOps

from app.config import COMPOSITE_JPEG_QUALITY, COMPOSITE_MAX_PHOTO_PIXELS


def decode_photo(image_bytes: bytes) -> Image.Image:
    """以 BytesIO 讀取照片並正規化為 RGB；無效或過大時拋出 ValueError。"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.width * img.height > COMPOSITE_MAX_PHOTO_PIXELS:
            raise ValueError("照片像素過大")
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"無法讀取照片: {e}") from e


def compose(
    template: Image.Image,
    slots: List[Dict[str, int]],
    photos: Dict[int, Image.Image],
) -> Image.Image:
    """將 photos（slot_id → RGB）等比例放大至完整填滿槽位（不變形、不留白，超出部分置中裁切）後貼入，再以模板 Alpha 覆蓋。未提供照片的槽位保持空白。"""
    template = template.convert("RGBA")
    canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
    for slot in slots:
        photo = photos.get(slot["slot_id"])
        if photo is None:
            continue
        fitted = ImageOps.fit(photo, (slot["width"], slot["height"]), Image.LANCZOS)
        canvas.paste(fitted.convert("RGBA"), (slot["x"], slot["y"]))
    canvas.alpha_composite(template)
    return canvas.convert("RGB")


def encode_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=COMPOSITE_JPEG_QUALITY, optimize=True)
    return buf.getvalue()
