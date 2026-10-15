from analyzer import analyse, check_item, count_syllables, parse_input, readability, suggest_rewrite
from app import app


def rules(text, el="other"):
    return {i.rule for i in check_item(text, el)}


def test_syllables():
    assert count_syllables("cat") == 1
    assert count_syllables("table") == 2
    assert count_syllables("accessibility") >= 5


def test_readability_simple_is_easier_than_complex():
    easy, _ = readability("Save your file. Then close the window.")
    hard, _ = readability("Authentication credentials were unequivocally invalidated by the administrative infrastructure.")
    assert easy > hard


def test_generic_and_vague():
    assert "generic-link" in rules("Click here", "button")
    assert "vague-button" in rules("Submit", "button")
    assert "vague-button" not in rules("Save changes", "button")


def test_sensory_and_caps_and_emoji():
    assert "sensory" in rules("Press the red button on the left")
    assert "all-caps" in rules("CANCEL", "button")
    assert "emoji" in rules("Save 🚀", "button")


def test_error_without_remedy():
    assert "no-remedy" in rules("Invalid password.", "message")
    assert "no-remedy" not in rules("Invalid password. Try again.", "message")


def test_consistency_terms():
    res = analyse([("Log in", "button"), ("Sign in", "button"), ("Login", "button")])
    assert all(any(i["rule"] == "term-variants" for i in it["issues"]) for it in res["items"])


def test_parse_input():
    rows = parse_input("# c\nbutton | Save\n\nplain")
    assert rows == [("Save", "button"), ("plain", "other")]


def test_api():
    c = app.test_client()
    assert c.post("/api/analyze", json={"text": ""}).status_code == 400
    r = c.post("/api/analyze", json={"text": "button | Submit\nlabel | Email"})
    assert r.status_code == 200 and r.json["summary"]["total"] == 2
    assert c.get("/").status_code == 200


def test_parse_aliases():
    rows = parse_input("Button label: Click here\nError message: Invalid input\nForm instruction: Fill this in\nPlaceholder - Email")
    assert [r[1] for r in rows] == ["button", "message", "message", "label"]
    assert rows[0][0] == "Click here"


def test_rewrites():
    assert suggest_rewrite("CANCEL", "button") == "Cancel"
    assert suggest_rewrite("Provide it prior to proceeding.", "message") == "Provide it before proceeding."
    assert suggest_rewrite("Save changes", "button") == ""
    assert analyse([("CANCEL", "button")])["items"][0]["rewrite"] == "Cancel"


def test_rewrite_is_conservative():
    assert suggest_rewrite("Invalid parameter", "message") == ""
    assert suggest_rewrite("Please utilize the tool", "message") == "Please use the tool"
