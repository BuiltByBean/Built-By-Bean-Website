"""Vendors: its own page, one tile per vendor, found and kept by itself.

Michael, 2026-11-05: Vendors was a tab of Hosting, AWS (stopped in July) sat
beside the live ones, vendors he pays had no tile, Twilio's three accounts
had one, and its sync said "401 Client Error: Unauthorized for url: ...".
His picks: its own Finances link, one tile per vendor with its accounts under
it, Not in use as a tab, and vendors the board spots added on their own.

    python tools/test_vendors_page.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-vendors-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, User, Client, Business, ServiceProvider, VendorRule,  # noqa: E402
                    BankConnection, BankTransaction, ServiceCostEntry, Playbook, BusinessNode)
import vendor_discovery  # noqa: E402
import service_costs_service  # noqa: E402

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False
FAIL = []
TODAY = date(2026, 11, 5)


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}   {name}" + ("" if cond else f"  [{str(detail)[:300]}]"))
    if not cond:
        FAIL.append(name)


with app.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", slug="builtbybean", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", slug="entertainhq", sales_source="manual")
    kenali = Client(name="Kenali Kendrick", email="k@example.test")
    db.session.add_all([boss, bbb, ehq, kenali])
    db.session.flush()
    twilio_jd = ServiceProvider(name="twilio", display_name="Twilio", account_client_id=kenali.id,
                                account_label="J&D Entertainment", credentials_json="{}",
                                sync_error="401 Client Error: Unauthorized for url: https://api.twilio.com/x",
                                last_sync_at=datetime(2026, 11, 5, tzinfo=timezone.utc))
    railway = ServiceProvider(name="railway", display_name="Railway", credentials_json="{}",
                              last_sync_at=datetime(2026, 11, 5, tzinfo=timezone.utc))
    railway_ehq = ServiceProvider(name="railway", display_name="Railway (EntertainHQ)", credentials_json="{}",
                                  account_business_id=ehq.id)
    claude = ServiceProvider(name="flat", display_name="Claude", credentials_json="{}", monthly_cost=100.0)
    aws = ServiceProvider(name="aws", display_name="Amazon Web Services", credentials_json="{}", is_active=False)
    db.session.add_all([twilio_jd, railway, railway_ehq, claude, aws])
    db.session.flush()
    # Michael, the same day: "ensure the vendors page uses the service icons
    # I know we already have ... a vendor will connect to a service that we
    # have a blueprint for". A playbook is one vendor's runbook and mark.
    pb_twilio = Playbook(slug="twilio", display_name="Twilio", logo_path="img/vendors/twilio.svg")
    pb_llm = Playbook(slug="llm-apis", display_name="LLM APIs")
    pb_railway = Playbook(slug="railway", display_name="Railway hosting", service_provider_id=railway.id)
    db.session.add_all([pb_twilio, pb_llm, pb_railway])
    db.session.flush()
    db.session.add(BusinessNode(business_id=ehq.id, kind="service", name="Texting", playbook_id=pb_twilio.id))
    db.session.add(ServiceCostEntry(provider_id=railway.id, resource_identifier="railway:x",
                                    period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
                                    raw_amount=52.38, allocated_amount=52.38))

    conn = BankConnection(business_id=bbb.id, token="secret-token:x")
    conn_ehq = BankConnection(business_id=ehq.id, token="secret-token:y")
    db.session.add_all([conn, conn_ehq])
    db.session.flush()
    rules = {
        "OPENAI": VendorRule(pattern="OPENAI", vendor="OpenAI ChatGPT", disposition="expense",
                             business_id=bbb.id, category="ai_services"),
        "WORKSPACE ENTE": VendorRule(pattern="WORKSPACE ENTE", vendor="Google Workspace", disposition="expense",
                                     business_id=ehq.id, category="software"),
        "TWILIO": VendorRule(pattern="TWILIO", vendor="Twilio", disposition="expense",
                             business_id=bbb.id, category="service_cost"),
        "LEGALZOOM": VendorRule(pattern="LEGALZOOM", vendor="LegalZoom", disposition="expense",
                                business_id=bbb.id, category="legal_professional"),
        "CHUY S": VendorRule(pattern="CHUY S", vendor="Chuy's", disposition="expense",
                             business_id=bbb.id, category="meals"),
        "NEVER": VendorRule(pattern="NEVER", vendor="Never Charged", disposition="expense",
                            business_id=bbb.id, category="software"),
        "RAILWAY": VendorRule(pattern="RAILWAY", vendor="Railway", disposition="split", category="hosting"),
    }
    db.session.add_all(rules.values())
    db.session.flush()
    n = 0
    for pattern, days_ago, amount, c in (("OPENAI", 10, -20.0, conn), ("OPENAI", 40, -20.0, conn),
                                          ("WORKSPACE ENTE", 5, -14.0, conn_ehq), ("TWILIO", 20, -10.03, conn),
                                          ("LEGALZOOM", 200, -299.0, conn), ("CHUY S", 3, -30.0, conn),
                                          ("RAILWAY", 4, -52.38, conn)):
        n += 1
        db.session.add(BankTransaction(connection_id=c.id, business_id=c.business_id, external_id=f"t{n}",
                                       amount=amount, occurred_on=TODAY - timedelta(days=days_ago),
                                       counterparty=pattern, disposition=rules[pattern].disposition,
                                       rule_id=rules[pattern].id))
    db.session.commit()
    ids = SimpleNamespace(boss=boss.id, ehq=ehq.id, twilio_jd=twilio_jd.id, aws=aws.id)

    print("1. found on the bank")
    lines = vendor_discovery.from_bank(TODAY)
    found = {p.vendor_name: p for p in ServiceProvider.query.filter_by(name="bank").all()}
    check("OpenAI, Google Workspace, LegalZoom and Twilio's own account are found",
          set(found) == {"OpenAI ChatGPT", "Google Workspace", "LegalZoom", "Twilio"}, (set(found), lines))
    check("Google Workspace is EntertainHQ's", found["Google Workspace"].account_business_id == ids.ehq)
    check("OpenAI is Built by Bean's", found["OpenAI ChatGPT"].account_business_id is None)
    check("Twilio paid by Built by Bean is a second Twilio account beside Kenali's",
          found["Twilio"].account_client_id is None and found["Twilio"].account_business_id is None)
    check("a vendor not charged in 90 days is found Not in use", found["LegalZoom"].is_active is False)
    check("a charged one is in use", found["OpenAI ChatGPT"].is_active is True)
    check("meals are not a vendor, and a rule nothing matched adds nothing",
          "Chuy's" not in found and "Never Charged" not in found)
    check("a vendor that already has its account is not added again", "Railway" not in found)
    check("it says where it found each", found["OpenAI ChatGPT"].discovered_from == "bank: OPENAI")
    again = vendor_discovery.from_bank(TODAY)
    check("a second night adds nothing", again == [] and ServiceProvider.query.filter_by(name="bank").count() == 4, again)
    later = vendor_discovery.from_bank(TODAY + timedelta(days=95))
    check("charges stopping moves an account to Not in use on its own",
          db.session.get(ServiceProvider, found["OpenAI ChatGPT"].id).is_active is False, later)
    vendor_discovery.from_bank(TODAY)
    check("and back when they are in the window again",
          db.session.get(ServiceProvider, found["OpenAI ChatGPT"].id).is_active is True)
    check("a found account never syncs and never fails",
          service_costs_service.sync_provider(found["OpenAI ChatGPT"].id) == (0, None)
          and not db.session.get(ServiceProvider, found["OpenAI ChatGPT"].id).sync_error)
    check("what it cost is the bank's charges for it",
          vendor_discovery.spend(found["OpenAI ChatGPT"], TODAY) == 40.0, vendor_discovery.spend(found["OpenAI ChatGPT"], TODAY))

    print("2. found in the code")
    sentry = SimpleNamespace(display_name="Sentry")
    tw = SimpleNamespace(display_name="Twilio")
    b = db.session.get(Business, ids.ehq)
    check("a vendor the code uses with no account is added", vendor_discovery.note_code(sentry, b, ["mb/ehq"]) == "Sentry")
    db.session.commit()
    check("only once", vendor_discovery.note_code(sentry, b, ["mb/ehq"]) is None)
    check("never for a vendor that has an account", vendor_discovery.note_code(tw, b, ["mb/ehq"]) is None)
    s = ServiceProvider.query.filter_by(name="code").one()
    check("it says which repo", s.discovered_from == "code: mb/ehq" and s.account_business_id == ids.ehq)

    print("3. the page")
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(ids.boss)
        sess["_fresh"] = True
    page = c.get("/admin/vendors/").get_data(as_text=True)
    check("the page draws", "Vendors" in page and 'data-vendor="twilio"' in page)
    check("one Twilio tile with both accounts",
          page.count('data-vendor="twilio"') == 1 and "2 accounts" in page and "Kenali Kendrick" in page and "s card" in page)
    check("one Railway tile with both accounts", page.count('data-vendor="railway"') == 1)
    check("a 401 says what to do, not the URL",
          "Twilio turned the key down" in page and "api.twilio.com" not in page)
    check("its cost from the vendor's report", "$52.38" in page)
    check("AWS is not in use, so not here", 'data-vendor="amazon web services"' not in page)
    check("found accounts say where from", "From the bank" in page and "In the code, no account linked" in page)
    off = c.get("/admin/vendors/?view=not_in_use").get_data(as_text=True)
    check("Not in use has AWS and LegalZoom", 'data-vendor="amazon web services"' in off and 'data-vendor="legalzoom"' in off)
    r = c.get("/admin/service-costs/providers?view=not_in_use")
    check("the old address lands on the page", r.status_code == 301 and r.headers["Location"].endswith("/admin/vendors/?view=not_in_use"),
          (r.status_code, r.headers.get("Location")))
    hosting = c.get("/admin/hosting/").get_data(as_text=True)
    check("Hosting has no Vendors tab any more", "/admin/vendors" not in hosting.split('id="pm-main"')[-1])
    check("the sidebar has Vendors, with one failing account on its badge",
          'href="/admin/vendors/"' in hosting and "Vendors" in hosting)
    with app.test_request_context():
        from flask_login import login_user
        login_user(db.session.get(User, ids.boss))
        ctx = {}
        for fn in app.template_context_processors[None]:
            ctx.update(fn())
    check("the badge counts the one in use account whose sync failed", ctx.get("vendors_failing") == 1, ctx.get("vendors_failing"))
    import service_costs_service as scs
    scs_sync = scs.sync_provider
    import pm.service_costs_routes as routes
    routes.sync_provider = lambda pid: (0, None)
    db.session.delete(ServiceProvider.query.filter_by(name="bank", vendor="OpenAI ChatGPT").one())
    db.session.commit()
    r = c.post("/admin/service-costs/sync-all", follow_redirects=True).get_data(as_text=True)
    check("Sync all finds vendors on the bank too", "Found 1 new vendor account on the bank" in r
          and ServiceProvider.query.filter_by(name="bank", vendor="OpenAI ChatGPT").count() == 1)
    routes.sync_provider = scs_sync
    print("4. a vendor knows its playbook, its mark and its maps")
    page = c.get("/admin/vendors/").get_data(as_text=True)
    import re as _re
    def tile(k):
        m = _re.search(rf'data-vendor="{k}"(.*?)(?=<section |\Z)', page, _re.S)
        return m.group(1) if m else ""
    check("Twilio wears its playbook's mark and opens it",
          "img/vendors/twilio.svg" in tile("twilio") and 'data-playbook="twilio"' in tile("twilio"), tile("twilio")[:400])
    check("and names the map it is a service on", "EntertainHQ LLC map" in tile("twilio"))
    check("a playbook pointed at an account finds it whatever its name",
          'data-playbook="railway"' in tile("railway"))
    check("OpenAI finds the LLM playbook by the words the night uses", 'data-playbook="llm-apis"' in tile("openai chatgpt"))
    check("a vendor with no runbook says so", "No playbook yet" in tile("google workspace"), tile("google workspace")[:300])
    pb_page = c.get("/admin/playbooks/twilio").get_data(as_text=True)
    check("the playbook's page lists the vendor's accounts and opens them",
          "2 accounts on Vendors" in pb_page and "#vendor-twilio" in pb_page)
    edit = c.get(f"/admin/service-costs/providers/{ids.twilio_jd}/edit").get_data(as_text=True)
    check("the edit form names the vendor and says In use", 'name="vendor"' in edit and "In use" in edit)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
