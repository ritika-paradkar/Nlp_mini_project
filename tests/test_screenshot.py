import glob
import io

import pytest

pytest.importorskip("rapidocr")
PIL = pytest.importorskip("PIL.Image")
from PIL import Image, ImageDraw, ImageFont

import screenshot
from app import app

FONTS = glob.glob("/usr/share/fonts/**/LiberationSans-Regular.ttf", recursive=True) + glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True)
needs_font = pytest.mark.skipif(not FONTS, reason="no TrueType font available to draw a test image")


def make_image():
    f = lambda s: ImageFont.truetype(FONTS[0], s)
    im = Image.new("RGB", (1000, 420), "white")
    d = ImageDraw.Draw(im)
    d.text((40, 30), "Welcome back to Acme", font=f(40), fill=(20, 20, 20))
    d.text((40, 110), "Enter your password below to continue", font=f(22), fill=(200, 200, 200))   # low contrast
    d.text((40, 170), "Fine print about terms and conditions", font=f(11), fill=(90, 90, 90))      # tiny
    d.rounded_rectangle((40, 230, 240, 290), 8, fill=(30, 90, 220))
    d.text((95, 247), "SUBMIT", font=f(22), fill="white")
    d.text((40, 340), "Error 0x80070057: invalid parameter", font=f(22), fill=(200, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_contrast_maths():
    assert screenshot.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert screenshot.contrast_ratio((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.05)
    c = screenshot.suggest_colour((200, 200, 200), (255, 255, 255))
    rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    assert screenshot.contrast_ratio(rgb, (255, 255, 255)) >= 4.5


@needs_font
def test_review_finds_text_and_visual_problems():
    r = screenshot.review(make_image(), name="t.png")
    by_text = {i["text"]: i for i in r["items"]}
    low = next(i for t, i in by_text.items() if t.startswith("Enter your password"))
    assert "low-contrast" in {x["rule"] for x in low["issues"]}
    assert any("small-text" in {x["rule"] for x in i["issues"]} for i in r["items"])
    err = next(i for t, i in by_text.items() if t.startswith("Error 0x"))
    assert err["element"] == "message" and "no-remedy" in {x["rule"] for x in err["issues"]}
    assert len(r["boxes"]) == len(r["items"]) and r["page"]["screenshot"]


@needs_font
def test_api_screenshot_and_errors():
    c = app.test_client()
    ok = c.post("/api/screenshot", data={"image": (io.BytesIO(make_image()), "a.png"), "scale": "1"}, content_type="multipart/form-data")
    assert ok.status_code == 200 and ok.json["summary"]["page_score"] is not None
    assert c.post("/api/screenshot", data={}, content_type="multipart/form-data").status_code == 400
    bad = c.post("/api/screenshot", data={"image": (io.BytesIO(b"not an image"), "a.png")}, content_type="multipart/form-data")
    assert bad.status_code == 400 and "image" in bad.json["error"].lower()
    blank = io.BytesIO(); Image.new("RGB", (600, 300), "white").save(blank, "PNG"); blank.seek(0)
    assert c.post("/api/screenshot", data={"image": (blank, "b.png")}, content_type="multipart/form-data").status_code == 400
    assert c.get("/demo/sample-screenshot.png").status_code == 200
