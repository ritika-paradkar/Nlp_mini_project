# UI Text Accessibility Reviewer

Group G07 – NLP Mini Project. A web app that evaluates UI labels, buttons and messages for
**clarity, accessibility, reading level and consistency**.

## Run
```bash
python -m pip install -r requirements.txt
python -m playwright install chromium     # one-time, ~150 MB, only needed for JavaScript-built sites
python app.py                             # http://localhost:5000
python -m pytest                          # run tests
```
The core app (text review and plain-HTML site scans) needs only Flask. Playwright adds JavaScript-built pages;
rapidocr + onnxruntime + pillow + numpy add screenshot review. Missing add-ons show a helpful message instead of crashing.

## Website scan
Enter a URL on the **Scan a website** tab. `scanner.py` downloads the page (private/internal addresses are blocked), extracts buttons, links, form labels/placeholders, headings, alert messages, alt text and paragraphs, and also reports page-level problems (missing alt text, unlabeled fields, no `lang`, skipped headings, disabled zoom, duplicate link text). Everything is then reviewed by the analyzer below. If a page has little text in its HTML (single-page apps such as ChatGPT), the scanner automatically opens it in headless Chromium so its JavaScript runs; tick “Run the page’s JavaScript first” to always do this. This needs Playwright and its browser (see Run). Every request the browser makes is checked against the same internal-address block. Pages behind a login show only their public part. API: `POST /api/scan` with `{"url": "example.com"}`. For local testing of internal addresses set `UITR_ALLOW_PRIVATE=1`.

Built-in demos (no internet needed): on the Scan tab click “a badly written site” (scores ~40) or “a well written site” (~100). The site score is half the average text score and half the page-level checks.

## Screenshot review
On the **Upload screenshot** tab, drop, paste (Ctrl+V) or choose an image. `screenshot.py` reads the text with OCR (RapidOCR), merges wrapped
lines into paragraphs, guesses what each piece is (button, heading, message…), and measures each text area from its own pixels:
**colour contrast** (WCAG ratio against the local background, with a suggested colour) and **text size**. The words then go through the
same language reviewer as the website scan. Results show the screenshot with clickable boxes around every piece of text.
Contrast and size are estimates, so check surprises by eye. API: `POST /api/screenshot` (multipart `image`, optional `scale` = auto|1|2).

## How it works (`analyzer.py`)
| Dimension | Techniques |
|---|---|
| Clarity | Lexicons of jargon / vague actions, passive-voice & double-negative patterns, error codes, length limits per element type, error messages without a remedy |
| Accessibility | WCAG-inspired rules: sensory characteristics, generic link text, device-specific verbs, ALL CAPS, emoji, symbol-only text, user-blaming wording |
| Reading level | Flesch Reading Ease and Flesch-Kincaid grade (own syllable counter; no corpora needed) |
| Consistency | Cross-string checks: term variants (Log in / Sign in), capitalisation style, end punctuation, near-duplicates |

Input: one string per line, optionally prefixed `button | …`, `label | …`, `message | …`.
API: `POST /api/analyze` with `{"text": "...", "default_element": "other"}`.

## Features
- Per-string scores for clarity, accessibility, reading level and consistency, each with a suggested fix
- **Suggested rewrites** (plain-word swaps, ALL CAPS → sentence case, tidier punctuation) with one-click copy
- Flexible input: `button | Save`, `Error message: ...`, `Placeholder - ...`, or plain lines
- Upload `.txt` / `.csv` files (CSV may be `type,text` rows)
- Filter by severity / category, sort by score
- Export results as CSV or JSON, or print / save as PDF
