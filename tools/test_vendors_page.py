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
                    BankConnection, BankTransaction, ServiceCostEntry, Playbook, BusinessNode, Expense)
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
        line = BankTransaction(connection_id=c.id, business_id=c.business_id, external_id=f"t{n}",
                               amount=amount, occurred_on=TODAY - timedelta(days=days_ago),
                               counterparty=pattern, disposition=rules[pattern].disposition,
                               rule_id=rules[pattern].id, status="sent")
        db.session.add(line)
        db.session.flush()
        # The books: what each company was charged (the bank line books it).
        db.session.add(Expense(amount=-amount, date=line.occurred_on, description=rules[pattern].vendor,
                               category=rules[pattern].category, business_id=c.business_id, bank_line_id=line.id))
    # Michael, 2026-11-06: EntertainHQ has its own Claude plan, and LegalZoom
    # formed both LLCs. Neither has a bank rule of its own company.
    db.session.add_all([
        Expense(amount=105.40, date=TODAY - timedelta(days=19), description="Claude, EntertainHQ Max plan",
                category="ai_services", business_id=ehq.id, paid_by="Michael Bean"),
        Expense(amount=301.0, date=TODAY - timedelta(days=33), description="LegalZoom",
                category="taxes_licenses", business_id=ehq.id, paid_by="Michael Bean"),
    ])
    db.session.commit()
    ids = SimpleNamespace(boss=boss.id, ehq=ehq.id, twilio_jd=twilio_jd.id, aws=aws.id)

    print("1. found in every company's books")
    lines = vendor_discovery.from_books(TODAY)
    rows = ServiceProvider.query.filter_by(name="bank").all()
    found = {p.vendor_name: p for p in rows if p.account_business_id is None}
    ehq_found = {p.vendor_name: p for p in rows if p.account_business_id == ids.ehq}
    check("OpenAI, LegalZoom and Twilio's own account are found for Built by Bean",
          set(found) == {"OpenAI ChatGPT", "LegalZoom", "Twilio"}, (set(found), lines))
    check("EntertainHQ's own Claude plan, LegalZoom and Google Workspace are found for EntertainHQ",
          set(ehq_found) == {"Claude", "LegalZoom", "Google Workspace"}, set(ehq_found))
    check("each costs what its own company paid",
          vendor_discovery.spend(ehq_found["Claude"], TODAY) == 105.40
          and vendor_discovery.spend(ehq_found["LegalZoom"], TODAY) == 301.0
          and vendor_discovery.spend(found["LegalZoom"], TODAY) == 299.0)
    found["Google Workspace"] = ehq_found["Google Workspace"]
    check("Google Workspace is EntertainHQ's", found["Google Workspace"].account_business_id == ids.ehq)
    check("OpenAI is Built by Bean's", found["OpenAI ChatGPT"].account_business_id is None)
    check("Twilio paid by Built by Bean is a second Twilio account beside Kenali's",
          found["Twilio"].account_client_id is None and found["Twilio"].account_business_id is None)
    check("one charge 200 days ago may be yearly, so it stays in use", found["LegalZoom"].is_active is True)
    check("a charged one is in use", found["OpenAI ChatGPT"].is_active is True)
    check("meals are not a vendor, and a rule nothing matched adds nothing",
          "Chuy's" not in found and "Never Charged" not in found)
    check("a vendor that already has its account is not added again", "Railway" not in found)
    check("it says where it found each", found["OpenAI ChatGPT"].discovered_from == "books: OpenAI ChatGPT")
    again = vendor_discovery.from_books(TODAY)
    check("a second night adds nothing", again == [] and ServiceProvider.query.filter_by(name="bank").count() == 6, again)
    later = vendor_discovery.from_books(TODAY + timedelta(days=95))
    check("charges stopping moves an account to Not in use on its own",
          db.session.get(ServiceProvider, found["OpenAI ChatGPT"].id).is_active is False, later)
    vendor_discovery.from_books(TODAY)
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
    check("found accounts say where from", "From the books" in page and "In the code" in page)
    check("a page to look at: no edit, delete or sync press on any account",
          "Sync now" not in page and "/delete" not in page and "Add account" not in page and "Sync all" not in page)
    check("only a refused key asks for a press", page.count("Fix the key") == 1)
    off = c.get("/admin/vendors/?view=not_in_use").get_data(as_text=True)
    check("Not in use has AWS, and LegalZoom is in use (EntertainHQ was charged this month)",
          'data-vendor="amazon web services"' in off and 'data-vendor="legalzoom"' not in off
          and 'data-vendor="legalzoom"' in page)
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
    check("Sync all finds vendors in the books too", "Found 1 new vendor account." in r
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
    check("no map links, only the playbook (Michael, 2026-11-06)", " map" not in tile("twilio").split("data-account")[0])
    check("a playbook pointed at an account finds it whatever its name",
          'data-playbook="railway"' in tile("railway"))
    check("OpenAI finds the LLM playbook by the words the night uses", 'data-playbook="llm-apis"' in tile("openai chatgpt"))
    check("a vendor with no runbook says so", "No playbook yet" in tile("google workspace"), tile("google workspace")[:300])
    pb_page = c.get("/admin/playbooks/twilio").get_data(as_text=True)
    check("the playbook's page lists the vendor's accounts and opens them",
          "2 accounts on Vendors" in pb_page and "#vendor-twilio" in pb_page)
    edit = c.get(f"/admin/service-costs/providers/{ids.twilio_jd}/edit").get_data(as_text=True)
    check("the edit form names the vendor and says In use", 'name="vendor"' in edit and "In use" in edit)

    print("5. found from the stores and from the code")
    from models import AppLink
    tile = AppLink(name="EntertainHQ", url="https://entertainhq.example", app_store_bundle_id="com.ehq.app",
                   play_package="com.ehq.app", github_url="https://github.com/mb/ehq")
    db.session.add(tile)
    db.session.flush()
    db.session.get(Business, ids.ehq).logo_app_id = tile.id
    db.session.commit()
    lines = vendor_discovery.from_stores()
    apple = ServiceProvider.query.filter_by(vendor="Apple Developer Program").one_or_none()
    check("an app on the App Store is an Apple Developer Program account", apple is not None, lines)
    check("paid by the company whose app it is", apple and apple.account_business_id == ids.ehq)
    check("and says it came from the store", apple and apple.discovered_from.startswith("store:"))
    check("an app on Google Play is a Google Play account",
          ServiceProvider.query.filter_by(vendor="Google Play").count() == 1)
    check("a second pass adds nothing", vendor_discovery.from_stores() == [])
    added = vendor_discovery.note_repo("mb/ehq", {
        "app.py": "import os" + chr(10) + "RESEND_API_KEY = os.environ['RESEND_API_KEY']" + chr(10),
        "package.json": '{"dependencies": {"@sentry/browser": "7"}}',
        "config.py": "ONESIGNAL_APP_ID = ''",
        "docs/vendors.py": "POSTMARK_SERVER_TOKEN = 1",
        "tests/test_mail.py": "MAILGUN_API_KEY = 1",
        "node_modules/x/index.js": "process.env.SUPABASE_URL",
    })
    db.session.commit()
    check("the code's own vendors are found, one that has an account is left", sorted(added) == ["OneSignal", "Resend"]
          and ServiceProvider.query.filter_by(vendor="Sentry").count() == 1, added)
    check("never from docs, tests or dependencies",
          not ServiceProvider.query.filter(ServiceProvider.vendor.in_(["Postmark", "Mailgun", "Supabase"])).count())
    check("paid by the company whose repo it is",
          ServiceProvider.query.filter_by(vendor="Resend").one().account_business_id == ids.ehq)
    page = c.get("/admin/vendors/").get_data(as_text=True)
    check("the store's account says so on the page", "From the store" in page and "EntertainHQ on the App Store" in page)

    print("6. the books stand: rhythm, stand-ins, the old reading's leftovers")
    check("a yearly membership is in use five months on", vendor_discovery.in_use_by_rhythm([TODAY - timedelta(days=145)], TODAY))
    check("a monthly one that stopped is not",
          not vendor_discovery.in_use_by_rhythm([TODAY - timedelta(days=d) for d in (190, 160, 130)], TODAY))
    check("a monthly one still charging is",
          vendor_discovery.in_use_by_rhythm([TODAY - timedelta(days=d) for d in (65, 35, 5)], TODAY))
    # Apple's membership paid by Built by Bean, booked whole (the line points
    # at its expense), while the store's stand-in sits under the DBA.
    dd = Business(name="Data Dungeon", slug="dd", sales_source="manual", parent_id=db.session.get(Business, ids.ehq).id)
    db.session.add(dd)
    db.session.flush()
    stand_in = ServiceProvider(name="code", display_name="Apple Developer Program", vendor="Apple Developer Program",
                               credentials_json="{}", discovered_from="store: Data Dungeon on the App Store",
                               account_business_id=dd.id)
    ServiceProvider.query.filter_by(vendor="Apple Developer Program").delete()
    db.session.add(stand_in)
    exp = Expense(amount=107.17, date=TODAY - timedelta(days=145), description="Apple Developer Program",
                  category="software", business_id=ids.ehq)
    db.session.add(exp)
    db.session.flush()
    db.session.add(BankTransaction(connection_id=conn.id, business_id=conn.business_id, external_id="apple",
                                   amount=-107.17, occurred_on=exp.date, counterparty="APPLE.COM/US",
                                   disposition="expense", expense_id=exp.id, status="sent"))
    stale = ServiceProvider(name="bank", display_name="Google Play", vendor="Google Play", credentials_json="{}",
                            discovered_from="bank: GOOGLE PLAY")
    kept = ServiceProvider(name="bank", display_name="LegalZoom", vendor="LegalZoom", credentials_json="{}",
                           discovered_from="mail: order 1, $301.00 on 2024-01-17", account_business_id=None,
                           is_active=False)
    ServiceProvider.query.filter_by(name="bank", vendor="LegalZoom", account_business_id=None).delete()
    db.session.add_all([stale, kept])
    db.session.commit()
    STALE, KEPT, STAND = stale.id, kept.id, stand_in.id
    lines = vendor_discovery.from_books(TODAY)
    apple = [a for a in ServiceProvider.query.filter_by(vendor="Apple Developer Program").all()]
    check("Apple's membership is one account, paid by its company, in use, at what it cost",
          len(apple) == 1 and apple[0].name == "bank" and apple[0].is_active
          and vendor_discovery.spend(apple[0], TODAY) == 107.17, [(a.name, a.account_business_id, a.is_active) for a in apple])
    check("the store's stand-in under the DBA gave way to it", db.session.get(ServiceProvider, STAND) is None, lines)
    tile_dd = AppLink(name="Data Dungeon", url="https://dd.example", app_store_bundle_id="com.dd.app")
    db.session.add(tile_dd)
    db.session.flush()
    dd.logo_app_id = tile_dd.id
    db.session.commit()
    vendor_discovery.from_stores()
    check("a DBA's App Store listing never makes an account of its own",
          ServiceProvider.query.filter_by(vendor="Apple Developer Program", account_business_id=dd.id).count() == 0)
    check("an account the old reading made for a company never charged is taken off",
          db.session.get(ServiceProvider, STALE) is None)
    check("an account kept by its mail evidence stays", db.session.get(ServiceProvider, KEPT) is not None)
    page = c.get("/admin/vendors/?view=in_use").get_data(as_text=True)
    check("and says it is from the mail", "From the mail" in page and "2024-01-17" in page)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
