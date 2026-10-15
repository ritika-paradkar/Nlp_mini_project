"""Fetch a web page and pull out the UI text it shows, plus page-level accessibility problems.

Uses only the standard library. Only the HTML a server returns is read, so pages that build their
content with JavaScript (single-page apps) will show little text.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
TIMEOUT = 10
MAX_STRINGS = 250
MAX_PARAGRAPHS = 40
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 UITextReviewer/1.0"

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "canvas", "code", "pre"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
MSG_CLASS = re.compile(r"(?:^|[\s_-])(?:error|alert|warning|success|toast|notice|notification|snackbar|invalid|feedback|flash)(?:$|[\s_-])", re.I)
GENERIC_ALT = re.compile(r"^(?:image|img|photo|picture|graphic|icon|logo|banner|untitled|spacer)?[\s_-]*\d*$|\.(?:png|jpe?g|gif|svg|webp)$|^(?:dsc|img|screenshot)[\s_-]*\d+", re.I)


class ScanError(Exception):
    pass


# ---------------------------------------------------------------- safe fetching
# Only genuinely internal ranges are refused. Python's own is_private/is_reserved flags are broader and also
# catch addresses that VPNs, proxies and some DNS setups hand out for ordinary public sites (e.g. 198.18.0.0/15).
BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "::/128", "fc00::/7", "fe80::/10")]


def _check_host(host: str) -> None:
    if os.environ.get("UITR_ALLOW_PRIVATE") == "1":
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ScanError(f"Could not find the website “{host}”. Check the address.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if any(ip in net for net in BLOCKED_NETS):
            raise ScanError(f"“{host}” resolves to an internal network address ({ip}), so it can’t be scanned.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


INSTALL_HINT = "Install it once with:  python -m pip install playwright   then   python -m playwright install chromium"
HIDE_JS = """() => { document.querySelectorAll('script,style,noscript,template').forEach(e => e.remove());
  document.querySelectorAll('body *').forEach(e => { try { if (getComputedStyle(e).display === 'none') e.remove(); } catch (_) {} });
  return document.documentElement.outerHTML; }"""


def _render(url: str | None = None, html: str | None = None, base_url: str = "") -> tuple[str, str]:
    """Open the page in headless Chromium so its JavaScript runs; return (final_url, rendered_html).

    Every network request the page makes is checked, so JavaScript can't be used to reach internal addresses."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ScanError("Reading JavaScript-built pages needs the optional Playwright add-on. " + INSTALL_HINT)

    host_ok: dict[str, bool] = {}

    def route(r):
        u = urllib.parse.urlsplit(r.request.url)
        if u.scheme in ("data", "blob", "about"):
            return r.continue_()
        if u.scheme not in ("http", "https") or r.request.resource_type in ("image", "media", "font"):
            return r.abort()
        if u.hostname not in host_ok:
            try:
                _check_host(u.hostname)
                host_ok[u.hostname] = True
            except ScanError:
                host_ok[u.hostname] = False
        return r.continue_() if host_ok[u.hostname] else r.abort()

    try:
        with sync_playwright() as pw:
            exe = os.environ.get("UITR_CHROMIUM_PATH") or None
            try:
                browser = pw.chromium.launch(executable_path=exe)
            except Exception:
                raise ScanError("The browser used for JavaScript pages isn’t installed. " + INSTALL_HINT)
            try:
                ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, accept_downloads=False,
                                          locale="en-US", service_workers="block")
                page = ctx.new_page()
                page.route("**/*", route)
                page.set_default_timeout(20000)
                if html is not None:
                    page.set_content(html, wait_until="load")
                else:
                    page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass                                    # busy pages never go idle; use what has rendered
                page.wait_for_timeout(1200)
                return page.url if html is None else base_url, page.evaluate(HIDE_JS)
            finally:
                browser.close()
    except ScanError:
        raise
    except Exception as e:
        msg = str(e).splitlines()[0][:160] if str(e) else type(e).__name__
        raise ScanError(f"Could not load the page in the browser ({msg}).")


def normalise_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ScanError("Please enter a website address.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ScanError("Only http:// and https:// addresses can be scanned.")
    return raw


def fetch(url: str) -> tuple[str, str]:
    """Return (final_url, html). Follows redirects manually so every hop is checked."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        _check_host(urllib.parse.urlsplit(url).hostname)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                                                   "Accept-Language": "en"})
        try:
            resp = opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                    raise ScanError("The site redirected to an unsupported address.")
                continue
            raise ScanError(f"The website answered with an error ({e.code}). It may block automated tools.")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            raise ScanError(f"Could not open the website ({getattr(e, 'reason', e)}).")
        with resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower() and "xml" not in ctype.lower():
                raise ScanError(f"That address is not a web page (type: {ctype or 'unknown'}).")
            body = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
            m = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
            enc = (m.group(1).decode() if m and isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
            try:
                return url, body.decode(enc, "replace")
            except LookupError:
                return url, body.decode("utf-8", "replace")
    raise ScanError("The website redirected too many times.")


# ---------------------------------------------------------------- HTML parsing
def _examples(items, filenames=True):
    """Short 'For example: a, b, c (+N more)' text. Long URLs are reduced to their last path segment."""
    out = []
    for x in items:
        x = (x or "").split("?")[0].rstrip("/")
        out.append((x.rsplit("/", 1)[-1] if filenames else x)[:40] or "(unnamed)")
    out = list(dict.fromkeys(out))
    more = len(out) - 3
    return "For example: " + ", ".join(out[:3]) + (f" (+{more} more)" if more > 0 else "") + "."


BLOCKED_TITLE = re.compile(r"unsupported|access denied|forbidden|just a moment|attention required|are you a robot|captcha|blocked|"
                           r"enable javascript|not available|403|security check|please wait", re.I)


class _Collector:
    __slots__ = ("tag", "kind", "where", "parts")

    def __init__(self, tag, kind, where):
        self.tag, self.kind, self.where, self.parts = tag, kind, where, []


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.title = ""
        self.lang = ""
        self.strings: list[tuple[str, str, str]] = []      # (text, element, where)
        self.page_issues: list[dict] = []
        self.stack: list[_Collector] = []
        self.skip = 0
        self.in_title = False
        self.headings: list[int] = []
        self.labels_for: set[str] = set()
        self.inputs: list[dict] = []
        self.label_depth = 0
        self.imgs_no_alt: list[str] = []
        self.link_targets: dict[str, set[str]] = {}
        self.empty_buttons = 0
        self.empty_links: list[str] = []
        self.viewport = ""
        self._seen: set[tuple[str, str]] = set()
        self._paragraphs = 0

    # -- helpers
    def _emit(self, text, element, where):
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text or (element not in ("button", "link") and not re.search(r"[A-Za-z]", text)):
            return
        key = (text.lower(), element)
        if key in self._seen or len(self.strings) >= MAX_STRINGS:
            return
        self._seen.add(key)
        self.strings.append((text, element, where))

    def _issue(self, severity, message, suggestion, rule, detail=""):
        self.page_issues.append({"severity": severity, "message": message, "detail": detail, "suggestion": suggestion, "rule": rule})

    def _push(self, tag, kind, where):
        self.stack.append(_Collector(tag, kind, where))

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "").strip()
        if tag in SKIP_TAGS:
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "meta" and a.get("name", "").lower() == "viewport":
            self.viewport = a.get("content", "")
        if tag == "img":
            if "alt" not in a:
                self.imgs_no_alt.append(a.get("src", "")[:60])
            elif a["alt"].strip():
                self._emit(a["alt"], "alt", f"alt text of image {a.get('src', '')[:40]}")
            for c in self.stack:                         # an image inside a link/button supplies its name
                if a.get("alt", "").strip():
                    c.parts.append(a["alt"])
            return
        if tag == "input":
            t = a.get("type", "text").lower()
            if t == "hidden":
                return
            if t in ("submit", "button", "reset"):
                self._emit(a.get("value", "") or a.get("aria-label", ""), "button", f"<input type={t}>")
                return
            if t not in ("image", "checkbox", "radio"):
                self._register_field(a, t)
            return
        if tag in ("textarea", "select"):
            self._register_field(a, tag)
        if tag in VOID:
            return

        # collectors
        role = a.get("role", "").lower()
        cls = a.get("class", "") + " " + a.get("id", "")
        href = a.get("href", "")
        if tag in ("p", "li") and self.stack and self.stack[-1].tag == tag:
            self._pop(tag)                                   # implicit close of an unclosed <p>/<li>
        if tag == "button" or role == "button":
            self._push(tag, "button", f"<{tag}>")
        elif tag == "a" and href and not href.startswith(("#", "javascript:")):
            self._push(tag, "link", "link → " + urllib.parse.urljoin(self.base, href)[:70])
        elif tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.labels_for.add(a["for"])
            self._push(tag, "label", "<label>")
        elif tag == "legend":
            self._push(tag, "label", "<legend>")
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
            self._push(tag, "heading", f"<{tag}>")
        elif role in ("alert", "status") or (tag in ("div", "span", "p", "li", "section") and MSG_CLASS.search(cls)):
            self._push(tag, "message", f"<{tag}> " + (f"role={role}" if role else "message box"))
        elif tag in ("p", "li") and self._paragraphs < MAX_PARAGRAPHS:
            self._push(tag, "other", f"<{tag}> paragraph text")
        if self.stack and self.stack[-1].tag == tag and a.get("aria-label") and self.stack[-1].kind in ("button", "link", "label"):
            self.stack[-1].parts.append("\0" + a["aria-label"])

    def _register_field(self, a, kind):
        named = bool((a.get("aria-label") or a.get("title") or "").strip() or a.get("aria-labelledby"))
        self.inputs.append({"id": a.get("id", ""), "named": named, "wrapped": self.label_depth > 0, "where": a.get("name") or a.get("id") or kind})
        if a.get("placeholder"):
            self._emit(a["placeholder"], "label", f"placeholder of {kind} field")
        if a.get("aria-label"):
            self._emit(a["aria-label"], "label", f"aria-label of {kind} field")

    def stack_tags(self, *tags):
        return [c.tag for c in self.stack if c.tag in tags]

    def _pop(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                closing = self.stack[i:]
                del self.stack[i:]
                for c in reversed(closing):                  # inner (possibly unclosed) elements finish first
                    self._finish(c)
                return

    def _finish(self, c: _Collector):
        explicit = [p[1:] for p in c.parts if p.startswith("\0")]
        text = re.sub(r"\s+", " ", "".join(p for p in c.parts if not p.startswith("\0"))).strip()
        if c.kind in ("button", "link") and not text:
            text = explicit[0].strip() if explicit else ""
            if not text:
                if c.kind == "button":
                    self.empty_buttons += 1
                else:
                    self.empty_links.append(c.where)
                return
        if c.kind == "link":
            self.link_targets.setdefault(text.lower(), set()).add(c.where.replace("link → ", ""))
        if c.kind == "other":
            if len(text.split()) < 6:
                return
            self._paragraphs += 1
        if c.kind == "label":
            self.label_depth = max(0, self.label_depth - (1 if c.tag == "label" else 0))
        self._emit(text, c.kind, c.where)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and tag not in VOID:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
            return
        if any(c.tag == tag for c in self.stack):
            self._pop(tag)

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
            return
        for c in self.stack:
            c.parts.append(data)

    def close(self):
        super().close()
        while self.stack:
            self._finish(self.stack.pop())

    # -- page-level findings
    def finalise(self):
        if not self.lang:
            self._issue("medium", "The page doesn’t say what language it is in",
                        "Add lang=\"en\" (or the right code) to the <html> tag.", "no-lang",
                        detail="Screen readers may pronounce the text wrongly (WCAG 3.1.1).")
        t = re.sub(r"\s+", " ", self.title).strip()
        if not t:
            self._issue("medium", "The page has no title",
                        "Add a short, unique title describing the page.", "no-title",
                        detail="The title is the first thing a screen reader announces and what browser tabs show.")
        elif t.lower() in {"untitled", "document", "home", "index", "new page", "page"}:
            self._issue("low", f"The page title “{t[:50]}” is too generic", "Use a descriptive title such as “Pricing – Acme”.", "generic-title")
        if self.imgs_no_alt:
            n = len(self.imgs_no_alt)
            self._issue("high", f"{n} image{'s' if n != 1 else ''} {'have' if n != 1 else 'has'} no alt text",
                        "Add a short description to each image, or alt=\"\" if it is only decoration.", "img-no-alt",
                        detail="Screen readers can’t describe these images (WCAG 1.1.1). " + _examples(self.imgs_no_alt))
        unnamed = [i for i in self.inputs if not (i["named"] or i["wrapped"] or (i["id"] and i["id"] in self.labels_for))]
        if unnamed:
            n = len(unnamed)
            self._issue("high", f"{n} form field{'s' if n != 1 else ''} {'have' if n != 1 else 'has'} no label",
                        "Add a visible label to every field. Placeholder text alone disappears while typing.", "input-no-label",
                        detail="Without a label, screen readers can’t say what to enter (WCAG 1.3.1, 3.3.2). " + _examples([i["where"] for i in unnamed], False))
        if self.empty_buttons:
            self._issue("high", f"{self.empty_buttons} button{'s' if self.empty_buttons != 1 else ''} with no name",
                        "Add visible text or an aria-label such as “Close dialog”.", "empty-button",
                        detail="Screen readers announce these as just “button”.")
        if self.empty_links:
            self._issue("high", f"{len(self.empty_links)} link{'s' if len(self.empty_links) != 1 else ''} with no name",
                        "Give each link descriptive text.", "empty-link", detail="Screen readers announce these as just “link”. " + _examples(self.empty_links, False))
        dup = [t for t, hrefs in self.link_targets.items() if len(hrefs) > 1]
        if dup:
            self._issue("medium", "Different pages share the same link text",
                        "Make each link text unique and descriptive.", "dup-link-text",
                        detail="Repeated: " + ", ".join("“" + d[:40] + "”" for d in dup[:4]) + ("…" if len(dup) > 4 else ""))
        h1 = self.headings.count(1)
        if self.headings and h1 == 0:
            self._issue("low", "The page has no main heading (h1)", "Add one h1 that names the page.", "no-h1")
        elif h1 > 1:
            self._issue("low", f"The page has {h1} main headings (h1)", "Use a single h1 and h2–h6 for sub-sections.", "multi-h1")
        skips = [(a, b) for a, b in zip(self.headings, self.headings[1:]) if b > a + 1]
        if skips:
            self._issue("low", "Heading levels are skipped", "Go in order: h1 → h2 → h3.", "heading-skip",
                        detail=f"For example h{skips[0][0]} jumps to h{skips[0][1]}, which breaks the page outline for screen-reader users.")
        if re.search(r"user-scalable\s*=\s*(?:no|0)|maximum-scale\s*=\s*1(?:\.0)?\b", self.viewport, re.I):
            self._issue("medium", "Pinch-zoom is turned off on phones",
                        "Remove user-scalable=no and maximum-scale=1 from the viewport tag.", "no-zoom",
                        detail="Low-vision users can’t enlarge the text (WCAG 1.4.4).")
        for text, element, where in self.strings:
            if element == "alt" and (GENERIC_ALT.search(text.strip()) or re.match(r"^(?:image|picture|photo) of\b", text.strip(), re.I)):
                self._issue("medium", f"Alt text “{text[:40]}” isn’t useful",
                            "Describe what the image shows, without “image of” or a file name.", "bad-alt")
                break


def scan_html(html: str, final_url: str, run_js: bool = False) -> dict:
    """Review HTML we already have (used by the built-in demo pages)."""
    if run_js:
        _, html = _render(html=html, base_url=final_url)
    out = _build(final_url, html)
    out["rendered"] = run_js
    return out


def scan(raw_url: str, js: str = "auto") -> dict:
    """js: 'never' = HTML only, 'auto' = fall back to a real browser when the HTML has little text, 'always' = browser first."""
    url = normalise_url(raw_url)
    if js == "always":
        final_url, html = _render(url)
        out = _build(final_url, html)
        out["rendered"] = True
        return out

    typed_scheme = bool(re.match(r"^[a-z][a-z0-9+.-]*://", (raw_url or "").strip(), re.I))
    static_err = None
    try:
        try:
            final_url, html = fetch(url)
        except ScanError as e:
            if typed_scheme or "Could not open" not in str(e):
                raise
            final_url, html = fetch("http://" + url[len("https://"):])    # no scheme typed and https failed: try plain http
        out = _build(final_url, html)
        out["rendered"] = False
        if js == "never" or len(out["rows"]) >= 8:
            return out
        static_err = out                                    # thin result: maybe a JavaScript-built page
    except ScanError as e:
        if js == "never":
            raise
        static_err = e
    try:                                                    # auto mode: try again in a real browser
        final_url, html = _render(url)
        out = _build(final_url, html)
        out["rendered"] = True
        return out
    except ScanError as render_err:
        if isinstance(static_err, dict):
            if "Playwright" in str(render_err) or "isn’t installed" in str(render_err):
                static_err["warning"] = ("Very little text was found, so this page probably builds its content with JavaScript. "
                                         + str(render_err))
            return static_err
        raise static_err if "Playwright" not in str(render_err) and "isn’t installed" not in str(render_err) else render_err


def _build(final_url: str, html: str) -> dict:
    p = PageParser(final_url)
    p.feed(html)
    p.close()
    p.finalise()
    if not p.strings:
        raise ScanError("No readable interface text was found. The page may build its content with JavaScript (turn on “Run the page’s JavaScript first”) or may block automated tools.")
    title = re.sub(r"\s+", " ", p.title).strip()
    warning = ""
    if BLOCKED_TITLE.search(title) or len(p.strings) < 6:
        warning = ("This website may have blocked our scanner or served a plain fallback page "
                   "(its page title is “" + title[:60] + "”). The results below describe that page, not the real site. "
                   "Try another page, or use the Paste text tab.")
    return {
        "warning": warning,
        "url": final_url,
        "title": re.sub(r"\s+", " ", p.title).strip(),
        "lang": p.lang,
        "rows": p.strings,
        "page_issues": p.page_issues,
        "truncated": len(p.strings) >= MAX_STRINGS,
    }
