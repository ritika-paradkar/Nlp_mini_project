import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import scanner
from app import app

HTML = """<!doctype html><html><head><title>Untitled</title>
<meta name="viewport" content="width=device-width, user-scalable=no"></head><body>
<h1>Welcome</h1><h3>Our Plans</h3>
<nav><a href="/a">Click here</a> <a href="/b">Click here</a> <a href="/c"><img src="x.png" alt="DSC_1234.jpg"></a></nav>
<img src="hero.png"><img src="ok.png" alt="">
<form><input type="text" placeholder="Enter email"><label for="p">Password</label><input id="p" type="password">
<button>SUBMIT</button><button></button><input type="submit" value="Go"></form>
<div class="error-msg">Error 0x80070057: invalid parameter</div>
<p>In order to proceed you must utilize the configuration parameter that was previously initialized by the administrator.</p>
<script>var x = "ignore me";</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML.encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server(monkeypatch_module=None):
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


@pytest.fixture(autouse=True)
def allow_private(monkeypatch):
    monkeypatch.setenv("UITR_ALLOW_PRIVATE", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")


def test_extracts_text_and_page_issues(server):
    page = scanner.scan(server)
    got = {(t, e) for t, e, _ in page["rows"]}
    assert ("Click here", "link") in got and ("SUBMIT", "button") in got and ("Go", "button") in got
    assert ("Enter email", "label") in got and ("Welcome", "heading") in got
    assert any(e == "message" and "0x80070057" in t for t, e, _ in page["rows"])
    assert not any("ignore me" in t for t, _, _ in page["rows"])
    rules = {i["rule"] for i in page["page_issues"]}
    assert {"no-lang", "generic-title", "img-no-alt", "empty-button", "dup-link-text", "heading-skip", "no-zoom", "bad-alt"} <= rules
    assert "input-no-label" in rules          # the placeholder-only field


def test_private_addresses_blocked(monkeypatch):
    monkeypatch.delenv("UITR_ALLOW_PRIVATE")
    with pytest.raises(scanner.ScanError):
        scanner.scan("http://127.0.0.1:9/")
    with pytest.raises(scanner.ScanError):
        scanner.scan("ftp://example.com")


def test_api_scan(server):
    c = app.test_client()
    r = c.post("/api/scan", json={"url": server})
    assert r.status_code == 200
    d = r.json
    assert d["summary"]["total"] > 5 and d["page"]["page_issues"]
    assert any(i["rewrite"] for i in d["items"])
    assert c.post("/api/scan", json={"url": ""}).status_code == 400


def test_demo_pages_score_low_and_high():
    c = app.test_client()
    bad = c.post("/api/scan", json={"url": "http://localhost:5000/demo/bad-site"}).json
    good = c.post("/api/scan", json={"url": "http://localhost:5000/demo/good-site"}).json
    assert bad["summary"]["overall"] < 50 < 75 < good["summary"]["overall"]
    assert len(bad["page"]["page_issues"]) >= 8 and len(good["page"]["page_issues"]) == 0
    assert c.get("/demo/bad-site").status_code == 200 and c.get("/demo/nope").status_code == 404


def test_host_check_blocks_internal_but_allows_odd_public_ranges(monkeypatch):
    import socket
    monkeypatch.delenv("UITR_ALLOW_PRIVATE", raising=False)

    def fake(ip):
        return lambda host, port: [(socket.AF_INET, 1, 6, "", (ip, 0))]

    for ip in ("10.0.0.5", "192.168.1.1", "127.0.0.1", "169.254.169.254", "172.20.1.1"):
        monkeypatch.setattr(socket, "getaddrinfo", fake(ip))
        with pytest.raises(scanner.ScanError):
            scanner._check_host("x.test")
    for ip in ("198.18.0.5", "100.64.0.9", "23.45.67.89", "240.0.0.1"):    # VPN / carrier / public ranges
        monkeypatch.setattr(socket, "getaddrinfo", fake(ip))
        scanner._check_host("x.test")


import os
needs_browser = pytest.mark.skipif(not os.path.exists(os.environ.get("UITR_CHROMIUM_PATH", "/opt/pw-browsers/chromium")),
                                   reason="headless Chromium not available")


@needs_browser
def test_js_built_page_needs_rendering(monkeypatch):
    monkeypatch.setenv("UITR_CHROMIUM_PATH", os.environ.get("UITR_CHROMIUM_PATH", "/opt/pw-browsers/chromium"))
    c = app.test_client()
    html_only = c.post("/api/scan", json={"url": "http://localhost:5000/demo/js-site", "js": "never"})
    assert html_only.status_code == 400                                  # nothing in the raw HTML
    d = c.post("/api/scan", json={"url": "http://localhost:5000/demo/js-site", "js": "always"}).json
    texts = {i["text"] for i in d["items"]}
    assert d["page"]["rendered"] and "Pixel Chat" in texts and "SEND" in texts
    assert {i["rule"] for i in d["page"]["page_issues"]} >= {"img-no-alt", "empty-button", "input-no-label"}


@needs_browser
def test_render_blocks_internal_requests(monkeypatch):
    monkeypatch.delenv("UITR_ALLOW_PRIVATE", raising=False)
    monkeypatch.setenv("UITR_CHROMIUM_PATH", os.environ.get("UITR_CHROMIUM_PATH", "/opt/pw-browsers/chromium"))
    with pytest.raises(scanner.ScanError):
        scanner.scan("http://127.0.0.1:9/", "always")
