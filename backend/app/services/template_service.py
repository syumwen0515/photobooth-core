"""模板透明槽位偵測：以 Alpha 通道找出可貼照片的矩形區域（Pillow + numpy，不依賴 OpenCV）。"""

import io
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from app.config import (
    TEMPLATE_ALPHA_THRESHOLD,
    TEMPLATE_MAX_PIXELS,
    TEMPLATE_MAX_RUNS,
    TEMPLATE_MIN_SLOT_AREA,
)


def group_rows(slots: List[Dict[str, int]]) -> List[List[Dict[str, int]]]:
    """將垂直方向重疊超過一半的槽位視為同一列，列由上到下、列內由左到右排序。"""
    rows: List[List[Dict[str, int]]] = []
    spans: List[Tuple[int, int]] = []
    for slot in sorted(slots, key=lambda s: (s["y"], s["x"])):
        top, bottom = slot["y"], slot["y"] + slot["height"]
        for i, (r_top, r_bottom) in enumerate(spans):
            overlap = min(bottom, r_bottom) - max(top, r_top)
            if overlap * 2 > min(bottom - top, r_bottom - r_top):
                rows[i].append(slot)
                spans[i] = (min(top, r_top), max(bottom, r_bottom))
                break
        else:
            rows.append([slot])
            spans.append((top, bottom))
    return [sorted(r, key=lambda s: s["x"]) for r in rows]


def looks_mirrored(slots: List[Dict[str, int]]) -> bool:
    """每一列都恰好有 2 個槽位（左右對稱版型）。"""
    rows = group_rows(slots)
    return len(rows) >= 1 and all(len(r) == 2 for r in rows)


def photo_groups(tpl: Dict) -> List[List[Dict[str, int]]]:
    """每個元素代表一張需要的照片及其要填入的所有槽位。"""
    slots = tpl["slots"]
    if tpl.get("mirror_rows"):
        return group_rows(slots)
    return [[s] for s in slots]


def open_template(image_bytes: bytes) -> Image.Image:
    """以 BytesIO 讀取模板並轉為 RGBA；超過像素上限或非有效圖片時拋出 ValueError。"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.format != "PNG":
            raise ValueError("模板必須是 PNG 格式")
        if img.width * img.height > TEMPLATE_MAX_PIXELS:
            raise ValueError("模板像素過大")
        return img.convert("RGBA")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"無法讀取模板圖片: {e}") from e


def _find_roots(parent: List[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def detect_slots_from_alpha(
    alpha: np.ndarray,
    threshold: int = TEMPLATE_ALPHA_THRESHOLD,
    min_area: int = TEMPLATE_MIN_SLOT_AREA,
) -> List[Dict[str, int]]:
    """以逐列連續區段 + union-find（4 連通）標記透明區域並回傳外接矩形。"""
    mask = np.pad(alpha <= threshold, ((0, 0), (1, 1)))
    diff = np.diff(mask.astype(np.int8), axis=1)
    run_starts = np.argwhere(diff == 1)
    run_ends = np.argwhere(diff == -1)
    if len(run_starts) == 0:
        return []
    if len(run_starts) > TEMPLATE_MAX_RUNS:
        raise ValueError("模板透明區域過於複雜，無法自動偵測")

    rows = run_starts[:, 0].tolist()
    starts = run_starts[:, 1].tolist()
    ends = run_ends[:, 1].tolist()
    parent = list(range(len(rows)))

    # 逐列以雙指標合併相鄰列中重疊的區段
    prev_lo = prev_hi = 0
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        cur_lo = i
        while i < n and rows[i] == row:
            i += 1
        cur_hi = i
        if cur_lo > 0 and rows[prev_lo] == row - 1:
            a, b = prev_lo, cur_lo
            while a < prev_hi and b < cur_hi:
                if starts[a] < ends[b] and starts[b] < ends[a]:
                    ra, rb = _find_roots(parent, a), _find_roots(parent, b)
                    if ra != rb:
                        parent[rb] = ra
                if ends[a] < ends[b]:
                    a += 1
                else:
                    b += 1
        prev_lo, prev_hi = cur_lo, cur_hi

    boxes: Dict[int, List[int]] = {}  # root → [x0, y0, x1, y1, area]
    for idx in range(n):
        root = _find_roots(parent, idx)
        x0, x1, y = starts[idx], ends[idx], rows[idx]
        box = boxes.get(root)
        if box is None:
            boxes[root] = [x0, y, x1, y + 1, x1 - x0]
        else:
            box[0] = min(box[0], x0)
            box[1] = min(box[1], y)
            box[2] = max(box[2], x1)
            box[3] = max(box[3], y + 1)
            box[4] += x1 - x0

    height, width = alpha.shape[:2]
    candidates = [b for b in boxes.values() if b[4] >= min_area]
    # 與影像邊緣相連的透明區視為背景留白而非槽位；若全部都碰邊（例如滿版槽位）則保留
    inner = [b for b in candidates if b[0] > 0 and b[1] > 0 and b[2] < width and b[3] < height]
    found: List[Tuple[int, int, int, int]] = [
        (b[0], b[1], b[2] - b[0], b[3] - b[1]) for b in (inner or candidates)
    ]
    found.sort(key=lambda t: (t[1], t[0]))
    return [
        {"slot_id": n + 1, "x": x, "y": y, "width": w, "height": h}
        for n, (x, y, w, h) in enumerate(found)
    ]


def detect_transparent_slots(image_bytes: bytes) -> List[Dict[str, int]]:
    """回傳 [{"slot_id", "x", "y", "width", "height"}]，依由上而下、由左而右排序。"""
    alpha = np.asarray(open_template(image_bytes).getchannel("A"))
    return detect_slots_from_alpha(alpha)


def analyze_template(image_bytes: bytes) -> Tuple[int, int, List[Dict[str, int]]]:
    """一次讀取並回傳 (寬, 高, 槽位)。"""
    img = open_template(image_bytes)
    return img.width, img.height, detect_slots_from_alpha(np.asarray(img.getchannel("A")))
