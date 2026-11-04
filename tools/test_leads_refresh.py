# -*- coding: utf-8 -*-
"""The lead list refreshes itself, weekly, inside the nightly job.

docs/automation_gaps.md item 17. Proves, with every public source faked:

  1. The step is due when no night in the last week finished it, and not due
     after one did; a "not due" night or a failed one does not count.
  2. An import where a source came back empty (Overture with no DuckDB, the
     shape every cost-sync night has) prunes NOTHING, and keeps the marks of
     the source it did not read. Before, it would have deleted every unworked
     lead only that source supplied.
  3. The refresh imports, looks for websites on the new rows, and reads the
     sites of the new rows only, never an old row's.
  4. Run through night_log like the real night, the second night says not due.

Run: python tools/test_leads_refresh.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-leads-refresh-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("LEADS_REFRESH_FORCE", None)
os.environ.pop("LEADS_REFRESH_DISABLED", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "MAIL_SYNC_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Lead, NightRun  # noqa: E402
import check_websites  # noqa: E402
import enrich_sites  # noqa: E402
import import_leads  # noqa: E402
import leads_refresh  # noqa: E402
import night_log  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def permit(name, address, tpn):
    return {"outlet_name": name, "taxpayer_name": name, "outlet_address": address,
            "outlet_city": "PARIS", "outlet_state": "TX", "outlet_zip_code": "75460",
            "outlet_county_code": "139", "outlet_naics_code": "722511",
            "taxpayer_number": tpn, "outlet_first_sales_date": "2026-06-01T00:00:00.000"}


PERMITS = [permit("BLUE DOOR DINER", "12 MAIN ST", "1"),
           permit("RED BARN BAKERY", "40 LAMAR AVE", "2")]
# Every source but the permits comes back empty: Overture has no DuckDB on
# cost-sync, and any other source can fail on a given night.
import_leads.get_permits = lambda cache: list(PERMITS)
for getter in ("get_franchise", "get_osm", "get_npi", "get_overture",
               "get_licences", "get_salons"):
    setattr(import_leads, getter, lambda cache: [])
import_leads.get_carriers = lambda cache, towns: []
import_leads.statewide_locations = lambda numbers: {}

LOOKED, READ = [], []
check_websites.look = lambda name, city: (LOOKED.append(name), "https://bluedoordiner.test" if "Blue" in name else "")[1]


def fake_read(site, name):
    READ.append(name)
    return {"emails": ["hello@bluedoordiner.test"], "phones": [], "people": [],
            "employees": None, "revenue": None, "pages": 1}


enrich_sites.read_site = fake_read

NOW = datetime.now(timezone.utc)

with application.app_context():
    db.create_all()
    # A place only Overture knew, never worked: the row a partial read deleted.
    db.session.add(Lead(dedupe_key="lake cafe|1 lake rd", name="Lake Cafe", stage="lead",
                        sources="overture", website="https://lakecafe.test",
                        website_checked_at=NOW - timedelta(days=200)))
    # An old row whose site was never read well: not fetched again weekly.
    db.session.add(Lead(dedupe_key="old shop|9 elm st", name="Old Shop", stage="lead",
                        sources="comptroller", website="https://oldshop.test",
                        website_checked_at=NOW - timedelta(days=90)))
    db.session.commit()

print("1. When it is due")
with application.app_context():
    check("due on a board that has never run it", leads_refresh.due()[0])

    def night(days_ago, ok=True, note="3 new"):
        run = NightRun(status="ok", started_at=(NOW - timedelta(days=days_ago)).replace(tzinfo=None))
        run.steps = [{"name": "leads refresh", "ok": ok, "note": note, "seconds": 1}]
        db.session.add(run)
        db.session.commit()
        return run

    a = night(2)
    check("not due two days after a night finished it", not leads_refresh.due()[0])
    db.session.delete(a)
    b = night(8)
    check("due again after a week", leads_refresh.due()[0])
    c = night(1, note="not due: last ran 2026-10-28")
    check("a night that only said 'not due' does not count", leads_refresh.due()[0])
    d = night(1, ok=False, note="URLError")
    check("nor does a night where it failed", leads_refresh.due()[0])
    for r in (b, c, d):
        db.session.delete(r)
    db.session.commit()

print("2. A partial read prunes nothing")
with application.app_context():
    got = import_leads.run(enrich=False, app=application)
    lake = Lead.query.filter_by(name="Lake Cafe").first()
    check("the import names what it did not read", "overture" in got["unread"], got.get("unread"))
    check("THE POINT: the Overture-only lead survives a read without Overture",
          lake is not None and got["removed"] == 0, got)
    check("and keeps its Overture mark", lake is not None and "overture" in (lake.sources or ""))
    check("the permits still made their leads", got["made"] == 2, got)

print("3. The refresh, new rows only")
LOOKED.clear()
READ.clear()
with application.app_context():
    db.session.query(Lead).filter(Lead.name.in_(["Blue Door Diner", "Red Barn Bakery"])).delete(
        synchronize_session=False)
    db.session.commit()
    line = leads_refresh.refresh(application)
    blue = Lead.query.filter_by(name="Blue Door Diner").first()
    red = Lead.query.filter_by(name="Red Barn Bakery").first()
    check("websites are looked for on the new rows only",
          sorted(LOOKED) == ["Blue Door Diner", "Red Barn Bakery"], LOOKED)
    check("a found site is kept and the row marked checked",
          blue.website == "https://bluedoordiner.test" and blue.website_checked_at is not None
          and red.website_checked_at is not None)
    check("only the new row's site is read, never an old row's", READ == ["Blue Door Diner"], READ)
    check("and what it read is on the row", blue.email == "hello@bluedoordiner.test")
    check("the night's line says what happened and what was not read",
          "2 new" in line and "1 found" in line and "not read" in line, line)

print("4. Inside the night")
with application.app_context():
    for run in NightRun.query.all():
        db.session.delete(run)
    db.session.commit()
first = night_log.Night(application)
first.step("leads refresh", lambda: leads_refresh.main(application))
first.finish()
second = night_log.Night(application)
note = second.step("leads refresh", lambda: leads_refresh.main(application))
second.finish()
check("the first night runs it", first.steps[0]["ok"] and not first.steps[0]["note"].startswith("not due"),
      first.steps[0])
check("the next night says it is not due", str(note).startswith("not due"), note)
os.environ["LEADS_REFRESH_FORCE"] = "1"
with application.app_context():
    check("LEADS_REFRESH_FORCE makes it due", leads_refresh.due()[0])
os.environ.pop("LEADS_REFRESH_FORCE")
import sync_costs  # noqa: E402
check("the nightly sweep runs it", '"leads_refresh", "leads refresh"' in open(
    sync_costs.__file__, encoding="utf-8").read())

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
