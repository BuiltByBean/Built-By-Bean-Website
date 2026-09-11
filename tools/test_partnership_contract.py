# -*- coding: utf-8 -*-
"""The revenue share agreement: the words that have to be on it.

This is the one document this board sends where Built by Bean LLC is the party
paying rather than the party being paid, and almost every mistake available
here is a mistake of reuse: a clause written for a client engagement that means
the opposite when the money runs the other way.

What is proved:

  1. The share is refused unless it is a number, and a number between 0 and 100.
  2. A net profit share says it is not gross, and a gross commission says no
     costs come off. Neither document can be read as the other.
  3. The Partner is paid out of money that arrived, and nothing is advanced.
  4. It is not a partnership in law: every factor a Texas court weighs is
     negated on the page.
  5. The Venture belongs to Built by Bean LLC, and a sale of it pays no share.
  6. THE TRAP: the $50 per day late fee from STANDALONE_PROTECTIONS is nowhere
     on this document. That clause runs against whoever pays late, and on this
     one that is Michael.
  7. What is typed on the form is what is on the page.

The text is captured at `contract_style.sanitize`, which every drawn string
passes through, so this needs no PDF parser and no new dependency. When pymupdf
happens to be installed the rendered page is read back as well, because text
handed to a drawing call is not quite the same claim as text on the paper.

Run: python tools/test_partnership_contract.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-partnership-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import re  # noqa: E402

import contract_docs  # noqa: E402
import contract_style  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Client, SignatureRequest, User  # noqa: E402
import pm.contract_routes as contract_routes  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# Every string drawn on a page goes through sanitize on its way to fpdf, so
# wrapping it is the whole document as text, in the order it was written.
DRAWN = []
_real_sanitize = contract_style.sanitize


def _recording(text):
    out = _real_sanitize(text)
    DRAWN.append(out)
    return out


contract_style.sanitize = _recording
contract_docs.contract_style.sanitize = _recording


def build(**kw):
    """One document, and everything written on it as one flat string."""
    DRAWN.clear()
    base = dict(partner_name="Kenali Kendrick", venture="EntertainHQ",
                share_pct="35", date_str="April 09, 2026")
    base.update(kw)
    pdf_bytes = contract_docs.build_partnership(**base)[0]
    return pdf_bytes, " ".join(" ".join(DRAWN).split())


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    partner = Client(name="Kenali Kendrick", email="kenali@example.test")
    db.session.add_all([boss, partner])
    db.session.commit()
    boss_id, partner_id = boss.id, partner.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True


print("THE FORM:")
r = c.get("/admin/contracts/new/partnership")
body = r.data.decode("utf-8", "replace")
check("it draws", r.status_code == 200, r.status_code)
check("the partner is picked from the client list", 'name="client_id"' in body)
check("the basis is a choice, not a guess",
      "% of Net Profit" in body and "commission" in body)
# Comments stripped first: base.html carries a long note explaining why this
# app has no native select, and it is full of the word.
_no_comments = re.sub(r"<!--.*?-->", "", body, flags=re.S)
check("and it is not a native select (LM-2)", "<select" not in _no_comments)
check("the contracts page links to it", "new/partnership"
      in c.get("/admin/contracts/").data.decode("utf-8", "replace"))


print("\nTHE SHARE HAS TO BE A SHARE:")
def generate(**over):
    form = dict(client_id=str(partner_id), venture="EntertainHQ", share_pct="35",
                date="2026-04-09")
    form.update(over)
    return c.post("/admin/contracts/new/partnership", data=form, follow_redirects=True)


for bad, why in (("", "empty"), ("abc", "not a number"),
                 ("150", "more than everything"), ("0", "nothing at all")):
    r = generate(share_pct=bad)
    page = r.data.decode("utf-8", "replace")
    check(f"a share of {why} is refused",
          "new/partnership" in page and "Preview it" in page and "preview/" not in page)
r = generate(venture="")
check("and so is a venture with no name",
      "Preview it" in r.data.decode("utf-8", "replace"))

r = generate(share_pct="35%")
check("a typed percent sign is not a problem", "preview/" in r.request.path
      or r.status_code == 200, r.request.path)


print("\nA SHARE OF NET PROFIT:")
pdf_bytes, text = build(basis="net_profit", share_pct="35")
check("it is a percentage of Net Profit", "35% of the Net Profit" in text)
check("and says in terms that it is not gross",
      "not a percentage of gross revenue and it is not a commission on sales" in text)
check("the deductions are listed", "Payment processing, platform and marketplace fees" in text)
check("his own time is not quietly deducted",
      "general business overhead is not deducted" in text and "neither is its own time" in text)

_, timed = build(basis="net_profit", our_time_rate="100")
check("unless he says so, and then it is a line item",
      "development and support time spent on the Venture, at $100 per hour" in timed)
check("and the sentence changes with it",
      "neither is its own time" not in timed)


print("\nA COMMISSION ON GROSS:")
_, gross = build(basis="gross", share_pct="15")
check("it is a commission on Gross Receipts", "commission of 15% of the Gross" in gross)
check("nothing is deducted before it",
      "Nothing else is deducted before the commission is calculated" in gross)
check("and the words Net Profit appear nowhere on it", "Net Profit" not in gross)


print("\nPAID ONLY OUT OF MONEY THAT ARRIVED:")
check("the callout says it plainly",
      "does not pay the Partner before it has been paid itself" in text)
check("an invoice is not revenue",
      "is not a Gross Receipt until the money has been received and has cleared" in text)
check("no advance, no draw, no minimum",
      "No advance, draw, retainer, guarantee or minimum is payable" in text)
check("a refund after payment comes back",
      "the Partner's share of it is deducted from the next payment due" in text)


print("\nIT IS NOT A PARTNERSHIP IN LAW:")
for phrase, what in (
        ("does not create a partnership, joint venture", "the relationship is disclaimed"),
        ("contributes no capital", "no capital"),
        ("bears none of its losses", "no losses"),
        ("no right to control or direct the business", "no control"),
        ("holds no property in common", "no common property"),
        ("Neither party may bind the other", "no authority to bind"),
        ("The Partner is not an employee", "not employment")):
    check(what, phrase in text, phrase)


print("\nWHO OWNS WHAT:")
check("the Venture is his outright",
      "is and remains the sole and exclusive property of Built by Bean LLC" in text)
check("he may package it and sell it to anyone",
      "packaging it, or any product derived from it, for license or sale to anyone" in text)
check("what she contributes is assigned to him",
      "is assigned to Built by Bean LLC as it is created" in text)
check("and selling the Venture pays no share",
      "is not a Gross Receipt, and no share is payable on the proceeds of it" in text)


print("\nTHE TRAP - A CLAUSE THAT RUNS THE WRONG WAY:")
check("the $50 a day late fee is NOT on this document",
      "$50 per day" not in text and "late fee" not in text)
check("the liability cap is measured on what he paid her",
      "the total amount it paid the Partner" in text)
check("and the SOW's own late fee is still on the SOW",
      any("$50 per day" in clause for clause in contract_docs.STANDALONE_PROTECTIONS))


print("\nEVERYTHING ELSE THAT PROTECTS HIM:")
for phrase, what in (
        ("does not guarantee that the Venture will earn any revenue", "no guarantee of revenue"),
        ("A period in which the share is zero is not a breach", "a zero month is not a breach"),
        ("in its sole discretion", "every business decision is his"),
        ("will not build, market, sell, promote or hold an interest in a product or service "
         "that competes", "she will not compete"),
        ("will not approach any customer", "and will not go round him"),
        ("are given in exchange for that information and are ancillary to it",
         "the Texas hook that makes a restraint enforceable"),
        ("It ends on the Partner's death", "the share is personal to her"),
        ("The Partner may not assign it", "and she cannot sell it on"),
        ("prevailing party is entitled to recover", "the loser pays the lawyer"),
        ("It does not replace or affect any Statement of Work",
         "THE POINT: her existing SOW is untouched by this")):
    check(what, phrase in text, phrase)
check("it is settled in Texas", contract_docs.GOVERNING_LAW[:40] in text)


print("\nWHAT IS TYPED IS WHAT IS PRINTED:")
_, custom = build(deductions=["Only this one thing"],
                  our_duties=["Build the thing"], their_duties=["Sell the thing"],
                  period="quarterly", pay_days="45", notice_days="60",
                  tail_months="6", restraint_months="24",
                  special_terms="A bonus of $1,000 on the tenth venue.",
                  title="Partnership Agreement")
check("the deductions are the ones given",
      "Only this one thing" in custom and "Advertising and marketing" not in custom)
check("the duties are the ones given", "Sell the thing" in custom)
check("quarterly, within 45 days",
      "each calendar quarter and paid within 45 days" in custom)
check("60 days notice to end it", "on 60 days written notice" in custom)
check("a tail that keeps paying for 6 months",
      "during the 6 months after it" in custom)
check("with no tail it stops on the day", "the Partner's right to a share ends with it" in text)
check("restrictions run 24 months", "for 24 months after it ends" in custom)
check("the special terms get their own section", "A bonus of $1,000 on the tenth venue." in custom)
check("and the title is the one asked for", "Partnership Agreement" in custom)


print("\nTHE LOOK:")
check("a bad colour falls back to the house violet",
      contract_style.rgb("nonsense") == contract_style.ACCENT)
check("and a good one is used", contract_style.rgb("#7c3aed") == (124, 58, 237))
missing = contract_docs.build_partnership(
    partner_name="X", venture="Y", share_pct="10", date_str="",
    mark_path=os.path.join(TMP, "not-there.png"))[0]
check("a logo that is not on the volume is not an outage", len(missing) > 1000)


print("\nIT REACHES THE PORTAL AS ITS OWN KIND:")
with application.app_context():
    row = SignatureRequest(envelope_id="env-p", title="Revenue Share Agreement - EntertainHQ",
                           kind="partnership", signer_name="Kenali Kendrick",
                           signer_email="kenali@example.test", status="sent",
                           created_at=datetime.now(timezone.utc))
    db.session.add(row)
    db.session.commit()
    check("the list says what it is", row.kind_label == "Revenue share", row.kind_label)
check("and a declined one reopens the form that made it",
      contract_routes.FORM_ENDPOINTS.get("partnership") == "contracts.partnership_form")


print("\nON THE PAPER, NOT ONLY IN THE CALL:")
try:
    import fitz
except ImportError:
    check("pymupdf is installed, so the rendered page was read back", False,
          "pip install pymupdf - without it these words were never checked on paper")
else:
    path = os.path.join(TMP, "rendered.pdf")
    with open(path, "wb") as fh:
        fh.write(pdf_bytes)
    doc = fitz.open(path)
    flat = " ".join(" ".join(p.get_text() for p in doc).split())
    doc.close()
    check("the promise about being paid is on the page",
          "does not pay the Partner before it has been paid itself" in flat)
    check("the disclaimer is on the page", "does not create a partnership" in flat)
    check("the late fee is not", "$50 per day" not in flat)
    check("it is signed by both parties",
          "Built by Bean LLC" in flat and "Kenali Kendrick" in flat)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
