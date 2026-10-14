"""Rule-based NLP engine for the UI Text Accessibility Reviewer.

Each UI string is checked on four dimensions:
  * clarity       - vague, jargon-heavy, passive or overly long text
  * accessibility - text that breaks down for screen-reader / cognitive / low-vision users
  * reading level - Flesch Reading Ease and Flesch-Kincaid grade
  * consistency   - terminology, capitalisation and punctuation across the whole set

No external model or corpus download is needed, so the app runs offline.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict

ELEMENT_TYPES = ("button", "label", "message", "other")

WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*")

# ---------------------------------------------------------------- lexicons
JARGON = {
    "authenticate": "sign in", "authentication": "sign-in", "invalid": "not valid / incorrect",
    "terminate": "end / stop", "utilize": "use", "initiate": "start", "execute": "run",
    "parameter": "setting", "parameters": "settings", "configuration": "settings",
    "credentials": "username and password", "payload": "data", "exception": "error",
    "instantiate": "create", "persist": "save", "malformed": "incorrect", "null": "empty",
    "undefined": "unknown", "fatal": "serious", "unauthorized": "not allowed",
    "unauthorised": "not allowed", "deprecated": "no longer supported", "validation": "check",
    "legacy": "old", "proceed": "continue", "terminated": "ended", "failure": "problem",
    "cannot": "can't", "prohibited": "not allowed", "insufficient": "not enough",
    "functionality": "feature", "module": "section", "dismiss": "close", "navigate": "go",
}

VAGUE_ACTIONS = {
    "ok", "okay", "submit", "yes", "no", "go", "done", "click", "continue", "next",
    "proceed", "enter", "send", "action", "process",
}
GENERIC_LINKS = {"click here", "here", "read more", "learn more", "more", "link", "this link", "tap here"}

SENSORY = re.compile(
    r"\b(?:red|green|blue|yellow|orange|purple|pink|grey|gray)\s+(?:button|icon|link|text|box|field|area|bar)\b"
    r"|\b(?:left|right|above|below|top|bottom)(?:-hand)?\s+(?:side|corner|of the (?:page|screen))\b"
    r"|\b(?:round|square|circular|triangular)\s+(?:button|icon)\b"
    r"|\b(?:see|look at|in) the (?:left|right|above|below)\b"
    r"|\b(?:listen for|hear the)\b",
    re.I,
)
DEVICE_SPECIFIC = re.compile(r"\b(?:click|double-click|right-click|hover|swipe|tap|press)\b", re.I)
NEGATIVES = {"not", "no", "never", "cannot", "can't", "won't", "isn't", "aren't", "don't",
             "doesn't", "didn't", "unable", "without", "fail", "failed", "unless"}
BLAME = re.compile(r"\byou (?:failed|forgot|did not|didn't|must have|entered (?:an? )?(?:wrong|invalid|illegal))\b"
                   r"|\b(?:illegal|your (?:mistake|fault)|bad input)\b", re.I)
ERROR_CODE = re.compile(r"\b(?:error\s*(?:code)?\s*[:#]?\s*\d{2,}|0x[0-9a-f]{3,}|[A-Z]{2,}_[A-Z_]{2,}|HTTP\s*\d{3})\b", re.I)
HELPING = re.compile(r"\b(?:try|please|check|make sure|use|enter|select|choose|contact|retry|again|go to|"
                     r"update|add|change|reload|refresh|wait)\b", re.I)
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(?:\w+ed|written|made|given|taken|shown|"
                     r"seen|done|sent|found|set|lost|built|kept|chosen|known|broken|frozen|hidden)\b", re.I)
FILLER = re.compile(r"\b(?:please note that|in order to|at this point in time|due to the fact that|"
                    r"it is important to note|kindly)\b", re.I)
ABBREV = {"info", "msg", "pwd", "usr", "cfg", "config", "auth", "admin", "approx", "misc", "tmp", "temp", "acct", "addr"}

AMBIGUOUS_PAIRS = [
    {"log in", "login", "sign in", "signin", "log on"},
    {"log out", "logout", "sign out", "signout", "log off"},
    {"sign up", "signup", "register", "create account", "join"},
    {"delete", "remove", "erase", "discard", "trash"},
    {"cancel", "abort", "dismiss", "close", "exit"},
    {"settings", "preferences", "options", "configuration"},
    {"e-mail", "email"},
    {"username", "user name", "user id", "login id"},
    {"password", "passcode", "pass word", "pwd"},
    {"submit", "send", "confirm", "apply"},
    {"edit", "modify", "change", "update"},
    {"help", "support", "assistance"},
]

SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with", "from", "into", "vs"}

# ---------------------------------------------------------------- data
@dataclass
class Issue:
    category: str          # clarity | accessibility | consistency | reading
    severity: str          # high | medium | low
    message: str
    suggestion: str = ""
    rule: str = ""


@dataclass
class ItemResult:
    id: int
    text: str
    element: str
    word_count: int
    reading_ease: float | None
    grade: float | None
    reading_label: str
    scores: dict = field(default_factory=dict)
    score: int = 100
    issues: list = field(default_factory=list)


# ---------------------------------------------------------------- text utils
def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def count_syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.findall(text) if WORD_RE.search(s)]


def readability(text: str):
    ws = words(text)
    if not ws:
        return None, None
    n_sent = max(1, len(sentences(text)))
    syll = sum(count_syllables(w) for w in ws)
    wps = len(ws) / n_sent
    spw = syll / len(ws)
    ease = 206.835 - 1.015 * wps - 84.6 * spw
    grade = 0.39 * wps + 11.8 * spw - 15.59
    return round(max(0.0, min(100.0, ease)), 1), round(max(0.0, grade), 1)


def reading_label(ease: float | None) -> str:
    if ease is None:
        return "n/a"
    for limit, label in ((90, "Very easy"), (80, "Easy"), (70, "Fairly easy"), (60, "Plain English"),
                         (50, "Fairly difficult"), (30, "Difficult")):
        if ease >= limit:
            return label
    return "Very difficult"


def case_style(text: str) -> str:
    ws = [w for w in text.split() if re.search(r"[A-Za-z]", w)]
    if not ws:
        return "none"
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters.isupper() and len(letters) > 1:
        return "upper"
    if letters.islower():
        return "lower"
    if len(ws) == 1:
        return "single"
    rest = ws[1:]
    caps = [w for w in rest if w[0].isupper()]
    significant = [w for w in rest if w.lower().strip(".,!?:;") not in SMALL_WORDS]
    if significant and all(w[0].isupper() for w in significant) and ws[0][0].isupper():
        return "title"
    if not caps:
        return "sentence"
    return "mixed"


def normalise(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower().replace("-", " ")).strip()


# ---------------------------------------------------------------- per-item rules
def check_item(text: str, element: str) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda *a, **k: issues.append(Issue(*a, **k))
    ws = words(text)
    lw = [w.lower() for w in ws]
    n = len(ws)
    low = text.lower().strip()
    norm = normalise(text)

    if n == 0:
        add("clarity", "high", "Text contains no readable words.", "Use a short phrase that describes the action or content.", "empty-text")
        return issues

    # ---- clarity
    if low.strip(" .!") in GENERIC_LINKS or norm in GENERIC_LINKS:
        add("accessibility", "high", f"“{text}” is meaningless out of context — screen-reader users often list links/buttons on their own.",
            "Describe the destination or result, e.g. “View billing history”.", "generic-link")
    elif element == "button" and norm in VAGUE_ACTIONS:
        add("clarity", "medium", f"“{text}” is a vague button label that doesn’t say what will happen.",
            "Use verb + object, e.g. “Save changes”, “Send message”.", "vague-button")

    jargon = sorted({w for w in lw if w in JARGON})
    if jargon:
        tips = ", ".join(f"“{w}” → “{JARGON[w]}”" for w in jargon)
        add("clarity", "medium", f"Technical or formal wording: {', '.join(jargon)}.", f"Prefer plain words: {tips}.", "jargon")

    abbr = sorted({w for w in lw if w in ABBREV})
    if abbr:
        add("clarity", "low", f"Abbreviation(s) may be unclear: {', '.join(abbr)}.", "Spell the word out in full.", "abbreviation")

    if ERROR_CODE.search(text):
        add("clarity", "high" if element == "message" else "medium", "Contains an internal error code or system identifier.",
            "Show a human-readable explanation; put codes in a ‘Details’ section.", "error-code")

    if FILLER.search(text):
        add("clarity", "low", "Wordy filler phrase.", "Cut it: “in order to” → “to”, “please note that” → (remove).", "filler")

    if element in ("message", "other") and PASSIVE.search(text):
        add("clarity", "low", "Passive voice hides who or what acts.", "Rewrite actively, e.g. “We couldn’t save your file”.", "passive")

    neg = [w for w in lw if w in NEGATIVES or w.startswith("un") and w in {"unable", "unless"}]
    if len(neg) >= 2:
        add("clarity", "medium", "Multiple negatives make the sentence hard to parse.", "State it positively: “Enter a valid email”.", "double-negative")

    if element == "button" and n > 4:
        add("clarity", "medium", f"Button label is {n} words long.", "Keep buttons to 1–3 words.", "long-button")
    elif element == "label" and n > 5:
        add("clarity", "low", f"Field label is {n} words long.", "Shorten the label; move extra detail into helper text.", "long-label")
    elif element == "message" and n > 30:
        add("clarity", "medium", f"Message is {n} words long.", "Aim for under 20 words; lead with the key point.", "long-message")

    if element == "button" and n >= 1 and norm.split() and norm.split()[0] in {"the", "a", "an", "this", "your"}:
        add("clarity", "low", "Button should start with an action verb.", "Rephrase as “Verb + object”.", "button-verb")

    # ---- accessibility
    if SENSORY.search(text):
        add("accessibility", "high", "Relies on colour, shape or position to identify an element (WCAG 1.3.3 Sensory Characteristics).",
            "Refer to the element by its name or label instead.", "sensory")

    if element in ("button", "other", "message") and DEVICE_SPECIFIC.search(text):
        add("accessibility", "medium", "Assumes a specific input device (click / tap / hover).", "Use device-neutral verbs: “select”, “choose”, “open”.", "device-specific")

    letters = re.sub(r"[^A-Za-z]", "", text)
    if len(letters) > 3 and letters.isupper():
        add("accessibility", "medium", "ALL CAPS text is harder to read and some screen readers spell it out letter by letter.",
            "Use sentence case and style with CSS if you need uppercase.", "all-caps")

    if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text):
        add("accessibility", "medium", "Emoji or pictographic symbols are announced verbosely by screen readers and may not render.",
            "Replace with an icon that has an accessible name, or plain text.", "emoji")

    if re.search(r"[!]{2,}|[?]{2,}|\.{4,}", text):
        add("accessibility", "low", "Repeated punctuation is noisy for screen readers.", "Use a single punctuation mark.", "repeat-punct")

    if re.search(r"\w[/&|]\w|\([^)]*\bs\)", text) and element != "other":
        add("accessibility", "low", "Slashes, ampersands or “(s)” are read awkwardly by assistive tech.", "Write out “and” / “or”.", "symbols")

    if not re.search(r"[A-Za-z]", text) or (n == 1 and len(ws[0]) == 1):
        add("accessibility", "high", "Symbol-only or single-letter text gives no accessible name.", "Add visible text or an aria-label such as “Close dialog”.", "symbol-only")

    if element == "label" and low.endswith(":") is False and low in {"enter text", "type here", "enter value", "input"}:
        add("accessibility", "medium", "Placeholder-style wording used as a label.", "Use a persistent, descriptive label such as “Email address”.", "placeholder-label")

    if BLAME.search(text):
        add("accessibility", "medium", "Blames the user, which harms trust and is harder for people with cognitive disabilities.", "Describe what happened neutrally and what to do next.", "blame")

    # ---- message-specific guidance
    if element == "message":
        is_error = bool(re.search(r"\b(?:error|failed|fail|invalid|cannot|can't|couldn't|unable|wrong|problem|denied|not found|incorrect|unauthori[sz]ed)\b", low))
        if is_error and not HELPING.search(text):
            add("clarity", "high", "Error message states a problem but gives no way to fix it.", "Add the next step, e.g. “Check your connection and try again.”", "no-remedy")
        if n < 3 and is_error:
            add("clarity", "medium", "Error message is too terse to explain what went wrong.", "Say what failed and why in plain words.", "terse-error")
        if text.isupper() is False and text.strip().endswith("!") and is_error:
            add("clarity", "low", "Exclamation marks in errors sound alarming.", "End with a full stop.", "exclaim-error")

    return issues


SEVERITY_PENALTY = {"high": 22, "medium": 12, "low": 5}
CATEGORIES = ("clarity", "accessibility", "reading", "consistency")


def reading_issue(element: str, ease: float | None, grade: float | None, n_words: int) -> Issue | None:
    # tiny strings give unreliable formula output: only flag when there is enough text
    if ease is None or n_words < 6:
        return None
    if grade is not None and grade > 12:
        return Issue("reading", "high", f"Reading grade {grade} — college level. Plain-language guidance targets grade 6–8.",
                     "Use shorter sentences and everyday words.", "grade-high")
    if grade is not None and grade > 8:
        return Issue("reading", "medium", f"Reading grade {grade} is above the recommended grade 8.",
                     "Shorten sentences, swap long words for short ones.", "grade-medium")
    return None


# ---------------------------------------------------------------- cross-item rules
def check_consistency(items: list[ItemResult]) -> list[tuple[int, Issue]]:
    out: list[tuple[int, Issue]] = []

    # 1. different terms for the same concept
    for group in AMBIGUOUS_PAIRS:
        found: dict[str, list[int]] = defaultdict(list)
        for it in items:
            n = normalise(it.text)
            for term in group:
                if re.search(rf"\b{re.escape(term)}\b", n):
                    found[term].append(it.id)
                    break
        if len(found) > 1:
            names = ", ".join(f"“{t}”" for t in sorted(found))
            for ids in found.values():
                for i in ids:
                    out.append((i, Issue("consistency", "medium", f"Inconsistent terminology — the same idea is written as {names}.",
                                         "Pick one term and use it everywhere.", "term-variants")))

    # 2. capitalisation style by element type
    for element in ("button", "label"):
        group = [it for it in items if it.element == element and case_style(it.text) in ("title", "sentence", "upper", "lower", "mixed")]
        styles: dict[str, list[int]] = defaultdict(list)
        for it in group:
            styles[case_style(it.text)].append(it.id)
        if len(styles) > 1:
            dominant = max(styles, key=lambda s: len(styles[s]))
            for style, ids in styles.items():
                if style != dominant:
                    for i in ids:
                        out.append((i, Issue("consistency", "low",
                                             f"Capitalisation is {style} case but most {element}s use {dominant} case.",
                                             f"Match the {dominant}-case convention used by the other {element}s.", "case-style")))

    # 3. trailing punctuation by element type
    for element in ("button", "label", "message"):
        group = [it for it in items if it.element == element]
        if len(group) < 3:
            continue
        ends = {it.id: bool(re.search(r"[.!?:]$", it.text.strip())) for it in group}
        with_p = [i for i, v in ends.items() if v]
        without = [i for i, v in ends.items() if not v]
        minority = with_p if len(with_p) < len(without) else without
        if with_p and without and len(minority) < len(group) / 2 + 0.5:
            verb = "ends with punctuation" if minority is with_p else "has no end punctuation"
            for i in minority:
                out.append((i, Issue("consistency", "low", f"This {element} {verb}, unlike most other {element}s.",
                                     "Standardise end punctuation per element type.", "punctuation")))

    # 4. near-duplicates (same normalised text, differing form)
    seen: dict[str, list[ItemResult]] = defaultdict(list)
    for it in items:
        seen[normalise(it.text)].append(it)
    for key, group in seen.items():
        raw = {g.text for g in group}
        if key and len(raw) > 1:
            for g in group:
                out.append((g.id, Issue("consistency", "low", "Same text appears with different capitalisation/punctuation.",
                                        "Use one exact form.", "duplicate-variant")))

    # 5. conflicting tone: mix of "please" and none in messages, "you/your" vs "we"
    return out


# ---------------------------------------------------------------- public API
def parse_input(raw: str, default_element: str = "other") -> list[tuple[str, str]]:
    """Each line is either `text` or `element | text` (button|label|message|other)."""
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        element = default_element
        m = re.match(r"^(button|label|message|other|btn|error)\s*[|:>\t]\s*(.+)$", line, re.I)
        if m:
            element = {"btn": "button", "error": "message"}.get(m.group(1).lower(), m.group(1).lower())
            line = m.group(2).strip()
        rows.append((line, element))
    return rows


def analyse(rows: list[tuple[str, str]]) -> dict:
    items: list[ItemResult] = []
    for idx, (text, element) in enumerate(rows, 1):
        if element not in ELEMENT_TYPES:
            element = "other"
        ease, grade = readability(text)
        n = len(words(text))
        item = ItemResult(id=idx, text=text, element=element, word_count=n,
                          reading_ease=ease, grade=grade, reading_label=reading_label(ease))
        item.issues = check_item(text, element)
        ri = reading_issue(element, ease, grade, n)
        if ri:
            item.issues.append(ri)
        items.append(item)

    for i, issue in check_consistency(items):
        items[i - 1].issues.append(issue)

    for it in items:
        # drop exact duplicate messages produced by overlapping rules
        seen, unique = set(), []
        for iss in it.issues:
            key = (iss.rule, iss.message)
            if key not in seen:
                seen.add(key)
                unique.append(iss)
        it.issues = unique
        it.scores = {c: 100 for c in CATEGORIES}
        for iss in it.issues:
            it.scores[iss.category] = max(0, it.scores[iss.category] - SEVERITY_PENALTY[iss.severity])
        # reading ease also feeds the reading score for longer text
        if it.reading_ease is not None and it.word_count >= 6:
            it.scores["reading"] = min(it.scores["reading"], int(round(it.reading_ease)))
        it.score = int(round(sum(it.scores.values()) / len(CATEGORIES)))
        it.issues.sort(key=lambda x: ("high", "medium", "low").index(x.severity))

    total = len(items)
    avg = lambda key: round(sum(i.scores[key] for i in items) / total) if total else 0
    sev = defaultdict(int)
    for it in items:
        for iss in it.issues:
            sev[iss.severity] += 1
    long_items = [i for i in items if i.reading_ease is not None and i.word_count >= 6]
    summary = {
        "total": total,
        "overall": round(sum(i.score for i in items) / total) if total else 0,
        "categories": {c: avg(c) for c in CATEGORIES} if total else {c: 0 for c in CATEGORIES},
        "issues": {"high": sev["high"], "medium": sev["medium"], "low": sev["low"]},
        "passing": sum(1 for i in items if not i.issues),
        "avg_grade": round(sum(i.grade for i in long_items) / len(long_items), 1) if long_items else None,
        "avg_ease": round(sum(i.reading_ease for i in long_items) / len(long_items), 1) if long_items else None,
    }
    return {"summary": summary, "items": [asdict(i) for i in items]}
