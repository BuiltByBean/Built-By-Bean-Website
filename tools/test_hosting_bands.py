# -*- coding: utf-8 -*-
"""The hosting page's bands, and what the Needs a look tile counts.

The page read "Needs a look: 1" with a matching badge in the sidebar while
every row on it said Hosted free or Fine, and the one row being counted
offered no press at all. `_status` folded "no fee agreed" into the loss band,
so a project hosted free at $0.00 a month and costing $0.00 to run was filed
as a fee to raise. It cannot be raised, and there was nothing to look at.

What is proved:

  1. Each band is what it says: free, fine, raise, loss.
  2. THE POINT: a project hosted free that costs nothing is NOT counted, on
     the tile or in the sidebar badge, and the two agree with each other.
  3. Free stops being free the moment it costs something, and then it IS
     counted, because free to the client never meant paid for out of pocket.
  4. Every row the tile counts offers the press that acts on it. A number
     asking to be looked at, above a page with nothing to look at, is the
     whole defect.
  5. Every band has a colour. The template looks its tone up by key, so a
     band nobody styled is a 500, not a grey pill.

Run: python tools/test_hosting_bands.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-hosting-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Client, Project, User  # noqa: E402
import pm.hosting_routes as hosting  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("THE BANDS:")
BANDS = [
    ("hosted free, costing nothing", 0, 0.0, "free", False),
    ("hosted free, costing money", 0, 12.40, "loss", True),
    ("no fee at all, costing nothing", None, 0.0, "free", False),
    ("$50 fee, $22.30 of cost", 50.0, 22.30, "fine", False),
    ("$50 fee, $30 of cost", 50.0, 30.00, "raise", True),
    ("$50 fee, $60 of cost", 50.0, 60.00, "loss", True),
    ("$50 fee, nothing recorded", 50.0, 0.0, "fine", False),
]
for label, fee, cost, want_key, want_counted in BANDS:
    key, said = hosting._status(fee, cost)
    check(f"{label} reads {want_key} ({said})", key == want_key, key)
    check(f"   and is {'counted' if want_counted else 'left alone'}",
          (key in ("loss", "raise")) == want_counted, key)

check("every band has a colour in the template",
      set(["free", "fine", "raise", "loss"]) <= set(hosting.STATUS_ORDER),
      hosting.STATUS_ORDER)


# Stripe is a network call and this is about arithmetic, not revenue.
hosting.__dict__.setdefault("_real_revenue", None)
import stripe_service  # noqa: E402
stripe_service.get_hosting_revenue = lambda: {
    "collected": 0.0, "outstanding": 0.0, "paid_invoices": 0, "by_customer": {}}

# The costs would come from the service ledger; each project's is set here so
# a band can be aimed at exactly.
COSTS = {}
hosting._costs_by_project = lambda months: (
    {pid: {months[-1]: amount} for pid, amount in COSTS.items()},
    {})
hosting._railway_lifetime_by_project = lambda: {}
hosting._railway_all_time = lambda: {"amount": 0.0, "source": "invoices", "months": 0}


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    made = {}
    for name, fee in (("Free And Idle", 0.0), ("Free And Costly", 0.0),
                      ("Healthy", 50.0), ("Thin", 50.0)):
        client = Client(name=name + " Ltd", email=f"{len(made)}@example.test")
        db.session.add(client)
        db.session.flush()
        project = Project(name=name, client_id=client.id,
                          hosting_fee=fee, hosting_cycle="monthly",
                          created_at=datetime.now(timezone.utc))
        db.session.add(project)
        db.session.flush()
        made[name] = project.id
    db.session.commit()
    boss_id = boss.id

COSTS.update({made["Free And Idle"]: 0.0, made["Free And Costly"]: 12.40,
              made["Healthy"]: 22.30, made["Thin"]: 30.0})

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

print("\nTHE PAGE:")
r = c.get("/admin/hosting/")
page = r.data.decode("utf-8", "replace")
check("it draws with every band on it", r.status_code == 200, r.status_code)
check("the free one says so", "Hosted free" in page)
check("the thin one asks to be raised", "Raise it" in page)
check("the healthy one does not", page.count("Raise it") == 1, page.count("Raise it"))

import re  # noqa: E402
tile = re.search(r"Needs a look.*?>(\d+)<", page, re.S)
counted = int(tile.group(1)) if tile else -1
print(f"\nTHE TILE SAYS {counted}:")
check("THE POINT: a free project costing nothing is not one of them",
      counted == 2, counted)
with application.app_context():
    hosting._DUE_CACHE.update(at=0.0, rows=[])
    badge = hosting.increases_due_count()
check("and the sidebar badge agrees with the tile", badge == counted, (badge, counted))
with application.app_context():
    hosting._DUE_CACHE.update(at=0.0, rows=[])
    names = sorted(row["project_name"] for row in hosting.increases_due())
check("it is the thin one and the costly free one, by name",
      names == ["Free And Costly", "Thin"], names)

print("\nEVERY COUNTED ROW OFFERS THE PRESS:")
drafts = page.count("/admin/contracts/new/hosting")
check("as many draft links as the tile counts", drafts == counted, (drafts, counted))
check("including the free one that started costing money",
      "Put it on" in page, "no press on a free row that costs money")

print("\nNOTHING TO SEE WHEN NOTHING IS WRONG:")
COSTS[made["Thin"]] = 5.0
COSTS[made["Free And Costly"]] = 0.0
page = c.get("/admin/hosting/").data.decode("utf-8", "replace")
tile = re.search(r"Needs a look.*?>(\d+)<", page, re.S)
check("the tile drops to zero", tile and tile.group(1) == "0",
      tile.group(1) if tile else None)
check("and no row offers a draft", "/admin/contracts/new/hosting" not in page)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
