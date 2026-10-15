"""UI Text Accessibility Reviewer - Flask web app."""
from flask import Flask, jsonify, render_template, request, send_from_directory

from analyzer import analyse, parse_input, ELEMENT_TYPES, SEVERITY_PENALTY
import os
import re
from scanner import ScanError, scan, scan_html
from screenshot import ScreenshotError, review as review_screenshot

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024        # screenshots up to ~10 MB (plus form overhead)
MAX_LINES = 500
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_CHARS = 200_000


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/analyze")
def api_analyze():
    data = request.get_json(silent=True) or {}
    raw = data.get("text", "")
    default = data.get("default_element", "other")
    if not isinstance(raw, str) or not raw.strip():
        return jsonify(error="Please enter at least one UI string."), 400
    if len(raw) > MAX_CHARS:
        return jsonify(error="Input is too large."), 413
    if default not in ELEMENT_TYPES:
        default = "other"
    rows = parse_input(raw, default)
    if not rows:
        return jsonify(error="No UI strings found."), 400
    if len(rows) > MAX_LINES:
        return jsonify(error=f"Please submit at most {MAX_LINES} strings at a time."), 413
    return jsonify(analyse(rows))


DEMO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo")
def blend_page_score(result, page_issues):
    """Site score = half the average text score, half the page-level checks (which the text scores can't see)."""
    penalty = sum(SEVERITY_PENALTY[i["severity"]] for i in page_issues)
    summary = result["summary"]
    summary["text_score"] = summary["overall"]
    summary["page_score"] = max(0, 100 - penalty)
    summary["overall"] = round((summary["text_score"] + summary["page_score"]) / 2)


DEMOS = ("bad-site", "good-site", "js-site")
DEMO_RE = re.compile(r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/demo/(" + "|".join(DEMOS) + r")/?$", re.I)


@app.get("/demo/<name>")
def demo_page(name):
    if name not in DEMOS:
        return "Not found", 404
    with open(os.path.join(DEMO_DIR, name + ".html"), encoding="utf-8") as f:
        return f.read()


@app.post("/api/scan")
def api_scan():
    data = request.get_json(silent=True) or {}
    try:
        m = DEMO_RE.match((data.get("url") or "").strip())
        if m:                                     # built-in demo pages are read from disk, no network needed
            with open(os.path.join(DEMO_DIR, m.group(1) + ".html"), encoding="utf-8") as f:
                page = scan_html(f.read(), data["url"].strip(), run_js=(m.group(1) == "js-site" and data.get("js") != "never"))
        else:
            mode = data.get("js", "auto")
            page = scan(data.get("url", ""), mode if mode in ("auto", "always", "never") else "auto")
    except ScanError as e:
        empty = not (data.get("url") or "").strip()
        return jsonify(error=str(e), hint=None if empty else "screenshot"), 400
    result = analyse(page["rows"])
    blend_page_score(result, page["page_issues"])
    result["page"] = {k: page[k] for k in ("url", "title", "lang", "page_issues", "truncated", "warning", "rendered")}
    return jsonify(result)


@app.get("/demo/sample-screenshot.png")
def demo_screenshot():
    return send_from_directory(DEMO_DIR, "sample-screenshot.png", mimetype="image/png")


@app.post("/api/screenshot")
def api_screenshot():
    f = request.files.get("image")
    if f is None:
        return jsonify(error="Please choose a screenshot to review."), 400
    data = f.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return jsonify(error="That image is larger than 10 MB."), 413
    scale = {"1": 1.0, "2": 2.0}.get(request.form.get("scale", "auto"))
    try:
        result = review_screenshot(data, scale, name=(f.filename or "screenshot")[:80])
    except ScreenshotError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        app.logger.exception("screenshot review failed")
        return jsonify(error="Something went wrong while reading that image. Try another screenshot."), 500
    blend_page_score(result, result["page"]["page_issues"])
    return jsonify(result)


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="That upload is too large."), 413


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)
