# -*- coding: utf-8 -*-
"""Only the bank line makes an expense (docs/finances_plan.md items 5, 6, 8).

Michael, 2026-11-04. Until then a vendor sync wrote an expense per cost entry
and the bank line for the same charge was "covered", booking nothing. Now the
bank line books it and the vendor's report only splits it. The migration that
carries the old rows over may not move any company's yearly total except to
remove a real double count, or by one of Michael's own decisions.

What is proved, on a ledger shaped like production's on the day:

  1. The dry run behind the door and the migration are the same reading: the
     door answers the plan, and changes nothing.
  2. The migration: a covered line whose vendor rows hold its charge takes
     those rows' expenses as its shares, with nothing added, removed or
     re-dated; a period's rows adding up to one charge go to that charge;
     two charges paying one period (Railway's March, $9.75 and $5.00) each
     take their share of every row, on the same dates; a plain expense line
     for a charge the sync also booked is the one double count, removed and
     kept whole in expense_corrections; Michael's decision books the Claude
     charge nothing stood for in EntertainHQ's books; a personal card's
     shares say who paid.
  3. THE POINT: every company's yearly expense total and the Books' own
     figures are unchanged but for the double count and the decision, to the
     cent, and the guard refuses a migration that would move one for any
     other reason.
  4. The night after changes nothing: splitting the carried-over lines again
     keeps every amount and every date.
  5. From now on: a new vendor charge books itself, split by the report, and
     the vendor sync books nothing; a report that lands later splits it
     again; voiding the line takes every share with it.
  6. A session's log_expense is a tag: the bank line takes it and its
     expense lands on the project; one logged after its line is put on it at
     once; one no line takes in ten days is a Needs attention row.
  7. Recurring expenses retire: every parent ends, every past row stays, and
     the form no longer offers it.
  8. The downgrade puts everything back to the cent.

Run: python tools/test_only_bank_books.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-onlybank-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Client, Expense,  # noqa: E402
                    ExpenseCorrection, ExpenseTag, Project, ServiceCostEntry, ServiceMapping,
                    ServiceProvider, User, VendorRule)
import bank_feed  # noqa: E402
import books_service  # noqa: E402
import books_upkeep  # noqa: E402
import finance_carryover  # noqa: E402
import service_costs_service as scs  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def migration():
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/f2a7c9d41e63_only_the_bank_makes_an_expense.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


def run(step):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    mig = migration()
    db.session.commit()
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        getattr(mig, step)()
    db.session.expire_all()


def totals():
    """Every company's yearly expense total, and what the Books say."""
    out = {}
    for b in Business.query.filter_by(parent_id=None).all():
        for year in (2026,):
            s = books_service.summarize(b, date(year, 1, 1), date(year + 1, 1, 1))
            out[(b.short_name, year)] = round(s["expense_total"] if "expense_total" in s else
                                              sum(e.amount for e in books_service.expenses_between(
                                                  b, date(year, 1, 1), date(year + 1, 1, 1))), 2)
    return out


def raw_totals():
    """The same per company and year, read with plain SQL: after the
    downgrade the model has columns the table no longer does."""
    fam, _, _ = finance_carryover._families(db.session.connection())
    return finance_carryover._totals(db.session.connection(), fam)


def snapshot():
    return {e.id: (round(e.amount, 2), e.date, e.business_id, e.client_id, e.project_id, e.category)
            for e in Expense.query.all()}


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    kuper = Client(name="Cason Kuper")
    db.session.add_all([boss, bbb, ehq, kuper])
    db.session.flush()
    kp = Project(name="Kuper Plumbing", client_id=kuper.id, status="active")
    site = Project(name="Website", client_id=kuper.id, status="active")
    rw = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    cl = ServiceProvider(name="flat", display_name="Claude", is_active=True, monthly_cost=20.0, billing_day=3)
    db.session.add_all([kp, site, rw, cl])
    db.session.flush()
    m_kuper = ServiceMapping(provider_id=rw.id, resource_identifier="railway:kuper", client_id=kuper.id,
                             project_id=kp.id, split_percentage=100.0, is_active=True)
    db.session.add(m_kuper)
    mercury = BankConnection(business_id=bbb.id, token="t", synced_from=date(2026, 4, 1))
    card = BankConnection(business_id=bbb.id, provider="statement", kind="personal",
                          owner_name="Michael Bean", label="Michael's card")
    db.session.add_all([mercury, card])
    db.session.flush()
    r_rw = VendorRule(pattern="RAILWAY", disposition="covered", vendor="Railway", category="hosting",
                      provider_id=rw.id, business_id=bbb.id)
    r_cl = VendorRule(pattern="CLAUDE", disposition="covered", vendor="Claude", category="ai_services",
                      provider_id=cl.id, business_id=bbb.id)
    db.session.add_all([r_rw, r_cl])
    db.session.flush()

    def vendor_row(provider, resource, start, end, amount, mapping=None):
        """A cost entry and the expense the OLD sync wrote beside it."""
        exp = Expense(amount=amount, date=end, business_id=bbb.id, category="service_cost",
                      description=f"{provider.display_name} - {resource} ({start:%b %Y})",
                      client_id=mapping.client_id if mapping else None,
                      project_id=mapping.project_id if mapping else None)
        db.session.add(exp)
        db.session.flush()
        entry = ServiceCostEntry(provider_id=provider.id, mapping_id=mapping.id if mapping else None,
                                 resource_identifier=resource, period_start=start, period_end=end,
                                 raw_amount=amount, allocated_amount=amount, expense_id=exp.id,
                                 description=f"{provider.display_name} - {resource} ({start:%b %Y})")
        db.session.add(entry)
        db.session.flush()
        return entry

    def line(conn, ext, amount, when, name, disposition="covered", rule=None, expense=None):
        row = BankTransaction(connection_id=conn.id, business_id=bbb.id, external_id=ext, status="sent",
                              amount=amount, occurred_on=when, counterparty=name, disposition=disposition,
                              rule_id=rule.id if rule else None, expense_id=expense.id if expense else None)
        db.session.add(row)
        db.session.flush()
        return row

    # Railway's March: two invoices, $9.75 and $5.00, over three project rows.
    mar = (date(2026, 3, 1), date(2026, 3, 31))
    vendor_row(rw, "railway:kuper", *mar, 6.00, m_kuper)
    vendor_row(rw, "railway:site", *mar, 4.75)
    vendor_row(rw, "railway:other", *mar, 4.00)
    l_mar_a = line(mercury, "m1", -9.75, date(2026, 4, 1), "Railway", rule=r_rw)
    l_mar_b = line(mercury, "m2", -5.00, date(2026, 4, 2), "Railway", rule=r_rw)
    # September, a period's rows adding up to one charge.
    sep = (date(2026, 9, 1), date(2026, 9, 30))
    vendor_row(rw, "railway:kuper", *sep, 30.00, m_kuper)
    vendor_row(rw, "railway:site", *sep, 13.71)
    l_sep = line(mercury, "s1", -43.71, date(2026, 10, 1), "Railway", rule=r_rw)
    # Claude, one row for one charge, on Michael's own card.
    c_day = date(2026, 10, 3)
    vendor_row(cl, "flat:subscription", c_day, c_day, 20.00)
    l_cl = line(card, "c1", -20.00, c_day, "CLAUDE.AI SUBSCRIPTION", rule=r_cl)
    # October's Railway charged twice: the sync's rows AND a line settled by
    # hand as a plain expense. The double count.
    octo = (date(2026, 10, 1), date(2026, 10, 31))
    vendor_row(rw, "railway:kuper", *octo, 52.38, m_kuper)
    dup = Expense(amount=52.38, date=date(2026, 11, 1), business_id=bbb.id, category="hosting",
                  description="Railway")
    db.session.add(dup)
    db.session.flush()
    l_dup = line(mercury, "d1", -52.38, date(2026, 11, 1), "RAILWAY CORPORATION", disposition="expense",
                 expense=dup)
    l_dup.decided_at = datetime(2026, 11, 2)
    # The Claude charge nothing booked (Michael: EntertainHQ's).
    l_hole = line(mercury, "h1", -10.66, date(2026, 10, 17), "CLAUDE.AI SUBSCRIPTION", rule=r_cl)
    # A recurring parent and its child, from the old toggle.
    parent = Expense(amount=12.0, date=date(2026, 5, 1), business_id=bbb.id, description="Old monthly",
                     is_recurring=True, frequency="monthly", next_due_date=date(2026, 12, 1))
    db.session.add(parent)
    db.session.flush()
    child = Expense(amount=12.0, date=date(2026, 6, 1), business_id=bbb.id, description="Old monthly",
                    parent_expense_id=parent.id)
    db.session.add(child)
    db.session.commit()
    finance_carryover.DECISIONS = [{"line_id": l_hole.id, "amount": 10.66, "date": "2026-10-17",
                                    "company": "EntertainHQ", "why": "test: Michael's answer"}]
    ids = dict(bbb=bbb.id, ehq=ehq.id, rw=rw.id, cl=cl.id, kp=kp.id, kuper=kuper.id, boss=boss.id,
               mar_a=l_mar_a.id, mar_b=l_mar_b.id, sep=l_sep.id, cl_line=l_cl.id, dup=l_dup.id,
               dup_expense=dup.id, hole=l_hole.id, parent=parent.id, child=child.id,
               mercury=mercury.id, r_rw=r_rw.id)
    before_totals = totals()
    before_raw = raw_totals()
    before = snapshot()
    before_count = Expense.query.count()

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(ids["boss"])
    sess["_fresh"] = True

print("1. The dry run behind the door")
r = c.get("/api/guidance/books/carryover", headers={"Authorization": "Bearer test-key"})
plan = r.get_json() or {}
check("answers the plan", r.status_code == 200 and len(plan.get("links", [])) == 2, r.status_code)
check("finds the one double count", [d["line_id"] for d in plan.get("doubles", [])] == [ids["dup"]],
      plan.get("doubles"))
check("finds March's two charges sharing one month",
      len(plan.get("shared", [])) == 1 and len(plan["shared"][0]["lines"]) == 2, plan.get("shared"))
check("finds Michael's decision", [d["line_id"] for d in plan.get("decided", [])] == [ids["hole"]])
check("and nothing it cannot explain", plan.get("unexplained_moves") == [] and not plan.get("holes")
      and not plan.get("mismatches"), plan.get("summary"))
check("the door refuses without the key",
      c.get("/api/guidance/books/carryover").status_code == 401)
with application.app_context():
    check("and the dry run changed nothing", snapshot() == before and Expense.query.count() == before_count)

print("2. The migration")
with application.app_context():
    run("upgrade")
    lines = {l.id: l for l in BankTransaction.query.all()}
    sep_parts = bank_feed._parts(lines[ids["sep"]])
    check("September's line takes both rows the sync wrote, unchanged",
          sorted(round(p.amount, 2) for p in sep_parts) == [13.71, 30.0]
          and all(before[p.id][:3] == (round(p.amount, 2), p.date, p.business_id) for p in sep_parts),
          [(p.id, p.amount, p.date) for p in sep_parts])
    check("and reads split", lines[ids["sep"]].disposition == "split")
    a, b = bank_feed._parts(lines[ids["mar_a"]]), bank_feed._parts(lines[ids["mar_b"]])
    check("March's $9.75 charge takes its share of all three rows",
          len(a) == 3 and round(sum(p.amount for p in a), 2) == 9.75, [(p.amount) for p in a])
    check("and the $5.00 its share of the same three",
          len(b) == 3 and round(sum(p.amount for p in b), 2) == 5.00, [(p.amount) for p in b])
    check("both on March's own date, so March does not move",
          all(p.date == date(2026, 3, 31) for p in a + b))
    check("Kuper's March share stays on Kuper's project",
          all(any(p.project_id == ids["kp"] for p in side) for side in (a, b)))
    cl_parts = bank_feed._parts(lines[ids["cl_line"]])
    check("the card's Claude share says Michael paid it",
          len(cl_parts) == 1 and cl_parts[0].paid_by == "Michael Bean", [(p.paid_by) for p in cl_parts])
    check("the double count is gone", db.session.get(Expense, ids["dup_expense"]) is None)
    gone = ExpenseCorrection.query.filter_by(expense_id=ids["dup_expense"], action="removed").first()
    check("and kept whole in expense_corrections, with why", gone is not None and "booked twice" in gone.reason
          and '"amount": 52.38' in gone.snapshot_json, gone and gone.reason)
    check("its line now carries the vendor's split instead",
          lines[ids["dup"]].disposition == "split" and len(bank_feed._parts(lines[ids["dup"]])) == 1
          and bank_feed._parts(lines[ids["dup"]])[0].project_id == ids["kp"])
    hole = lines[ids["hole"]]
    check("Michael's decision: the Claude charge is EntertainHQ's expense",
          hole.disposition == "expense" and hole.expense and hole.expense.business_id == ids["ehq"]
          and round(hole.expense.amount, 2) == 10.66 and hole.decided_at is not None)
    check("every rule that said covered says split",
          not VendorRule.query.filter_by(disposition="covered").count()
          and not BankTransaction.query.filter_by(disposition="covered").count())

    print("3. THE POINT: the totals")
    after_totals = totals()
    want = dict(before_totals)
    want[("Built by Bean", 2026)] = round(want[("Built by Bean", 2026)] - 52.38, 2)
    want[("EntertainHQ", 2026)] = round(want.get(("EntertainHQ", 2026), 0.0) + 10.66, 2)
    check("each company's year moves only by the double count and the decision, to the cent",
          after_totals == want, (before_totals, after_totals))
    month = {}
    for e in Expense.query.filter(Expense.business_id == ids["bbb"]).all():
        month[(e.date.year, e.date.month)] = round(month.get((e.date.year, e.date.month), 0.0) + e.amount, 2)
    old_month = {}
    for eid, (amount, when, biz, *_rest) in before.items():
        if biz == ids["bbb"] and eid != ids["dup_expense"]:
            old_month[(when.year, when.month)] = round(old_month.get((when.year, when.month), 0.0) + amount, 2)
    check("and no month moves either, but the double count's", month == old_month, (old_month, month))

    print("   the guard")
    saved = finance_carryover.DECISIONS
    finance_carryover.DECISIONS = []
    try:
        db.session.commit()
        bad = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="x1",
                              status="sent", amount=-7.0, occurred_on=date(2026, 10, 9),
                              counterparty="RAILWAY", disposition="covered", rule_id=ids["r_rw"])
        db.session.add(bad)
        stray = Expense(amount=7.0, date=date(2026, 10, 9), business_id=ids["bbb"], description="x")
        db.session.add(stray)
        db.session.flush()
        bad2 = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="x2",
                               status="sent", amount=-7.0, occurred_on=date(2026, 10, 9),
                               counterparty="NOBODY", disposition="expense", expense_id=stray.id)
        db.session.add(bad2)
        db.session.flush()
        report = finance_carryover.plan(db.session.connection())
        check("a covered line nothing stood for is reported and books nothing",
              any(h["line_id"] == bad.id for h in report["holes"] + report["mismatches"]))
        orig = finance_carryover._totals
        finance_carryover._totals = lambda conn, fam, removed=(): (
            {"Built by Bean LLC": {2026: 1.0}} if removed == () else {"Built by Bean LLC": {2026: 2.0}})
        try:
            finance_carryover.apply(db.session.connection())
            check("a total moving for any other reason stops the migration", False)
        except RuntimeError as err:
            check("a total moving for any other reason stops the migration", "would move" in str(err))
        finally:
            finance_carryover._totals = orig
    finally:
        db.session.rollback()
        finance_carryover.DECISIONS = saved

    print("4. The night after")
    kept = snapshot()
    n = bank_feed.resplit(today=date(2026, 11, 20), days=400)
    db.session.commit()
    check("splitting the carried-over lines again keeps every amount and date",
          n >= 4 and {k: v[:3] for k, v in snapshot().items()} == {k: v[:3] for k, v in kept.items()},
          [(k, kept.get(k), v) for k, v in snapshot().items() if kept.get(k, (None,))[:3] != v[:3]][:4])

    print("5. From now on")
    rw = db.session.get(ServiceProvider, ids["rw"])
    nov = (date(2026, 11, 1), date(2026, 11, 30))
    for res, amount, mapping in (("railway:kuper", 20.0, ServiceMapping.query.first()), ("railway:site", 8.5, None)):
        scs._record_cost_entry(rw, res, nov[0], nov[1], amount, f"Railway - {res}", {})
    db.session.commit()
    check("the vendor sync books no expense for a new month",
          all(e.expense_id is None for e in ServiceCostEntry.query.filter_by(period_start=nov[0]).all()))
    new = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="n1",
                          status="sent", amount=-28.5, occurred_on=date(2026, 12, 1), counterparty="Railway")
    db.session.add(new)
    db.session.flush()
    bank_feed.classify(new)
    db.session.commit()
    parts = bank_feed._parts(new)
    check("its charge books one row per project share, adding up to the charge, on the bank's date",
          new.disposition == "split" and sorted(round(p.amount, 2) for p in parts) == [8.5, 20.0]
          and all(p.date == date(2026, 12, 1) for p in parts) and any(p.project_id == ids["kp"] for p in parts),
          [(p.amount, p.date, p.project_id) for p in parts])
    late = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="n2",
                           status="sent", amount=-11.0, occurred_on=date(2027, 1, 20), counterparty="Railway")
    db.session.add(late)
    db.session.flush()
    bank_feed.classify(late)
    check("a charge whose report has not landed is one row",
          len(bank_feed._parts(late)) == 1 and round(late.expense.amount, 2) == 11.0)
    dec = (date(2026, 12, 1), date(2026, 12, 31))
    scs._record_cost_entry(rw, "railway:kuper", dec[0], dec[1], 6.0, "Railway - kuper", {})
    scs._record_cost_entry(rw, "railway:site", dec[0], dec[1], 5.0, "Railway - site", {})
    bank_feed.resplit(provider_id=ids["rw"], today=date(2027, 1, 21))
    db.session.commit()
    check("and when it lands, the next split divides it",
          sorted(round(p.amount, 2) for p in bank_feed._parts(late)) == [5.0, 6.0])
    late.status = "cancelled"
    bank_feed.classify(late)
    db.session.commit()
    check("a voided line takes every share with it",
          not bank_feed._parts(late) and late.expense_id is None)
    odd = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="n3",
                          status="sent", amount=-3.33, occurred_on=date(2026, 12, 2), counterparty="Railway")
    db.session.add(odd)
    db.session.flush()
    check("a charge the report beside it does not explain waits on review, as before",
          bank_feed.classify(odd) == "review" and odd.expense_id is None)

print("6. A session's log_expense is a tag")
r = c.post("/api/guidance/expenses", headers={"Authorization": "Bearer test-key"},
           json={"amount": 15.0, "description": "kuperplumbing.com renewal", "vendor": "Cloudflare",
                 "client": "Cason Kuper", "project": "Kuper Plumbing", "date": "2026-11-10",
                 "category": "domain", "source": "kuper repo"})
body = r.get_json() or {}
with application.app_context():
    check("it makes no expense", body.get("action") == "tagged" and not body.get("taken")
          and Expense.query.filter(Expense.description.like("%kuperplumbing%")).count() == 0, body)
    again = c.post("/api/guidance/expenses", headers={"Authorization": "Bearer test-key"},
                   json={"amount": 15.0, "description": "kuperplumbing.com renewal", "vendor": "Cloudflare",
                         "client": "Cason Kuper", "project": "Kuper Plumbing", "date": "2026-11-10",
                         "category": "domain", "source": "kuper repo"}).get_json()
    check("a retry is the same tag", again.get("action") == "already tagged" and ExpenseTag.query.count() == 1)
    cf = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="t1",
                         status="sent", amount=-15.0, occurred_on=date(2026, 11, 12), counterparty="CLOUDFLARE")
    db.session.add(cf)
    db.session.flush()
    cf.disposition = "expense"
    bank_feed.book(cf, manual={"business_id": ids["bbb"], "category": "misc", "vendor": "CLOUDFLARE"})
    db.session.commit()
    tag = ExpenseTag.query.first()
    check("the bank line takes it, and its expense lands on the project",
          tag.line_id == cf.id and cf.expense.project_id == ids["kp"] and cf.expense.client_id == ids["kuper"]
          and cf.expense.category == "domain", (tag.line_id, cf.expense.project_id))
    early = BankTransaction(connection_id=ids["mercury"], business_id=ids["bbb"], external_id="t2",
                            status="sent", amount=-9.99, occurred_on=date(2026, 11, 14),
                            counterparty="NAMECHEAP", disposition="expense")
    db.session.add(early)
    db.session.flush()
    bank_feed.book(early, manual={"business_id": ids["bbb"], "category": "misc", "vendor": "Namecheap"})
    db.session.commit()
r = c.post("/api/guidance/expenses", headers={"Authorization": "Bearer test-key"},
           json={"amount": 9.99, "description": "piped.dev", "client": "Cason Kuper",
                 "project": "Website", "date": "2026-11-14", "source": "piped repo"})
with application.app_context():
    early = BankTransaction.query.filter_by(external_id="t2").one()
    check("a tag logged after its line is put on that line at once",
          (r.get_json() or {}).get("taken") and early.expense.project_id is not None, r.get_json())
    db.session.add(ExpenseTag(amount=44.0, occurred_on=date.today() - timedelta(days=12), vendor="Somewhere",
                              description="a card the board cannot see"))
    db.session.add(ExpenseTag(amount=3.0, occurred_on=date.today() - timedelta(days=2), vendor="Fresh"))
    db.session.commit()
    with application.test_request_context():
        rows = [row for row in books_upkeep.attention_rows() if row["label"] == "Tag"]
    check("one no line took in ten days is one Needs attention row, and a fresh one is not",
          len(rows) == 1 and "Somewhere" in rows[0]["detail"] and "Fresh" not in rows[0]["detail"], rows)

print("7. Recurring expenses retire")
with application.app_context():
    p = db.session.get(Expense, ids["parent"])
    check("the parent ends", not p.is_recurring and p.next_due_date is None)
    check("and every past row stays", db.session.get(Expense, ids["child"]) is not None and p.amount == 12.0)
page = c.get("/admin/expenses/new").get_data(as_text=True)
check("the form no longer offers it", "Recurring" not in page and "frequency" not in page)

print("8. The downgrade")
with application.app_context():
    # What 5 and 6 added is today's work, not the migration's: take it off so
    # the downgrade's own promise can be checked to the cent.
    for row in BankTransaction.query.filter(BankTransaction.external_id.in_(("n1", "n2", "n3", "t1", "t2"))).all():
        row.status = "cancelled"
        bank_feed.classify(row)
        db.session.delete(row)
    ExpenseTag.query.delete()
    for e in ServiceCostEntry.query.filter(ServiceCostEntry.period_start >= date(2026, 11, 1)).all():
        db.session.delete(e)
    db.session.commit()
    run("downgrade")
    check("the totals are back to the cent", raw_totals() == before_raw, (before_raw, raw_totals()))
    from sqlalchemy import text
    back = db.session.execute(text("SELECT amount FROM expenses WHERE id = :e"), {"e": ids["dup_expense"]}).scalar()
    check("the double count is back as it was", back == 52.38, back)
    check("and the lines read covered again",
          db.session.get(BankTransaction, ids["sep"]).disposition == "covered"
          and VendorRule.query.filter_by(disposition="covered").count() == 2)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
