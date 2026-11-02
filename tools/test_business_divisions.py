# -*- coding: utf-8 -*-
"""A business can be a division of another: Data Dungeon under Built by Bean.

Michael, 2026-11-02: Data Dungeon "is technically not its own business
because it sits under my Built by Bean LLC, but it effectively is a business
... kind of like a division." This boots the board on a throwaway SQLite
database and proves:

  1. The migration puts Data Dungeon on file as Built by Bean's division,
     wearing its My Apps icon, and running it again adds nothing.
  2. Businesses shows it as a tile of its own, straight after Built by Bean,
     saying whose it is.
  3. Its page points at its parent instead of carrying a tax card, and the
     parent's page lists it.
  4. It is never a row on the returns pages or the guide: its sales are on
     Built by Bean's return, and a second set of returns would file them twice.
  5. A division never counts the board's invoices as its revenue, which are
     its parent's takings.
  6. The form: a business can be made a division and back, and making one
     keeps its tax numbers rather than wiping them. A division cannot have
     divisions, and a company with divisions cannot become one.

Run: python tools/test_business_divisions.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-divisions-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, AppLink, Business, User  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])   # never touch Stripe from a test
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 12345.0}

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def run_migration():
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/f3b9d27c4e18_data_dungeon_a_division.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    dd_app = AppLink(name="Data Dungeon", url="https://datadungeon.example.test", icon_file="dd.png")
    db.session.add_all([boss, dd_app, AppLink(name="Other", url="https://other.example.test")])
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   texas_taxpayer_number="32093304155", sales_tax_webfile="RT123456",
                   sales_tax_first_sale=date(2026, 4, 9), sales_source="board", formed_on=date(2024, 1, 17))
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   texas_taxpayer_number="32108463343", sales_source="manual")
    db.session.add_all([bbb, ehq])
    db.session.commit()
    ids = dict(boss=boss.id, bbb=bbb.id, ehq=ehq.id, dd_app=dd_app.id)

    print("THE MIGRATION:")
    run_migration()
    dd = Business.query.filter_by(slug="data-dungeon").first()
    check("Data Dungeon is on file", dd is not None)
    check("as Built by Bean's division", dd and dd.parent_id == ids["bbb"])
    check("wearing its My Apps icon", dd and dd.logo_app_id == ids["dd_app"])
    check("with nothing of its own to file", dd and not dd.texas_taxpayer_number
          and dd.sales_tax_first_sale is None and dd.sales_source == "manual")
    run_migration()
    check("running it again adds nothing", Business.query.filter_by(slug="data-dungeon").count() == 1)
    ids["dd"] = dd.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("\nBUSINESSES:")
page = c.get("/admin/businesses").get_data(as_text=True)
check("the page draws", "Data Dungeon" in page)
order = [page.find(n) for n in ("Built by Bean", "Data Dungeon", "EntertainHQ")]
check("it sits straight after Built by Bean", order[0] < order[1] < order[2], order)
check("and says whose it is", "Part of Built by Bean" in page)
check("Built by Bean still shows the board's revenue", "$12,345.00" in page)
check("Data Dungeon does not show it a second time", page.count("$12,345.00") == 1, page.count("$12,345.00"))

print("\nITS PAGE, AND ITS PARENT'S:")
r = c.get(f"/admin/businesses/{ids['dd']}")
page = r.get_data(as_text=True)
check("its page draws", r.status_code == 200, r.status_code)
check("it points at Built by Bean", f"/admin/businesses/{ids['bbb']}" in page and "Part of" in page)
check("with no tax card of its own", "Texas taxpayer number" not in page and "eSystems" not in page)
page = c.get(f"/admin/businesses/{ids['bbb']}").get_data(as_text=True)
check("Built by Bean's page lists it", "Divisions" in page and f"/admin/businesses/{ids['dd']}" in page)
check("and keeps its own tax card", "Texas taxpayer number" in page)

print("\nTHE RETURNS:")
page = c.get("/admin/taxes/sales/returns").get_data(as_text=True)
check("the returns list draws", "Built by Bean" in page)
check("Data Dungeon is not on it", "Data Dungeon" not in page)
page = c.get("/admin/taxes/sales/guide").get_data(as_text=True)
check("nor in the guide", "Data Dungeon" not in page)

print("\nTHE FORM:")
page = c.get(f"/admin/businesses/{ids['dd']}/edit").get_data(as_text=True)
check("the form offers Part of", "A division of Built by Bean" in page)
check("and never offers a division as a parent", "A division of Data Dungeon" not in page)
check("its x-data sits in single quotes", "x-data='{ parent: \"" in page)


def save(bid, **over):
    with application.app_context():
        b = db.session.get(Business, bid)
        form = {"name": b.name, "short_name": b.short_name or "", "slug": b.slug,
                "texas_taxpayer_number": b.texas_taxpayer_number or "",
                "sales_tax_webfile": b.sales_tax_webfile or "",
                "sales_tax_first_sale": b.sales_tax_first_sale.isoformat() if b.sales_tax_first_sale else "",
                "sales_source": b.sales_source, "is_active": "1",
                "parent_id": str(b.parent_id or "")}
    form.update(over)
    return c.post(f"/admin/businesses/{bid}/edit", data=form)


save(ids["ehq"], parent_id=str(ids["bbb"]), sales_source="board")
with application.app_context():
    e = db.session.get(Business, ids["ehq"])
    check("a business can be made a division", e.parent_id == ids["bbb"])
    check("making one keeps its taxpayer number", e.texas_taxpayer_number == "32108463343")
    check("and a division can never count the board's invoices", e.sales_source == "manual", e.sales_source)
save(ids["ehq"], parent_id="")
with application.app_context():
    check("and put back as its own company", db.session.get(Business, ids["ehq"]).parent_id is None)

save(ids["bbb"], parent_id=str(ids["ehq"]))
with application.app_context():
    check("a company with divisions cannot become one", db.session.get(Business, ids["bbb"]).parent_id is None)
save(ids["ehq"], parent_id=str(ids["dd"]))
with application.app_context():
    check("a division cannot have divisions", db.session.get(Business, ids["ehq"]).parent_id is None)

with application.app_context():
    dd = db.session.get(Business, ids["dd"])
    dd.sales_source = "board"   # written somewhere other than the form
    db.session.commit()
    check("even a stray board source counts nothing for a division", br.lifetime_revenue(dd) is None)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
