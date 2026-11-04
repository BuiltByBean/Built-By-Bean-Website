# -*- coding: utf-8 -*-
"""A session searches the catalogue in its own words.

Until 2026-11-04 the search looked for the whole query as one string, so "sign a
contract" answered "nothing in the catalogue" while e-signature sat there, and a
session told that builds the thing blind. It also handed back every match whole,
76,917 bytes for "dropdown", which is more than a tool's answer can carry.

This boots the board on a throwaway SQLite database and proves:

  1. The words are matched wherever they are, in any order and any form.
  2. A word has to start a word: "tax" is not in "syntax".
  3. Most of the words have to be there, so a wrong answer is not offered.
  4. A name beats a summary beats a body, and an exact name beats everything.
  5. A retired entry is never found.
  6. The answer fits, the best come whole, the rest say how to read them, and
     asking by name or slug brings any entry back whole.

Run: python tools/test_guidance_search.py
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
TMP = tempfile.mkdtemp(prefix="board-search-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Feature  # noqa: E402
from pm.guidance_routes import SEARCH_WHOLE  # noqa: E402
import pm_guidance_mcp  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


application = create_app()
application.config["TESTING"] = True
client = application.test_client()
HEADERS = {"Authorization": "Bearer test-key"}


def find(query):
    r = client.get("/api/guidance/search", query_string={"q": query}, headers=HEADERS)
    assert r.status_code == 200, r.status_code
    return r.get_json()["matches"]


def names(query):
    return [m["name"] for m in find(query)]


with application.app_context():
    db.create_all()
    for i, (slug, name, kind, summary, gold, pit) in enumerate([
        ("e-signature", "E-signature", "feature", "Send a document and have it signed online",
         "The contract is sealed once both have signed.", ""),
        ("appointment-text", "Appointment reminder text", "feature", "A text the day before they are due",
         "Send the SMS at a sensible hour.", ""),
        ("sales-tax", "Sales tax by state", "feature", "Charge the right tax", "", ""),
        ("syntax", "Syntax highlighting", "rule", "Code reads in colour", "Mark up the syntax.", ""),
        ("mentions-tax-in-passing", "Keep every receipt", "rule", "Records", "It matters at tax time.", ""),
        ("old-thing", "Old contract signing", "feature", "Retired", "", ""),
        ("huge-one", "Dropdown one", "rule", "A big one", "x " * 14000, ""),
        ("huge-two", "Dropdown two", "rule", "Another big one", "y " * 14000, ""),
        ("huge-three", "Dropdown three", "rule", "And another", "z " * 14000, ""),
    ]):
        db.session.add(Feature(slug=slug, name=name, kind=kind, summary=summary, gold_standard_md=gold,
                               pitfalls_md=pit, sort_order=i, is_active=slug != "old-thing"))
    db.session.commit()

print("1. The words, wherever they are")
check("sign a contract finds e-signature", "E-signature" in names("sign a contract"), names("sign a contract"))
check("in any order", "E-signature" in names("contract signing"))
check("and across fields", "Appointment reminder text" in names("sms reminders"), names("sms reminders"))
check("a question reads the same as its words", "E-signature" in names("how do I get a contract signed"))
check("nothing near it answers nothing", names("zebra quokka") == [])

print("2. From the start of a word")
check("tax is not in syntax", "Syntax highlighting" not in names("tax"), names("tax"))

print("3. Most of the words")
check("one word of three is not an answer", names("contract zebra quokka") == [], names("contract zebra quokka"))
check("two of three is", "E-signature" in names("signed contract zebra"), names("signed contract zebra"))

print("4. What it ranks by")
order = names("tax")
check("a name beats a body", order.index("Sales tax by state") < order.index("Keep every receipt"), order)
check("searching an exact name puts it first", names("Dropdown two")[0] == "Dropdown two", names("Dropdown two"))

print("5. A retired entry")
check("is never found", "Old contract signing" not in names("contract signing"))

print("6. The answer fits")
big = find("dropdown")
check("all three are named", len(big) == 3, len(big))
whole = [m for m in big if not m.get("cut")]
cut = [m for m in big if m.get("cut")]
check("the best comes whole", whole and whole[0]["how_to_build"], [m["name"] for m in whole])
check("and the rest are left short", cut and all(m["how_to_build"] == "" for m in cut), [m["name"] for m in cut])
check("so the whole answer is inside the budget",
      sum(len(m["how_to_build"]) + len(m["what_went_wrong"]) for m in big) <= SEARCH_WHOLE)
check("a short one still says what it is", all(m["summary"] and m["slug"] for m in cut))
printed = pm_guidance_mcp._entry_text(cut[0])
check("the bridge says how to read it whole", "Search for its slug" in printed and cut[0]["slug"] in printed, printed)
check("the bridge does not say so on a whole one", "Search for its slug" not in pm_guidance_mcp._entry_text(whole[0]))
slug = cut[0]["slug"]
again = find(slug)
check("searching that slug brings it back whole", again[0]["slug"] == slug and again[0]["how_to_build"]
      and not again[0].get("cut"), again[0]["slug"])
one = find("huge-one")[0]
check("the first answer is whole even past the budget's share", one["slug"] == "huge-one" and one["how_to_build"])

print()
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
    sys.exit(1)
print("all passed")
