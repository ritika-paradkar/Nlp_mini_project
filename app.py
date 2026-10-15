"""UI Text Accessibility Reviewer - Flask web app."""
from flask import Flask, jsonify, render_template, request

from analyzer import analyse, parse_input, ELEMENT_TYPES, SEVERITY_PENALTY
import os
import re
from scanner import ScanError, scan, scan_html

app = Flask(__name__)
MAX_LINES = 500
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
        return jsonify(error=str(e)), 400
    result = analyse(page["rows"])
    # Site score = half the average text score, half the page-level checks (which the text scores can't see).
    penalty = sum(SEVERITY_PENALTY[i["severity"]] for i in page["page_issues"])
    summary = result["summary"]
    summary["text_score"] = summary["overall"]
    summary["page_score"] = max(0, 100 - penalty)
    summary["overall"] = round((summary["text_score"] + summary["page_score"]) / 2)
    result["page"] = {k: page[k] for k in ("url", "title", "lang", "page_issues", "truncated", "warning", "rendered")}
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
