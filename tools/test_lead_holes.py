# -*- coding: utf-8 -*-
"""The businesses the lead list could not see.

The owner spoke to a painter in Powderly and found him missing from his own
call sheet. Two separate holes, and a third that stops either from being
patched by hand:

  1. A trade that sells LABOUR is on no list this import creates from. It
     collects no sales tax, so it is not on the permit spine; painting is not
     a licensed trade in Texas, so there is no TDLR record; and a one-van
     operation is on no map. The franchise file holds them and was downloaded
     only to decorate rows that already existed. Measured against the live
     board: 180 businesses missing, 10 of them painters, 40 concrete and
     welding, 25 plumbing and electrical.
  2. A SOLE TRADER is in no state file at all - no company, so no franchise
     tax either. The painter is one of these, and no source change reaches
     him.
  3. And there was no way to type one in.

What is proved:

  1. A name that declares a trade creates a lead; a registration that declares
     nothing does not.
  2. THE TRAP: the same file holds PAINTED WIND RANCH, PAINTER FIREARMS
     TRAINING INSTITUTE and NETA PAINTER, CPA. None of them is a decorator,
     and a wrong name on a call sheet is worse than a missing one because
     somebody reads it out.
  3. A typed lead is keyed exactly as the import keys one, so a later import
     folds into it rather than writing the business twice.
  4. And it is recorded as typed, which is what stops the loader overwriting
     what somebody put there by hand.

Run: python tools/test_lead_holes.py
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-leads-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import import_leads as il  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Lead, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("A NAME THAT SAYS WHAT IT DOES:")
# Every one of these is a real row in the live franchise file for these
# counties, which is why they are the fixture.
for name, want in (
        ("SIMMONS PAINTING LLC", "Painting and finishing"),
        ("GRIMALDO'S PAINTING LLC", "Painting and finishing"),
        ("CARTER'S PAINTING & DRYWALL, LLC", "Painting and finishing"),
        ("ARRITOLA'S PLUMBING, LLC", "Plumbing, heating and electrical"),
        ("BKM ELECTRIC, LLC", "Plumbing, heating and electrical"),
        ("WITHERS EXCAVATION, L.L.C.", "Site preparation and other trades"),
        ("ROSS WELDING AND FABRICATION, LLC", "Site preparation and other trades"),
        ("FREEDOM FENCING LLC", "Building trade contractors"),
        ("LATINOS PAINT & CLEANING S. LLC", "Cleaning and landscaping")):
    got = il.trade_in_the_name(name)
    check(f"{name[:40]} -> {want}", got == want, got or "nothing")

print("\nTHE TRAP, AND IT IS IN THE SAME FILE:")
for name, why in (
        ("PAINTED WIND RANCH, L.L.C.", "a ranch, and painted is not painting"),
        ("PAINTER FIREARMS TRAINING INSTITUTE LLC", "a firearms school"),
        ("NETA PAINTER, CPA LLC", "an accountant whose surname is Painter"),
        ("PAINT YOUR WAGON PARK, LLC", "a park"),
        ("DOMUS I LLC", "a shell, and it names nothing"),
        ("W RANGE FIEFDOM LLC", "a shell"),
        ("KINGDOM ACRES, LP", "land"),
        ("PARIS LOGISTICS CENTER, LLC", "names a trade, but see below")):
    got = il.trade_in_the_name(name)
    if name.startswith("PARIS LOGISTICS"):
        check("a genuine logistics company is still found", got == "Trucking", got)
        continue
    check(f"{name[:40]} is not a lead ({why})", got == "", got)

check("an empty name is not a trade", il.trade_in_the_name("") == "")
check("and neither is None", il.trade_in_the_name(None) == "")


print("\nTYPING IN ONE THE STATE HAS NEVER HEARD OF:")
with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    db.session.commit()
    boss_id = boss.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

r = c.post("/admin/leads/new", data={
    "name": "Dom's Painting Services", "city": "powderly", "phone": "(903) 249-0350",
    "website": "https://domspaintingservices.com", "new_industry": "Painting and finishing",
    "owner_name": "Dom", "notes": "Spoke to him on the phone."}, follow_redirects=True)
check("the press lands back on the list", r.status_code == 200)

with application.app_context():
    lead = Lead.query.filter(Lead.name.ilike("%Dom%")).first()
    check("the business is on the list", lead is not None)
    if lead:
        check("with the town spelled the way the filters spell it",
              lead.city == "Powderly", lead.city)
        check("and the trade the filters offer",
              lead.industry == "Painting and finishing", lead.industry)
        check("and the telephone", lead.phone == "(903) 249-0350", lead.phone)
        check("THE POINT: recorded as typed, which is what the loader will not overwrite",
              lead.sources == "typed", lead.sources)
        check("its website counts as checked, because somebody just read it",
              lead.website_checked_at is not None)
        check("so it is not counted as a business with no site found",
              lead.no_website is False, lead.no_website)
        # The whole point of the key: a later import must fold into this row.
        typed_name = "Dom's Painting Services"
        expect = (il.norm(typed_name) + "|" + il.norm("powderly"))[:240]
        check("THE POINT: keyed exactly as the import keys one",
              lead.dedupe_key == expect, (lead.dedupe_key, expect))

print("\nAND IT DOES NOT WRITE THE SAME BUSINESS TWICE:")
r = c.post("/admin/leads/new", data={"name": "Dom's Painting Services",
                                     "city": "powderly"}, follow_redirects=True)
body = r.data.decode("utf-8", "replace")
with application.app_context():
    check("still one row", Lead.query.count() == 1, Lead.query.count())
check("and it says so", "already on the list" in body,
      body[-400:] if "already" not in body else "")

r = c.post("/admin/leads/new", data={"name": "   "}, follow_redirects=True)
with application.app_context():
    check("a lead with no name is refused", Lead.query.count() == 1, Lead.query.count())

print("\nA WEBSITE NOBODY TYPED IS STILL UNCHECKED:")
c.post("/admin/leads/new", data={"name": "Quiet Trades LLC", "city": "paris"},
       follow_redirects=True)
with application.app_context():
    quiet = Lead.query.filter_by(name="Quiet Trades LLC").first()
    check("nobody has looked for its website yet",
          quiet is not None and quiet.website_checked_at is None)
    check("so the board must not call it a business with no site found",
          quiet is not None and quiet.no_website is False,
          "an empty column and an established absence are different facts")

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
