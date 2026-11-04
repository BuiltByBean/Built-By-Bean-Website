# -*- coding: utf-8 -*-
"""The corrections from the receipt review, and the rule that lost real charges.

Proves:

  1. The migration removes exactly the approved rows, keeps each whole with its
     reason, and leaves any row whose amount or words do not match alone.
  2. The RuneScape charge becomes money the owner took out.
  3. EntertainHQ's real charges land on its books, paid by the card's owner, and
     the domain's tag survives on a mapping the nightly sync will read.
  4. Downgrade puts every row back to the cent.
  5. Going forward, a card charge a sync does not hold is never quietly dropped:
     it goes to the company that owns it when something says so, and to review
     when nothing does. A charge the sync does hold stays covered, one row or a
     month's rows adding up.

Run: python tools/test_book_corrections.py
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-corrections-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Expense, ExpenseCorrection,  # noqa: E402
                    Receipt, ReceiptMailbox, ServiceCostEntry, ServiceMapping, ServiceProvider, VendorRule)
import bank_feed  # noqa: E402
import books_service  # noqa: E402

application = create_app()
FAIL = []
NAME = "c3e7a1f90b42_corrections_from_the_receipt_review"
spec = importlib.util.spec_from_file_location(NAME, ROOT / f"migrations/versions/{NAME}.py")
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:260]) if detail != "" and not cond else ""))
    if not cond:
        FAIL.append(name)


def run(step):
    db.session.commit()
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        getattr(mig, step)()
    db.session.expire_all()


def amounts():
    return {e.id: round(e.amount, 2) for e in Expense.query.all()}


with application.app_context():
    db.create_all()
    bbb = Business(id=1, name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(id=2, name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add_all([bbb, ehq])
    db.session.flush()
    rows = {1: (21.32, "Claude Code"), 2: (86.75, "Claude Code"), 3: (9.75, "Railway - Hosting"),
            4: (5.00, "Railway - Hosting"), 12: (20.00, "Railway - Hosting"), 13: (20.00, "Railway - Hosting"),
            14: (20.00, "Railway - Hosting"), 46: (20.00, "Railway - Hosting"),
            170: (11.17, "masterbytrade.com, 1 year at Cloudflare Registrar"),
            6: (1.50, "Twilio Phone Number"), 7: (4.50, "Twilio, phone number registration"),
            8: (20.00, "Builtbybeans.com domain"), 110: (21.28, "ChatGPT Plus subscription (OpenAI), February"),
            199: (107.69, "Cambridge membership"),
            # Real rows that must not move.
            5: (20.00, "Twilio"), 137: (213.20, "Claude (17 Oct 2026)"),
            171: (11.17, "Cloudflare - masterbytrade.com registration (Nov 2026) [unallocated]"),
            # An id on the list whose amount does not match is not the row meant.
            9: (21.28, "Coding Agent")}
    for i, (amount, text) in rows.items():
        db.session.add(Expense(id=i, amount=amount, description=text, category="misc", date=date(2026, 4, 1), business_id=1))
    db.session.add(Expense(id=173, amount=213.20, description="Claude, product development", category="misc",
                           date=date(2026, 10, 17), business_id=2, paid_by="Michael Bean"))
    db.session.flush()
    db.session.get(Expense, 170).project_id = None
    db.session.get(Expense, 5).receipt_original_name = "Invoice-SKQBNJUH-0002.pdf"
    db.session.get(Expense, 5).receipt_filename = "wrong.pdf"
    box = ReceiptMailbox(id=1, business_id=1, address="owner@example.test", password="x")
    company = BankConnection(id=1, business_id=1, provider="statement", label="Chase business", token="", kind="business")
    card = BankConnection(id=2, business_id=1, provider="statement", label="Chase credit", token="", kind="personal",
                          owner_name="Michael Bean")
    provider = ServiceProvider(id=1, name="cloudflare", display_name="Cloudflare", is_active=True)
    railway = ServiceProvider(id=2, name="railway", display_name="Railway", is_active=True)
    railway_ehq = ServiceProvider(id=3, name="railway", display_name="Railway (EntertainHQ)", is_active=True,
                                  account_business_id=2)
    claude = ServiceProvider(id=4, name="anthropic", display_name="Claude", is_active=True)
    db.session.add_all([box, company, card, provider, railway, railway_ehq, claude])
    db.session.flush()
    db.session.add(ServiceCostEntry(provider_id=1, expense_id=171, resource_identifier="masterbytrade.com",
                                    period_start=date(2026, 11, 1), period_end=date(2026, 11, 30), raw_amount=11.17,
                                    allocated_amount=11.17, description="Cloudflare - masterbytrade.com registration (Nov 2026) [unallocated]"))
    db.session.add(Receipt(id=1, mailbox_id=1, message_key="k1", sender="Railway", vendor="Railway", subject="Your receipt",
                           received_on=date(2026, 4, 1), amount=9.75, filename="r.pdf", status="matched", expense_id=3))
    db.session.add(BankTransaction(id=1, connection_id=1, business_id=1, external_id="c", amount=-107.69,
                                   occurred_on=date(2026, 4, 7), status="sent", kind="statement",
                                   counterparty="12 Month Membership for CAMBRIDGE", disposition="expense", expense_id=199))
    for n, (who, amount, day) in enumerate([("ANTHROPIC* CLAUDE SUB", -105.40, date(2026, 10, 17)),
                                            ("ANTHROPIC* CLAUDE SUB", -113.69, date(2026, 10, 20)),
                                            ("RAILWAY", -5.33, date(2026, 9, 16)), ("RAILWAY", -15.83, date(2026, 9, 17)),
                                            ("RAILWAY", -21.32, date(2026, 10, 16)),
                                            ("ANTHROPIC* CLAUDE SUB", -213.20, date(2026, 10, 18))], start=10):
        db.session.add(BankTransaction(id=n, connection_id=2, business_id=1, external_id=f"l{n}", amount=amount,
                                       occurred_on=day, status="sent", kind="statement", counterparty=who,
                                       disposition="covered"))
    db.session.commit()
    before = amounts()
    money_before = books_service.owner_money_between(db.session.get(Business, 2), date(2026, 1, 1), date(2027, 1, 1))
    db.session.execute(db.text("DROP TABLE expense_corrections"))
    db.session.commit()

    print("1. The approved rows come off, each kept whole with its reason")
    run("upgrade")
    after = amounts()
    # By words as well as ids: SQLite hands a freed id straight to the next row,
    # so EntertainHQ's new charges can land on 173. Postgres never reuses one.
    gone = sorted(set(before) - set(after))
    check("exactly the approved rows and the RuneScape charge",
          gone == [1, 2, 3, 4, 6, 7, 8, 12, 13, 14, 46, 110, 170, 199]
          and Expense.query.filter(Expense.description.like("Claude, product%")).count() == 0, gone)
    check("the real rows stay", all(i in after for i in (5, 9, 137, 171)), after)
    removed = ExpenseCorrection.query.filter_by(action="removed").all()
    check("each is on the record with why", len(removed) == 15 and all(c.reason for c in removed), len(removed))
    check("whole, so it can come back", json.loads(next(c for c in removed if c.expense_id == 2).snapshot_json)["row"]["amount"] == 86.75)
    r = db.session.get(Receipt, 1)
    check("a receipt on a removed row is free for the row that stays", (r.status, r.expense_id) == ("unmatched", None))
    bbb_gone = sum(before[i] for i in (1, 2, 3, 4, 6, 7, 8, 12, 13, 14, 46, 110, 170))
    check("the double count taken off Built by Bean is $261.27", round(bbb_gone, 2) == 261.27, bbb_gone)

    print("2. RuneScape is money taken out")
    line = db.session.get(BankTransaction, 1)
    check("the bank line says so", (line.disposition, line.owner_name, line.expense_id) == ("draw", "Michael Bean", None),
          (line.disposition, line.owner_name, line.expense_id))
    money = books_service.owner_money_between(db.session.get(Business, 1), date(2026, 1, 1), date(2027, 1, 1))
    check("and the owner's figures show it", money["Michael Bean"]["out"] == 107.69, money)

    print("3. What was missing lands, and the tag survives")
    ehq_rows = Expense.query.filter_by(business_id=2).all()
    check("EntertainHQ has its five real charges",
          sorted(round(e.amount, 2) for e in ehq_rows) == [5.33, 15.83, 21.32, 105.40, 113.69],
          sorted(round(e.amount, 2) for e in ehq_rows))
    check("paid by the card's owner", all(e.paid_by == "Michael Bean" for e in ehq_rows))
    check("each stands behind its bank line",
          all(BankTransaction.query.filter_by(expense_id=e.id).count() == 1 for e in ehq_rows))
    check("a covered charge the sync does hold is untouched", db.session.get(BankTransaction, 15).disposition == "covered")
    mapping = ServiceMapping.query.filter_by(resource_identifier="masterbytrade.com").one()
    entry = ServiceCostEntry.query.filter_by(expense_id=171).one()
    check("the domain's tag is on a mapping the sync reads", entry.mapping_id == mapping.id)
    check("and the row stops reading unallocated", "[unallocated]" not in db.session.get(Expense, 171).description)
    check("the wrong receipt is off the row", db.session.get(Expense, 5).receipt_filename is None)
    snapshot = sorted((e.id, round(e.amount, 2)) for e in Expense.query.all())
    run("upgrade")
    check("running it twice changes nothing", sorted((e.id, round(e.amount, 2)) for e in Expense.query.all()) == snapshot)

    print("4. It all comes back")
    run("downgrade")
    check("every row, to the cent", amounts() == before, amounts())
    check("the receipts go back to their rows", db.session.get(Expense, 5).receipt_filename == "wrong.pdf"
          and db.session.get(Receipt, 1).expense_id == 3)
    check("the bank lines go back", db.session.get(BankTransaction, 1).expense_id == 199
          and db.session.get(BankTransaction, 10).disposition == "covered")
    check("the mapping goes", ServiceMapping.query.count() == 0)
    db.create_all()

    print("5. A charge a sync does not hold is never quietly dropped")
    claude_rule = bank_feed.remember("ANTHROPIC", "covered", vendor="Claude", business_id=1, category="ai_services", provider_id=4)
    railway_rule = bank_feed.remember("RAILWAY", "covered", vendor="Railway", business_id=1, category="hosting", provider_id=2)
    for i, (resource, amount, start, end) in enumerate([("a", 30.00, date(2027, 1, 1), date(2027, 1, 31)),
                                                        ("b", 10.38, date(2027, 1, 1), date(2027, 1, 31))]):
        db.session.add(ServiceCostEntry(provider_id=2, resource_identifier=resource, period_start=start, period_end=end,
                                        raw_amount=amount, allocated_amount=amount, description="x"))
    db.session.add(ServiceCostEntry(provider_id=4, resource_identifier="plan", period_start=date(2027, 2, 17),
                                    period_end=date(2027, 2, 17), raw_amount=213.20, allocated_amount=213.20, description="x"))
    db.session.commit()

    def charge(ref, who, amount, day):
        line = BankTransaction(connection_id=2, business_id=1, external_id=ref, amount=amount, occurred_on=day,
                               status="sent", kind="statement", counterparty=who, disposition="review")
        db.session.add(line)
        db.session.flush()
        bank_feed.classify(line, VendorRule.query.all())
        db.session.commit()
        return line

    held = charge("n1", "RAILWAY", -40.38, date(2027, 2, 1))
    check("a month's rows adding up to the bill count as held", held.disposition == "covered", held.disposition)
    one = charge("n2", "ANTHROPIC* CLAUDE SUB", -213.20, date(2027, 2, 18))
    check("so does a single row", one.disposition == "covered", one.disposition)
    theirs = charge("n3", "RAILWAY", -18.40, date(2027, 2, 16))
    booked = db.session.get(Expense, theirs.expense_id) if theirs.expense_id else None
    check("a charge from a vendor another company has its own account with goes to that company",
          booked is not None and booked.business_id == 2 and booked.paid_by == "Michael Bean", theirs.disposition)
    other_box = ReceiptMailbox(business_id=2, address="m@ehq.test", password="x")
    db.session.add(other_box)
    db.session.flush()
    db.session.add(Receipt(mailbox_id=other_box.id, message_key="e1", sender="Anthropic, PBC", vendor="Anthropic, PBC",
                           subject="Your receipt", received_on=date(2027, 2, 20), amount=113.69, filename=None, status="unmatched"))
    db.session.commit()
    second = charge("n4", "ANTHROPIC* CLAUDE SUB", -113.69, date(2027, 2, 20))
    booked = db.session.get(Expense, second.expense_id) if second.expense_id else None
    check("a receipt in that company's own mailbox says whose it is", booked is not None and booked.business_id == 2,
          second.disposition)
    lost = charge("n5", "ANTHROPIC* CLAUDE SUB", -77.77, date(2027, 2, 21))
    check("and when nothing says, a person decides rather than the charge vanishing", lost.disposition == "review",
          lost.disposition)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
