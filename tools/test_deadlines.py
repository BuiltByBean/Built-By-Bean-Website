# -*- coding: utf-8 -*-
"""One deadline list (deadlines.py), audit item 8.

  1. The dates: estimates roll off weekends and holidays the way a return
     does (and the Taxes page reads the same), May 15 franchise reports roll
     too (2027's is Monday May 17), a 1065 is March 15, a 1040 April 15.
  2. Who owes what: Built by Bean (one owner, formed 2024, its 2026 report on
     the state's record) owes a 1040 and Schedule C and the estimates;
     EntertainHQ (three members, formed 2026-10-05) owes its first franchise
     report in 2027 and a 1065 with three K-1s; a DBA's certificate renews
     ten years after it was filed, or says it has no date.
  3. What proves done: a filed return; the state's report year; an IRS line
     on the bank (each line used once); Done for the rest, and Undo.
  4. Needs attention carries a deadline from ten days out and once late,
     for the CEO only; the deadlines page draws.

Run: python tools/test_deadlines.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-deadlines-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, BusinessLocation,  # noqa: E402
                    BusinessOwner, DeadlineDone, SalesTaxFiling, User)
import deadlines as dl  # noqa: E402
from pm import tax_routes  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("1. THE DATES")
check("Q4 2026's estimate is Friday Jan 15", dl.estimate_due(2026, 4) == date(2027, 1, 15))
check("Q4 2027's rolls past a Saturday and MLK Day to Tue Jan 18 2028",
      dl.estimate_due(2027, 4) == date(2028, 1, 18), dl.estimate_due(2027, 4))
check("Q3 2029's Saturday Sep 15 rolls to Monday", dl.estimate_due(2029, 3) == date(2029, 9, 17))
check("the Taxes page names the same days",
      all(tax_routes._due_date(y, q) == dl.estimate_due(y, q) for y in (2026, 2027, 2029) for q in (1, 2, 3, 4)))
check("2027's franchise report is due Monday May 17", dl.franchise_due(2027) == date(2027, 5, 17))
check("2026's was Friday May 15", dl.franchise_due(2026) == date(2026, 5, 15))

print("\n2. WHO OWES WHAT")
with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    member = User(username="hb", email="hb@example.test", first_name="Hannah", role="member")
    member.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   texas_taxpayer_number="32093304155", formed_on=date(2024, 1, 17),
                   sales_tax_first_sale=date(2026, 4, 9), sales_source="manual",
                   franchise_report_year=2026, franchise_status="ACTIVE")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   texas_taxpayer_number="32108463343", formed_on=date(2026, 10, 5),
                   sales_tax_first_sale=date(2026, 11, 6), sales_source="manual")
    db.session.add_all([boss, member, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="data-dungeon", parent_id=bbb.id, sales_source="manual")
    pt = Business(name="Personal Training", slug="personal-training", parent_id=bbb.id,
                  sales_source="manual", assumed_name_filed_on=date(2017, 1, 10))
    db.session.add_all([dd, pt])
    db.session.add(BusinessOwner(business_id=bbb.id, name="Michael Bean", share_percent=100))
    for n in ("Michael Bean", "Kenali Kendrick", "Third Member"):
        db.session.add(BusinessOwner(business_id=ehq.id, name=n))
    db.session.add(BusinessLocation(business_id=bbb.id, webfile_number="00001", label="Paris",
                                    opened_on=date(2026, 4, 9)))
    for q in (2, 3):
        db.session.add(SalesTaxFiling(business_id=bbb.id, year=2026, quarter=q, reference_number=f"R{q}",
                                      filed_at=datetime(2026, 10, 30)))
    db.session.commit()
    boss_id, member_id, bbb_id, ehq_id, dd_id, pt_id = boss.id, member.id, bbb.id, ehq.id, dd.id, pt.id

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)

with application.test_request_context():
    today = date(2026, 11, 4)
    rows = dl.build(today, payments=[])
    keys = {r["key"]: r for r in rows}
    check("Built by Bean's filed returns are not deadlines",
          f"sales_tax:{bbb_id}:2026:2" not in keys and f"sales_tax:{bbb_id}:2026:3" not in keys)
    q4 = keys.get(f"sales_tax:{bbb_id}:2026:4")
    check("its open quarter is, due Jan 20", q4 and q4["due"] == date(2027, 1, 20) and q4["status"] == "upcoming", q4)
    check("its 2026 franchise report is done on the state's record",
          keys.get(f"franchise:{bbb_id}:2026", {}).get("done") == "On the Comptroller's record")
    check("its 2027 report is coming", keys.get(f"franchise:{bbb_id}:2027", {}).get("status") == "upcoming")
    check("EntertainHQ's first franchise report is 2027, not 2026",
          f"franchise:{ehq_id}:2027" in keys and f"franchise:{ehq_id}:2026" not in keys)
    p = keys.get(f"partnership:{ehq_id}:2026")
    check("EntertainHQ owes a 2026 1065 with three K-1s on Mon Mar 15 2027",
          p and p["due"] == date(2027, 3, 15) and "3 K-1s" in p["title"], p)
    check("Built by Bean, owned alone, owes no 1065", not any(k.startswith(f"partnership:{bbb_id}") for k in keys))
    check("Michael owes his 2026 1040 and Schedule C on Apr 15 2027",
          keys.get("personal:2026", {}).get("due") == date(2027, 4, 15)
          and "Built by Bean" in keys["personal:2026"]["note"])
    check("nothing federal from before the list began is late",
          not any(r["status"] == "late" for r in rows if r["kind"] in ("personal", "estimate", "partnership")))
    check("Q4 2026's estimate is on the list", keys.get("estimate:2026:4", {}).get("due") == date(2027, 1, 15))
    check("a DBA with no filing date says so", keys.get(f"dba:{dd_id}:unknown", {}).get("status") == "no_date")
    renew = keys.get(f"dba:{pt_id}:2027")
    check("a DBA filed 2017-01-10 renews by Jan 9 2027, never rolled past it",
          renew and renew["due"] == date(2027, 1, 9), renew)
    check("no DBA files a franchise report or a return",
          not any(k.startswith((f"franchise:{dd_id}", f"sales_tax:{dd_id}")) for k in keys))

print("\n3. WHAT PROVES DONE")
dues = {(2026, 4): date(2027, 1, 15), (2027, 1): date(2027, 4, 15)}
pays = [(date(2027, 1, 12), 1500.0, 1), (date(2027, 1, 14), 20.0, 2), (date(2027, 4, 14), 1500.0, 3)]
got = dl.match_estimates(dues, pays)
check("each estimate takes the first IRS payment near it, and a payment is used once",
      got == {(2026, 4): (date(2027, 1, 12), 1500.0), (2027, 1): (date(2027, 4, 14), 1500.0)}, got)
check("a payment two months off is not this estimate",
      dl.match_estimates({(2026, 4): date(2027, 1, 15)}, [(date(2026, 11, 1), 900.0, 9)]) == {})

with application.app_context():
    conn = BankConnection(business_id=bbb_id, provider="statement", label="Chase")
    db.session.add(conn)
    db.session.flush()
    db.session.add(BankTransaction(connection_id=conn.id, business_id=bbb_id, external_id="irs1",
                                   amount=-2400.0, occurred_on=date(2027, 1, 13),
                                   counterparty="IRS USATAXPYMT", disposition="draw", status="sent"))
    db.session.commit()
with application.test_request_context():
    keys = {r["key"]: r for r in dl.build(date(2027, 1, 14))}
    est = keys.get("estimate:2026:4")
    check("an IRS line on the bank marks the estimate paid",
          est and est["status"] == "done" and "$2,400.00 to the IRS" in est["done"], est)

r = c.post("/admin/taxes/deadlines/done", data={"key": f"partnership:{ehq_id}:2026"})
with application.test_request_context():
    keys = {r["key"]: r for r in dl.build(date(2027, 3, 10))}
    check("Done marks a 1065 done", r.status_code == 302
          and keys[f"partnership:{ehq_id}:2026"]["status"] == "done")
c.post("/admin/taxes/deadlines/undo", data={"key": f"partnership:{ehq_id}:2026"})
with application.test_request_context():
    keys = {r["key"]: r for r in dl.build(date(2027, 3, 10))}
    check("Undo puts it back, ten days out it is soon",
          keys[f"partnership:{ehq_id}:2026"]["status"] == "soon")

print("\n4. NEEDS ATTENTION AND THE PAGE")
with application.app_context():
    from models import Business as B
    e = db.session.get(B, ehq_id)
    e.franchise_report_year = None
    db.session.commit()
with application.test_request_context():
    rows = dl.attention_rows(date(2027, 5, 10))["deadlines"]
    check("from ten days out a franchise report is a row",
          any(r["key"] == f"franchise:{ehq_id}:2027" for r in rows), [r["key"] for r in rows])
    rows = dl.attention_rows(date(2027, 4, 1))["deadlines"]
    check("a month out it is not", not any(r["key"] == f"franchise:{ehq_id}:2027" for r in rows))
    rows = dl.attention_rows(date(2027, 6, 1))["deadlines"]
    check("late, it stays", any(r["key"] == f"franchise:{ehq_id}:2027" and r["status"] == "late" for r in rows))

dl.LIST_STARTED = date(2026, 1, 1)  # make the 2026 Q3 estimate (Sep 15) late today
dl.forget()
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention shows a late deadline with Done for the CEO",
      "data-deadline-row" in page and "estimated tax payment" in page and ">Done</button>" in page)
with c.session_transaction() as sess:
    sess["_user_id"] = str(member_id)
page = c.get("/admin/attention/").get_data(as_text=True)
check("not for the marketing seat", "data-deadline-row" not in page)
check("and the deadlines page is the CEO's", c.get("/admin/taxes/deadlines").status_code == 302)
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)
r = c.get("/admin/taxes/deadlines")
page = r.get_data(as_text=True)
check("the deadlines page draws every group",
      r.status_code == 200 and "Needs you" in page and "Coming up" in page and "Not on file" in page, r.status_code)
check("the business page draws what the state says",
      "What the state says" in c.get(f"/admin/businesses/{bbb_id}").get_data(as_text=True))

print("\n" + ("all passed" if not FAIL else "FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
