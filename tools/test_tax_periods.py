# -*- coding: utf-8 -*-
"""Audit faults 4 and 5: when returns are counted from, and how often.

  4. A blank first sale used to hide every return the business owed. Now the
     count starts from the permit's registration, then the earliest return
     filed, then the first location's opening, and the pages say so plainly
     when none of them is on file.
  5. The form offered monthly and yearly and every function was quarterly.
     A month and a year now have their own bounds, label and due date (the
     20th after, rolled like a quarter), a return page each, and a return
     filed under one frequency stays listed after the business moves to
     another. Every quarterly code, URL and due date is unchanged.

Run: python tools/test_tax_periods.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-periods-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Business, BusinessLocation, SalesTaxFiling, User  # noqa: E402
import sales_tax as st  # noqa: E402
import pm.business_routes as br  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("5. FREQUENCY")
check("quarters are as they were", st.periods_owed(date(2026, 4, 9), date(2026, 11, 4))
      == [(2026, 2), (2026, 3), (2026, 4)])
check("and so is a quarter's code and due date",
      st.period_code(2026, 2) == "262" and st.due_date(2026, 2) == date(2026, 7, 20))
months = st.periods_owed(date(2026, 9, 18), date(2026, 11, 4), "monthly")
check("monthly is one period a month", months == [(2026, 109), (2026, 110), (2026, 111)], months)
check("a month's bounds", st.quarter_bounds(2026, 102) == (date(2026, 2, 1), date(2026, 2, 28)))
check("a month's label", st.period_label(2026, 110) == "Oct 2026", st.period_label(2026, 110))
check("a month is due the 20th after it", st.due_date(2026, 110) == date(2026, 11, 20))
check("May 2026 rolls off a Saturday to Monday June 22", st.due_date(2026, 105) == date(2026, 6, 22),
      st.due_date(2026, 105))
check("December is due the next January", st.due_date(2026, 112) == date(2027, 1, 20))
check("a month has no WebFile code, rather than a guessed one", st.period_code(2026, 110) == "")
check("the year turns", st.next_period(2026, 112) == (2027, 101) and st.previous_period(2027, 101) == (2026, 112))
years = st.periods_owed(date(2025, 6, 1), date(2026, 11, 4), "yearly")
check("yearly is one period a year", years == [(2025, 10), (2026, 10)], years)
check("a year runs January to December and is due January 20",
      st.quarter_bounds(2026, 10) == (date(2026, 1, 1), date(2026, 12, 31))
      and st.due_date(2026, 10) == date(2027, 1, 20) and st.period_label(2026, 10) == "Jan–Dec 2026")
check("only real periods are valid",
      all(st.valid_period(n) for n in (1, 4, 10, 101, 112)) and not any(st.valid_period(n) for n in (0, 5, 9, 100, 113)))
check("a frequency nobody knows reads as quarterly",
      st.periods_owed(date(2026, 4, 9), date(2026, 6, 1), "fortnightly") == [(2026, 2)])

print("\n4. A BLANK FIRST SALE")
check("the first sale when it is on file", st.owed_from(date(2026, 4, 9), date(2026, 10, 28)) == (date(2026, 4, 9), "first sale"))
check("the permit's registration without it",
      st.owed_from(None, date(2026, 10, 28)) == (date(2026, 10, 28), "permit registered"))
check("then the earliest return filed",
      st.owed_from(None, None, [(2026, 3), (2026, 2)]) == (date(2026, 4, 1), "first return filed"))
check("then the first location", st.owed_from(None, None, [], [None, date(2026, 9, 18)])
      == (date(2026, 9, 18), "first location opened"))
check("and nothing when nothing is on file", st.owed_from(None, None, [], [None]) == (None, None))

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    blank = Business(name="Blank LLC", slug="blank", texas_taxpayer_number="32000000002",
                     sales_tax_registered_on=date(2026, 7, 1), sales_source="manual")
    none = Business(name="Nothing LLC", slug="nothing", sales_source="manual")
    monthly = Business(name="Monthly LLC", slug="monthly", sales_source="manual",
                       sales_tax_first_sale=date(2026, 4, 9), sales_tax_frequency="monthly")
    db.session.add_all([boss, blank, none, monthly])
    db.session.flush()
    db.session.add(BusinessLocation(business_id=monthly.id, webfile_number="00001", label="Paris",
                                    local_rate=2.0, opened_on=date(2026, 4, 9)))
    # Filed quarterly before the Comptroller's letter moved it to monthly.
    db.session.add(SalesTaxFiling(business_id=monthly.id, year=2026, quarter=2, reference_number="111",
                                  filed_at=datetime(2026, 7, 15, 10, 0)))
    db.session.commit()
    today = date(2026, 11, 4)
    owed = br.owed_periods(blank, today)
    check("a blank first sale with a permit date still owes its returns",
          owed == [(2026, 3), (2026, 4)], owed)
    check("nothing on file owes nothing", br.owed_periods(none, today) == [])
    owed = br.owed_periods(monthly, today)
    check("a monthly business lists months, and keeps its quarterly return",
          (2026, 2) in owed and (2026, 107) in owed and (2026, 111) == owed[-1] and (2026, 3) not in owed
          and not {(2026, 104), (2026, 105), (2026, 106)} & set(owed), owed)
    boss_id = boss.id

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)
page = c.get("/admin/taxes/sales/returns").get_data(as_text=True)
check("the returns page lists the months", "Oct 2026" in page and "Apr–Jun 2026" in page)
check("and says plainly when nothing says where to count from",
      "No first sale, permit date or location on file" in page)
r = c.get("/admin/taxes/sales/returns/monthly/2026/q110")
check("a month has a return page", r.status_code == 200 and "Oct 2026" in r.get_data(as_text=True), r.status_code)
check("a period that does not exist is a 404", c.get("/admin/taxes/sales/returns/monthly/2026/q5").status_code == 404)
check("the hub takes a month", br._period_from({"year": 2026, "quarter": 110}) == (2026, 110)
      and br._period_from({"year": 2026, "quarter": 5}) is None)

print("\n" + ("all passed" if not FAIL else "FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
