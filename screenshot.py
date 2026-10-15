"""Review a screenshot of a website or app.

Pipeline: OCR finds every piece of text and where it sits -> neighbouring lines of one paragraph are merged ->
each text area is measured (size, colour contrast against its own background) -> the text goes through the same
language reviewer as the website scan.  OCR and contrast values are estimates, so the report says "about".
"""
from __future__ import annotations

import io
import logging
import re
import threading

from analyzer import Issue

MAX_PIXELS = 40_000_000
MAX_SIDE = 3000
MIN_CONF = 0.5
_engine = None
_lock = threading.Lock()

INSTALL_HINT = "Install it once with:  python -m pip install -r requirements.txt"


class ScreenshotError(Exception):
    pass


# ---------------------------------------------------------------- colour maths (WCAG 2.x)
def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    r, g, b = (_lin(float(x)) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(255, x)))) for x in rgb)


def suggest_colour(fg, bg, target=4.5) -> str:
    """Nudge the text colour toward black or white until it reaches the target contrast."""
    end = (0, 0, 0) if luminance(bg) > 0.4 else (255, 255, 255)
    for step in range(0, 51):
        t = step / 50
        c = tuple(f * (1 - t) + e * t for f, e in zip(fg, end))
        if contrast_ratio(c, bg) >= target:
            return to_hex(c)
    return to_hex(end)


# ---------------------------------------------------------------- OCR
def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            try:
                logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                from rapidocr import RapidOCR
            except ImportError:
                raise ScreenshotError("Screenshot review needs the text-recognition add-on. " + INSTALL_HINT)
            _engine = RapidOCR()
    return _engine


def _open_image(data: bytes):
    try:
        from PIL import Image
    except ImportError:
        raise ScreenshotError("Screenshot review needs the Pillow add-on. " + INSTALL_HINT)
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise ScreenshotError("That file isn’t an image we can read. Use a PNG, JPG, WebP, GIF or BMP screenshot.")
    if img.width * img.height > MAX_PIXELS:
        raise ScreenshotError("That image is too large. Please use a screenshot under about 40 megapixels.")
    if img.width < 200 or img.height < 100:
        raise ScreenshotError("That image is too small to read text from. Use a larger screenshot.")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg
    return img.convert("RGB")


# ---------------------------------------------------------------- layout helpers
class Region:
    __slots__ = ("text", "x0", "y0", "x1", "y1", "n_lines", "conf")

    def __init__(self, text, x0, y0, x1, y1, conf):
        self.text, self.x0, self.y0, self.x1, self.y1, self.conf, self.n_lines = text, x0, y0, x1, y1, conf, 1

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def words(self):
        return len(self.text.split())


def _merge_wrapped_lines(regions: list[Region]) -> list[Region]:
    """Join the lines of one wrapped paragraph so sentences are analysed whole."""
    regions.sort(key=lambda r: (round(r.y0 / max(r.h, 1)), r.x0))
    out: list[Region] = []
    for r in sorted(regions, key=lambda r: (r.y0, r.x0)):
        prev = out[-1] if out else None
        if (prev and prev.words >= 5 and not re.search(r"[.!?:;]\s*$", prev.text)
                and abs(prev.x0 - r.x0) <= 0.6 * prev.h
                and -0.5 * prev.h <= r.y0 - prev.y1 <= 0.9 * prev.h
                and 0.7 <= r.h / max(prev.h, 1) <= 1.4):
            prev.text += " " + r.text
            prev.y1, prev.x1 = r.y1, max(prev.x1, r.x1)
            prev.n_lines += 1
            continue
        out.append(r)
    return out


def _measure(arr, region: Region):
    """Estimate (text_rgb, background_rgb, ink_height_px) of a text area from its own pixels."""
    import numpy as np
    H, W = arr.shape[:2]
    x0, x1 = max(0, int(region.x0)), min(W, int(region.x1) + 1)
    y0, y1 = max(0, int(region.y0)), min(H, int(region.y1) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    pad = max(3, int(region.h * 0.3))
    px0, px1, py0, py1 = max(0, x0 - pad), min(W, x1 + pad), max(0, y0 - pad), min(H, y1 + pad)
    mask = np.ones((py1 - py0, px1 - px0), dtype=bool)
    mask[y0 - py0:y1 - py0, x0 - px0:x1 - px0] = False
    ring = arr[py0:py1, px0:px1][mask]
    block = arr[y0:y1, x0:x1]
    crop = block.reshape(-1, 3)
    pool = ring if len(ring) >= 20 else crop
    bg = np.median(pool, axis=0)
    dist = np.linalg.norm(block.astype(float) - bg, axis=2)
    top = float(dist.max())
    if top < 25:                                           # nothing stands out from the background
        return tuple(bg), tuple(bg), None
    flat = dist.reshape(-1)
    k = max(5, int(len(flat) * 0.03))                      # thin strokes are anti-aliased, so trust only the strongest pixels
    idx = np.argpartition(flat, -k)[-k:]
    fg = crop[idx].mean(axis=0)
    rows = np.where((dist > 0.45 * top).any(axis=1))[0]    # rows that really contain ink
    ink = int(rows[-1] - rows[0] + 1) if len(rows) else None
    return tuple(fg), tuple(bg), ink


def _font_px(text: str, ink: int | None, box_h: float, n_lines: int) -> float:
    """Approximate CSS font size. Single lines use the ink height (more exact than the padded OCR box)."""
    if ink and n_lines == 1:
        desc = bool(re.search(r"[gjpqy,;()]", text))
        asc = bool(re.search(r"[A-Zbdfhklt0-9]", text))
        em = ink / (0.95 if desc and asc else 0.72 if asc else 0.5 if desc else 0.5)
        return em
    return 0.8 * box_h / max(n_lines, 1)


def _guess_element(r: Region, own_bg, page_bg, eff_h: float) -> str:
    text = r.text.strip()
    distinct = own_bg is not None and sum(abs(a - b) for a, b in zip(own_bg, page_bg)) > 90
    if distinct and 1 <= r.words <= 4 and r.n_lines == 1 and not re.search(r"[.!?]$", text):
        return "button"
    if text.endswith(":") and r.words <= 5:
        return "label"
    if re.search(r"\b(?:error|failed|invalid|couldn’t|couldn't|cannot|can’t|can't|something went wrong|unable|warning)\b", text, re.I) and r.words >= 3:
        return "message"
    if eff_h >= 22 and r.words <= 12 and r.n_lines == 1:
        return "heading"
    return "other"


# ---------------------------------------------------------------- main entry
def review(data: bytes, scale: float | None = None, name: str = "screenshot") -> dict:
    import numpy as np

    from analyzer import analyse

    img = _open_image(data)
    W0, H0 = img.size
    k = 1.0
    if max(W0, H0) > MAX_SIDE:
        k = MAX_SIDE / max(W0, H0)
        img = img.resize((int(W0 * k), int(H0 * k)))
    arr = np.asarray(img)
    if scale is None:
        scale = 2.0 if W0 >= 2200 else 1.0                 # very wide screenshots are usually retina / 2x

    out = _get_engine()(np.ascontiguousarray(arr[:, :, ::-1]))      # the OCR engine expects BGR (OpenCV) order
    if out is None or out.txts is None or len(out.txts) == 0:
        raise ScreenshotError("No text could be read from that image. Try a sharper, larger screenshot of the page.")

    regions = []
    for box, text, conf in zip(out.boxes, out.txts, out.scores):
        text = re.sub(r"\s+", " ", str(text)).strip()
        if conf < MIN_CONF or not re.search(r"[A-Za-z0-9]", text):
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        regions.append(Region(text, float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), float(conf)))
    regions = _merge_wrapped_lines(regions)
    if not regions:
        raise ScreenshotError("No clear text could be read from that image. Try a sharper, larger screenshot.")

    page_bg = tuple(np.median(arr[:: max(1, arr.shape[0] // 200), :: max(1, arr.shape[1] // 200)].reshape(-1, 3), axis=0))

    rows, boxes = [], []
    low_contrast, small_text = [], []
    for idx, r in enumerate(regions, 1):
        m = _measure(arr, r)
        eff_h = _font_px(r.text, m[2] if m else None, r.h, r.n_lines) / k / scale      # ≈ CSS font px
        extra: list[Issue] = []
        where = [f"screenshot · line {idx}"]
        own_bg = None
        if m:
            fg, own_bg, _ink = m
            ratio = float(contrast_ratio(fg, own_bg))
            where.append(f"contrast ≈ {ratio:.1f}:1")
            large = eff_h >= 24
            need = 3.0 if large else 4.5
            if ratio < need:
                sev = "high" if ratio < 3.0 else "medium"
                sug = suggest_colour(fg, own_bg, need)
                extra.append(Issue("accessibility", sev,
                                   f"Low colour contrast: about {ratio:.1f}:1 (WCAG asks for {need:g}:1 for {'large' if large else 'normal'} text).",
                                   f"Make the text darker or the background lighter. For example, use {sug} on {to_hex(own_bg)}.", "low-contrast"))
                low_contrast.append((idx, r.text, ratio))
        if eff_h < 12:
            sev = "medium" if eff_h < 10 else "low"
            extra.append(Issue("accessibility", sev, f"Very small text (about {eff_h:.0f} px).",
                               "Use at least 14–16 px for body text so people with low vision can read it.", "small-text"))
            small_text.append((idx, r.text, eff_h))
        where.append(f"text ≈ {eff_h:.0f}px")
        element = _guess_element(r, own_bg, page_bg, eff_h)
        rows.append((r.text, element, " · ".join(where), extra))
        boxes.append({"id": idx, "x": round(r.x0 / k / W0 * 100, 2), "y": round(r.y0 / k / H0 * 100, 2),
                      "w": round((r.x1 - r.x0) / k / W0 * 100, 2), "h": round((r.y1 - r.y0) / k / H0 * 100, 2)})

    result = analyse(rows)

    page_issues = []

    def ex(items):
        names = [f"“{t[:30]}{'…' if len(t) > 30 else ''}”" for _, t, _ in items[:3]]
        return "For example: " + ", ".join(names) + (f" (+{len(items) - 3} more)" if len(items) > 3 else "") + "."

    if low_contrast:
        n = len(low_contrast)
        worst = min(r for _, _, r in low_contrast)
        page_issues.append({"severity": "high" if worst < 3 else "medium", "message": f"{n} piece{'s' if n != 1 else ''} of text {'have' if n != 1 else 'has'} low colour contrast",
                            "detail": f"Hard to read for people with low vision or in bright light (WCAG 1.4.3). The weakest is about {worst:.1f}:1. " + ex(low_contrast),
                            "suggestion": "Raise the contrast to at least 4.5:1 for normal text and 3:1 for large text.", "rule": "low-contrast"})
    if small_text:
        n = len(small_text)
        page_issues.append({"severity": "medium" if any(h < 10 for _, _, h in small_text) else "low", "message": f"{n} piece{'s' if n != 1 else ''} of text {'are' if n != 1 else 'is'} very small",
                            "detail": "Small text is hard to read and to tap on phones. " + ex(small_text),
                            "suggestion": "Use at least 14–16 px for body text.", "rule": "small-text"})
    if len(rows) < 5:
        page_issues.append({"severity": "low", "message": "Only a little text was found", "detail": "The screenshot may be too small or blurry, or mostly images.",
                            "suggestion": "Use a sharper, larger screenshot of the whole screen.", "rule": "little-text"})

    result["boxes"] = boxes
    result["image"] = {"width": W0, "height": H0, "scale": scale}
    result["page"] = {"url": name, "title": "Screenshot review", "lang": "", "page_issues": page_issues, "truncated": False,
                      "rendered": False, "screenshot": True,
                      "warning": "Text and colours in a screenshot are measured by software, so values are estimates. Check anything surprising by eye."}
    return result
