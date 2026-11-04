# -*- coding: utf-8 -*-
"""The bank review list, settled without the paid API (automation item 2).

  1. The board's own suggestion, in order: a counterparty settled by hand
     before, a receipt for the same amount, a vendor the board already pays,
     the bank's merchant category; on an owner's personal card a restaurant
     is personal. Only the first three carry a pattern, so only they write a
     rule. A suggestion somebody else wrote is left alone.
  2. The door: /api/guidance/bank/review is behind the bearer gate and lists
     the waiting lines with their suggestions; /bank/decide settles them,
     writes the rule, settles every line like it, and refuses nonsense.
  3. The bridge tools and the /bank skill exist and read the door.

Run: python tools/test_bank_review.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
TMP = tempfile.mkdtemp(prefix="board-bankreview-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Expense, Receipt,  # noqa: E402
                    ReceiptMailbox, VendorRule)
import bank_feed  # noqa: E402
import bank_review  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def line(conn, ext, amount, name, day=date(2026, 10, 5), category="", kind="debitCardTransaction"):
    l = BankTransaction(connection_id=conn.id, business_id=conn.business_id, external_id=ext, amount=amount,
                        occurred_on=day, status="sent", kind=kind, counterparty=name,
                        merchant_category=category)
    db.session.add(l)
    db.session.flush()
    bank_feed.classify(l)
    return l


with application.app_context():
    db.create_all()
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add_all([bbb, ehq])
    db.session.flush()
    merc = BankConnection(business_id=bbb.id, provider="mercury", label="Mercury", token="x")
    card = BankConnection(business_id=bbb.id, provider="statement", label="Sapphire", kind="personal",
                          owner_name="Michael Bean")
    box = ReceiptMailbox(address="m@example.test", business_id=ehq.id, password="x")
    db.session.add_all([merc, card, box])
    db.session.commit()

    print("1. The board's own suggestion")
    # Settled by hand before, without remember: no rule, still an answer.
    old = line(merc, "h1", -6.50, "SQ *BLUE BOTTLE 0123 OAKLAND CA", day=date(2026, 9, 2))
    bank_feed.decide(old, "expense", business_id=bbb.id, category="meals", vendor="Blue Bottle", keep=False)
    again = line(merc, "h2", -7.25, "SQ *BLUE BOTTLE 0456 OAKLAND CA")
    rec = Receipt(mailbox_id=box.id, message_key="r1", sender="Linear <billing@linear.app>", vendor="Linear",
                  subject="Your receipt", received_on=date(2026, 10, 4), amount=8.00, status="unmatched")
    db.session.add(rec)
    by_receipt = line(merc, "r1", -8.00, "LINEAR.APP")
    by_vendor = line(merc, "v1", -4.00, "GITHUB, INC.")
    by_category = line(merc, "c1", -31.10, "LA MADELEINE 22", category="Restaurants")
    on_card = line(card, "p1", -18.40, "CHUYS AUSTIN", category="Food & Drink", kind="statement")
    nothing = line(merc, "n1", -99.00, "ZQXJ HOLDINGS")
    claude_said = line(merc, "q1", -3.00, "SOMETHING ELSE")
    claude_said.suggestion_json = json.dumps({"disposition": "personal", "why": "Claude said"})
    db.session.commit()
    check("all seven wait on review",
          all(l.disposition == "review" for l in (again, by_receipt, by_vendor, by_category, on_card, nothing)))
    bank_review.suggest_free()
    db.session.commit()
    s = again.suggestion or {}
    check("a counterparty settled by hand before is suggested the same way",
          s.get("source") == "history" and s.get("disposition") == "expense" and s.get("category") == "meals"
          and s.get("pattern") == "BLUE BOTTLE", s)
    s = by_receipt.suggestion or {}
    check("a receipt for the same amount names the vendor, its mailbox's company and a pattern",
          s.get("source") == "receipt" and s.get("vendor") == "Linear" and s.get("business_id") == ehq.id
          and s.get("pattern") == "LINEAR APP", s)
    s = by_vendor.suggestion or {}
    check("a vendor the board already pays", s.get("source") == "vendor" and s.get("category") == "software"
          and s.get("pattern") == "GITHUB", s)
    s = by_category.suggestion or {}
    check("the bank's merchant category, and no rule from it",
          s.get("source") == "category" and s.get("category") == "meals" and not s.get("pattern"), s)
    s = on_card.suggestion or {}
    check("a restaurant on a personal card is personal", s.get("disposition") == "personal", s)
    check("a line nothing explains carries no suggestion", nothing.suggestion is None, nothing.suggestion)
    check("a suggestion somebody else wrote is left alone", (claude_said.suggestion or {}).get("why") == "Claude said")
    check("the key drops store numbers and processors",
          bank_review.counterparty_key("SQ *BLUE BOTTLE 0456 OAKLAND CA") == "BLUE BOTTLE")
    ids = {"again": again.id, "vendor": by_vendor.id, "nothing": nothing.id, "bbb": bbb.id}
    second_github = line(merc, "v2", -4.00, "GITHUB, INC.", day=date(2026, 10, 9))
    ids["github2"] = second_github.id
    db.session.commit()

print("2. The door")
c = application.test_client()
H = {"Authorization": "Bearer test-key"}
check("no token, no door", c.get("/api/guidance/bank/review").status_code == 401)
r = c.get("/api/guidance/bank/review", headers=H)
data = r.get_json() or {}
check("the review lists the waiting lines", r.status_code == 200 and data.get("waiting", 0) >= 7, data.get("waiting"))
got = {l["id"]: l for l in data.get("lines", [])}
check("each with the board's suggestion", (got.get(ids["vendor"], {}).get("suggestion") or {}).get("source") == "vendor")
check("and what a session judges with",
      {"companies", "categories", "projects", "rules", "settled_by_hand"} <= set(data))
r = c.post("/api/guidance/bank/decide", headers=H, json={"decisions": [
    {"id": ids["vendor"], "disposition": "expense", "business_id": ids["bbb"], "category": "software",
     "vendor": "GitHub", "pattern": "GITHUB", "keep": True},
    {"id": ids["nothing"], "disposition": "bribe"},
    {"id": 999999, "disposition": "expense"},
]})
out = r.get_json() or {}
res = {x["id"]: x for x in out.get("results", [])}
check("a decision settles the line", res.get(ids["vendor"], {}).get("settled") == "expense", res)
check("and the rule settles the next GitHub charge too", out.get("settled_alike", 0) >= 1, out)
check("a disposition that does not exist is refused", "error" in res.get(ids["nothing"], {}), res)
check("a line that does not exist is refused", "error" in res.get(999999, {}), res)
check("an empty body is refused", c.post("/api/guidance/bank/decide", headers=H, json={}).status_code == 400)
with application.app_context():
    check("the rule is written", VendorRule.query.filter_by(pattern="GITHUB").first() is not None)
    g2 = db.session.get(BankTransaction, ids["github2"])
    check("the second GitHub line is an expense with its own expense row",
          g2.disposition == "expense" and g2.expense_id is not None, (g2.disposition, g2.expense_id))
    check("a line still waiting stays waiting", db.session.get(BankTransaction, ids["nothing"]).disposition == "review")

print("3. The bridge and the skill")
import pm_guidance_mcp as mcp  # noqa: E402


def through_client(method, path, payload=None):
    resp = c.open(path, method=method, headers=H, json=payload)
    if resp.status_code >= 400:
        return None, f"the board answered {resp.status_code}"
    return resp.get_data(as_text=True), None


mcp._http = through_client
text = mcp.HANDLERS["bank_review"]({"limit": 50})
check("bank_review reads the door as text", "WAITING" in text and "COMPANIES" in text, text[:200])
names = {t["name"] for t in mcp.TOOLS}
check("both tools are offered", {"bank_review", "bank_decide"} <= names)
with application.app_context():
    nid = ids["nothing"]
reply = mcp.HANDLERS["bank_decide"]({"decisions": [{"id": nid, "disposition": "personal", "keep": False}]})
check("bank_decide settles through the door", f"{nid}: personal" in reply, reply)
skill = (ROOT / ".claude" / "skills" / "bank" / "SKILL.md").read_text(encoding="utf-8")
check("the /bank skill names its tools", "name: bank" in skill and "bank_decide" in skill and "bank_review" in skill)
for path in ("bank_review.py", "pm/bank_door_routes.py", ".claude/skills/bank/SKILL.md"):
    check(f"no em dash in {path}", "—" not in (ROOT / path).read_text(encoding="utf-8"))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
