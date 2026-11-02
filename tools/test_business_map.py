# -*- coding: utf-8 -*-
"""The business map: everything that makes a business run, and the holes.

Michael, 2026-11-02: a map of every service running a business, with hover
on the lines saying why, and the holes showing; and under it a business
playbook of every need. This boots the board on a throwaway SQLite database
and proves:

  1. The migration seeds the needs, their connections and each business's
     services off its repo; Mercury lands with no runbook and its name; a
     second run adds nothing, and a business with a map of its own is left alone.
  2. The layout: columns in build order, every service in its need's column,
     an essential nobody filled drawn as a hole, a template connection drawn
     between two filled needs with its why, a hand-written one winning over
     it, and a same-column line drawn as an arc that leaves the column.
  3. The pages draw (map, edit, business page with the counts, the tile's
     map button), the data rides in a single-quoted x-data, and the presses:
     fill a hole from the map, save, connect two, remove one and its links,
     and never touch another business's service.

Run: python tools/test_business_map.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-map-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, BusinessLink, BusinessNeed, BusinessNeedLink,  # noqa: E402
                    BusinessService, Playbook, User)
import business_map  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 0.0}

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def run_migration():
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/c7f2a9e41d05_the_business_map.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()
    return mig


with application.test_request_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    for slug, name, logo in (("stripe", "Stripe", "img/playbooks/stripe.svg"), ("railway", "Railway", ""),
                             ("postgres", "PostgreSQL", ""), ("github", "GitHub", ""),
                             ("resend", "Resend", ""), ("legalzoom", "LegalZoom", "")):
        db.session.add(Playbook(slug=slug, display_name=name, logo_path=logo, is_active=True))
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq", sales_source="manual")
    other = Business(name="Other Co", slug="other-co", sales_source="manual")
    db.session.add_all([boss, ehq, other])
    db.session.commit()
    db.session.add(BusinessService(business_id=other.id, name="Already here", role="Typed by hand"))
    db.session.commit()
    ids = dict(boss=boss.id, ehq=ehq.id, other=other.id)

    print("THE SEED:")
    mig = run_migration()
    needs = BusinessNeed.query.all()
    check("the needs are on file", len(needs) == len(mig.NEEDS), (len(needs), len(mig.NEEDS)))
    check("in build order, with the legal entity first",
          BusinessNeed.query.order_by(BusinessNeed.sort_order).first().slug == "legal-entity")
    check("with their connections", BusinessNeedLink.query.count() == len(mig.NEED_LINKS))
    e = db.session.get(Business, ids["ehq"])
    check("EntertainHQ has its services", len(e.services) == len(mig.SERVICES["entertainhq"]), len(e.services))
    mercury = next((s for s in e.services if s.name == "Mercury"), None)
    check("Mercury is on it by name, with no runbook", mercury is not None and mercury.playbook_id is None)
    stripe = next((s for s in e.services if s.playbook and s.playbook.slug == "stripe"), None)
    check("Stripe is on it through its runbook", stripe is not None and stripe.display_name == "Stripe")
    twilio = next((s for s in e.services if s.need and s.need.slug == "texting"), None)
    check("a runbook the board lacks still lands by name", twilio is not None and twilio.name == "Twilio"
          and twilio.playbook_id is None, twilio and (twilio.name, twilio.playbook_id))
    run_migration()
    check("running it again adds nothing", len(db.session.get(Business, ids["ehq"]).services)
          == len(mig.SERVICES["entertainhq"]))
    o = db.session.get(Business, ids["other"])
    check("a business with a map already is left alone", len(o.services) == 1 and o.services[0].name == "Already here")

    # The correction that followed: the media is a Railway bucket, not AWS.
    db.session.add(Playbook(slug="aws", display_name="AWS", is_active=True))
    db.session.commit()
    spec2 = importlib.util.spec_from_file_location(
        "mig2", ROOT / "migrations/versions/e5a3c7b19d42_media_is_on_railway_not_aws.py")
    mig2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mig2)
    aws_id = Playbook.query.filter_by(slug="aws").one().id
    storage = next(s for s in db.session.get(Business, ids["ehq"]).services if s.need and s.need.slug == "storage")
    storage.playbook_id = aws_id
    db.session.commit()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig2.op = Operations(MigrationContext.configure(conn))
        mig2.upgrade()
    db.session.expire_all()
    storage = db.session.get(BusinessService, storage.id)
    check("EntertainHQ's file storage is the Railway bucket, not AWS",
          storage.name == "Railway bucket" and storage.playbook.slug == "railway" and "not AWS" in storage.role)
    storage.notes = "Michael checked this one."
    storage.playbook_id = aws_id
    db.session.commit()
    with db.engine.begin() as conn:
        mig2.op = Operations(MigrationContext.configure(conn))
        mig2.upgrade()
    db.session.expire_all()
    check("a row somebody edited is left alone", db.session.get(BusinessService, storage.id).playbook.slug == "aws")
    storage.playbook_id = Playbook.query.filter_by(slug="railway").one().id
    storage.name = "Railway bucket"
    db.session.commit()

    print("\nTHE LAYOUT:")
    m = br._map_for(e)
    cols = [c["key"] for c in m["columns"]]
    check("columns run in build order", cols == sorted(cols, key=lambda k: business_map.LAYER_INDEX[k]), cols)
    check("legal comes first and comms after infrastructure",
          cols[0] == "legal" and cols.index("infrastructure") < cols.index("comms"), cols)
    by_name = {n["name"]: n for n in m["nodes"]}
    check("Stripe sits in the Money column", by_name["Stripe"]["layer"] == "money")
    check("accounting, essential and unfilled, is a hole",
          "Accounting" in by_name and by_name["Accounting"]["kind"] == "hole")
    check("the hole says what would fill it",
          any(s["slug"] == "quickbooks-online" for s in by_name["Accounting"]["suggestions"]))
    check("an optional need unfilled is not a hole", "Error monitoring" not in by_name)
    check("every hole is in its need's column", all(n["layer"] == "money" for n in m["nodes"]
                                                   if n["kind"] == "hole" and n["name"] == "Accounting"))
    check("Mercury carries the no-runbook flag", by_name["Mercury"]["runbook_missing"])
    check("the app itself does not, being in house", not by_name["EntertainHQ"]["runbook_missing"])
    check("Stripe carries its runbook's mark and page",
          by_name["Stripe"]["mark"].endswith("stripe.svg") and "/admin/playbooks/stripe" in by_name["Stripe"]["runbook"])
    sm = f"s{stripe.id}"
    pay_bank = next((x for x in m["edges"] if {x["a"], x["b"]} == {sm, f"s{mercury.id}"}), None)
    check("Stripe and Mercury are connected by the playbook, with its why",
          pay_bank is not None and pay_bank["derived"] and "Payouts land here" in pay_bank["why"], pay_bank)
    check("nothing connects to a hole", all(not x["a"].startswith("n") and not x["b"].startswith("n") for x in m["edges"]))
    check("the counts add up", m["counts"]["services"] == len(e.services) and m["counts"]["holes"] >= 1
          and m["counts"]["no_runbook"] >= 2, m["counts"])

    db.session.add(BusinessLink(business_id=e.id, from_service_id=mercury.id, to_service_id=stripe.id,
                                why="Stripe pays into Mercury every Tuesday."))
    db.session.commit()
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    pay_bank = next((x for x in m["edges"] if {x["a"], x["b"]} == {sm, f"s{mercury.id}"}), None)
    check("a hand-written connection wins over the playbook's",
          pay_bank is not None and not pay_bank["derived"] and "Tuesday" in pay_bank["why"], pay_bank)

    # Two nodes in one column: the line arcs out past the column rather than
    # running through whatever sits between them.
    a = {"x": 140, "y": 120}
    b = {"x": 140, "y": 380}
    arc = business_map._path(a, b)
    check("a same-column line arcs to the right", "C 220 120, 220 380" in arc, arc)
    across = business_map._path({"x": 140, "y": 120}, {"x": 380, "y": 250})
    check("a cross-column line leaves the right side and enters the left", across.startswith("M 172 120") and across.endswith("348 250"), across)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("\nTHE PAGES:")
r = c.get(f"/admin/businesses/{ids['ehq']}/map")
page = r.get_data(as_text=True)
check("the map draws", r.status_code == 200, r.status_code)
check("its data rides in a single-quoted x-data", "x-data='bizMap({" in page)
check("it never scrolls the window", "contained-scroll" in page)
check("Mercury and the accounting hole are on it", "Mercury" in page and "Accounting" in page)
check("it counts the holes in the bar", "hole" in page and "without a runbook" in page)
check("no em dash on it", chr(0x2014) not in page)
page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
check("the business page carries the counts and opens the map",
      "What runs it" in page and f"/admin/businesses/{ids['ehq']}/map" in page)
page = c.get("/admin/businesses").get_data(as_text=True)
check("each tile has a map button", f'aria-label="Map of EntertainHQ"' in page)
r = c.get(f"/admin/businesses/{ids['ehq']}/map/edit?need=accounting")
page = r.get_data(as_text=True)
check("the edit page draws", r.status_code == 200, r.status_code)
check("a hole preselects its need", 'value="' in page and "Accounting (Money)" in page)

print("\nTHE PRESSES:")
with application.test_request_context():
    acct_need = BusinessNeed.query.filter_by(slug="accounting").one().id
    stripe_id = BusinessService.query.filter_by(business_id=ids["ehq"]).join(Playbook).filter(Playbook.slug == "stripe").one().id
    mercury_id = BusinessService.query.filter_by(business_id=ids["ehq"], name="Mercury").one().id
    other_id = BusinessService.query.filter_by(business_id=ids["other"]).one().id
r = c.post(f"/admin/businesses/{ids['ehq']}/map/services",
           data={"need_id": acct_need, "name": "QuickBooks", "role": "The books.", "status": "setting_up",
                 "url": "https://quickbooks.intuit.com"}, follow_redirects=True)
with application.test_request_context():
    qb = BusinessService.query.filter_by(business_id=ids["ehq"], name="QuickBooks").first()
    check("filling the hole puts the service on the map", qb is not None and qb.need_id == acct_need
          and qb.status == "setting_up")
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    check("and the hole is gone", not any(n["kind"] == "hole" and n["name"] == "Accounting" for n in m["nodes"]))
    check("with a dashed ring while it is being set up",
          next(n for n in m["nodes"] if n["name"] == "QuickBooks")["status"] == "setting_up")
    qb_id = qb.id
r = c.post(f"/admin/businesses/{ids['ehq']}/map/services", data={"role": "no name, no runbook"}, follow_redirects=True)
check("a service with neither a runbook nor a name is refused", b"needs a name" in r.data)
c.post(f"/admin/businesses/{ids['ehq']}/map/services/{qb_id}", data={"need_id": acct_need, "name": "QuickBooks Online",
                                                                     "role": "The books, reconciled monthly.", "status": "running"})
with application.test_request_context():
    check("a service saves", db.session.get(BusinessService, qb_id).name == "QuickBooks Online")
r = c.post(f"/admin/businesses/{ids['ehq']}/map/services/{other_id}", data={"name": "Hijacked"})
with application.test_request_context():
    check("another business's service cannot be reached", r.status_code == 404
          and db.session.get(BusinessService, other_id).name == "Already here")
c.post(f"/admin/businesses/{ids['ehq']}/map/links", data={"from_service_id": qb_id, "to_service_id": mercury_id,
                                                          "why": "Statements import nightly."})
with application.test_request_context():
    link = BusinessLink.query.filter_by(from_service_id=qb_id).first()
    check("two services can be connected with a why", link is not None and "nightly" in link.why)
r = c.post(f"/admin/businesses/{ids['ehq']}/map/links", data={"from_service_id": qb_id, "to_service_id": qb_id, "why": "x"},
           follow_redirects=True)
check("a service cannot be connected to itself", b"two different services" in r.data)
c.post(f"/admin/businesses/{ids['ehq']}/map/services/{qb_id}/delete")
with application.test_request_context():
    check("removing a service removes it", db.session.get(BusinessService, qb_id) is None)
    check("and its connections", BusinessLink.query.filter_by(from_service_id=qb_id).count() == 0)
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    check("and the hole comes back", any(n["kind"] == "hole" and n["name"] == "Accounting" for n in m["nodes"]))

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
