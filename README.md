# UI Text Accessibility Reviewer

Group G07 – NLP Mini Project. A web app that evaluates UI labels, buttons and messages for
**clarity, accessibility, reading level and consistency**.

## Run
```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000
pytest                 # run tests
```

## How it works (`analyzer.py`)
| Dimension | Techniques |
|---|---|
| Clarity | Lexicons of jargon / vague actions, passive-voice & double-negative patterns, error codes, length limits per element type, error messages without a remedy |
| Accessibility | WCAG-inspired rules: sensory characteristics, generic link text, device-specific verbs, ALL CAPS, emoji, symbol-only text, user-blaming wording |
| Reading level | Flesch Reading Ease and Flesch-Kincaid grade (own syllable counter; no corpora needed) |
| Consistency | Cross-string checks: term variants (Log in / Sign in), capitalisation style, end punctuation, near-duplicates |

Input: one string per line, optionally prefixed `button | …`, `label | …`, `message | …`.
API: `POST /api/analyze` with `{"text": "...", "default_element": "other"}`.
