"""UI Text Accessibility Reviewer - Flask web app."""
from flask import Flask, jsonify, render_template, request

from analyzer import analyse, parse_input, ELEMENT_TYPES
from scanner import ScanError, scan

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


@app.post("/api/scan")
def api_scan():
    data = request.get_json(silent=True) or {}
    try:
        page = scan(data.get("url", ""))
    except ScanError as e:
        return jsonify(error=str(e)), 400
    result = analyse(page["rows"])
    result["page"] = {k: page[k] for k in ("url", "title", "lang", "page_issues", "truncated", "warning")}
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
