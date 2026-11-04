# -*- coding: utf-8 -*-
"""An expense goes and finds its own receipt.

Michael, 2026-11-03: "getting receipts for the expenses on the books right now,
and a way to automate getting those receipts going forward." The board read mail
by subject and then looked for a charge to pin it to, so 31 expenses sat without
a receipt while their receipts were in the mailbox: Gmail's word search never
returned "recharged" or "funded", Twilio's figure was read as the balance it
tops up to, and a vendor's month is dated its last day, weeks from its bill.

Proves:

  1. The figure that is not the charge is not read as the charge.
  2. An expense finds a message by its amount and its vendor, whatever the subject.
  3. Nothing short of the vendor and the exact charge attaches: a wrong receipt is
     worse than none.
  4. One charge booked twice gets one receipt, which is what shows it; a line
     inside a bill is not what was charged.
  5. Mail already kept is used rather than stored again, and mail not used is
     never stored.
  6. A small charge with no document gets its statement line, named as that, and
     a real receipt replaces it. Mail nobody wants stops asking to be read.
  7. A failed search says so without losing the rest of the read, and uploading a
     statement sets the search off.

Run: python tools/test_receipt_hunt.py
"""
import io
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-hunt-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Expense, Receipt,  # noqa: E402
                    ReceiptMailbox, ServiceCostEntry, ServiceProvider, User)
import receipts_service as rs  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
# Last year, because a fixture must never pin a date still in the future.
Y = date.today().year - 1


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail != "" and not cond else ""))
    if not cond:
        FAIL.append(name)


def mail(sender, subject, day, body):
    m = EmailMessage()
    m["From"], m["Subject"] = sender, subject
    m["Date"] = format_datetime(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc))
    m["Message-ID"] = f"<{abs(hash((sender, subject, day, body)))}@test>"
    m.set_content(body)
    return m.as_bytes(), day, body


TWILIO = "Twilio <noreply@twilio.com>"
MAILBOX = [
    mail(TWILIO, "Your Twilio account has been recharged", date(Y, 7, 21),
         "we charged the payment method ( **** 4100 ) $10.03 to bring the balance to $20.00."),
    mail(TWILIO, "Your Twilio account has been recharged", date(Y, 10, 30),
         "we charged the payment method ( **** 5111 ) $40.73 to bring the balance to $50.00."),
    mail(TWILIO, "Your Twilio account has been funded", date(Y, 10, 31),
         "We charged the Credit Card ( **** 4100 ) $50.00\nto bring the balance to $50.00."),
    mail("Cloudflare <noreply@notify.cloudflare.com>", "Your invoice is available", date(Y, 9, 8),
         "Your latest invoice is ready.\nAmount: $10.46"),
    mail("Google Payments <payments-noreply@google.com>", "Google: Thank you", date(Y, 10, 31),
         "Your purchase of a Play developer account.\nTotal: $25.00"),
    mail("Squarespace <no-reply@squarespace.com>", "Thank you for choosing Squarespace Domains", date(Y, 4, 4),
         "We processed the registration of your order.\nRenews on Mar 20 for $20.00"),
    mail("Some Other Shop <orders@othershop.test>", "Your receipt", date(Y, 4, 22), "Total: $39.00"),
    mail("NTTA <billing@ntta.test>", "Payment failed", date(Y, 5, 30), "Your payment of $10.00 failed."),
    mail("Railway <hello@notify.railway.app>", "New this week", date(Y, 6, 28), "Teams save $20.00 a month."),
    mail("Railway Corporation <invoice@stripe.test>", "Your receipt from Railway Corporation", date(Y, 9, 1),
         "Pro plan $20.00\nUsage $40.70\nAmount paid $60.70"),
    mail("Anthropic, PBC <invoice@mail.anthropic.test>", "Your receipt from Anthropic, PBC", date(Y, 3, 29),
         "Amount paid $86.75"),
]


def finder(amount, lo, hi):
    """What Gmail does: messages in the window mentioning the amount."""
    return [raw for raw, day, body in MAILBOX if lo <= day < hi and f"{amount:,.2f}" in body]


def receipt_of(expense_id):
    e = db.session.get(Expense, expense_id)
    return e.receipt_original_name or ""


def stored_files():
    folder = pathlib.Path(TMP) / "receipts"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    box = ReceiptMailbox(business_id=bbb.id, address="owner@example.test", password="x")
    provider = ServiceProvider(name="cloudflare", display_name="Cloudflare")
    card = BankConnection(business_id=bbb.id, provider="statement", label="Chase Sapphire", token="",
                          kind="personal", owner_name="Michael Bean")
    db.session.add_all([box, provider, card])
    db.session.flush()

    def exp(amount, description, day, business=None):
        row = Expense(amount=amount, description=description, category="misc", date=day,
                      business_id=(business or bbb).id)
        db.session.add(row)
        db.session.flush()
        return row.id

    ids = {
        "twilio": exp(10.03, "Twilio", date(Y, 7, 23)),
        "twenty": exp(20.00, "Twilio", date(Y, 7, 23)),
        "funded": exp(50.00, "Twilio, texting balance initial setup", date(Y, 10, 30), ehq),
        "month": exp(10.46, "Cloudflare - entertainhq.com registration (Sep)", date(Y, 9, 30)),
        "google": exp(25.00, "Google Play developer account", date(Y, 10, 31), ehq),
        "squarespace": exp(20.00, "Builtbybeans.com domain", date(Y, 4, 4)),
        "squarespace2": exp(20.00, "Squarespace Domains", date(Y, 4, 4)),
        "chuys": exp(39.00, "Chuy's", date(Y, 4, 23)),
        "ntta": exp(10.00, "NTTA toll", date(Y, 5, 31)),
        "promo": exp(20.00, "Railway - something else", date(Y, 6, 30)),
        "plan": exp(20.00, "Railway - Hosting", date(Y, 9, 1)),
        "usage": exp(40.70, "Railway - Usage", date(Y, 9, 1)),
        "whole": exp(60.70, "Railway - The whole bill", date(Y, 9, 2)),
        "first": exp(86.75, "Claude (28 Mar) [unallocated]", date(Y, 3, 28)),
        "second": exp(86.75, "Claude Code", date(Y, 4, 1)),
    }
    db.session.add(ServiceCostEntry(provider_id=provider.id, resource_identifier="zone", period_start=date(Y, 9, 1),
                                    period_end=date(Y, 9, 30), raw_amount=10.46, allocated_amount=10.46,
                                    description="x", expense_id=ids["month"]))
    db.session.commit()

    print("1. The figure that is not the charge is not read as the charge")
    check("Twilio's charge, not the balance it tops up to",
          rs.read_amount(MAILBOX[0][2]) == 10.03, rs.read_amount(MAILBOX[0][2]))
    check("a renewal price is not what was paid",
          rs.read_amount("Renews on Mar 20 for $20.00\nTotal paid $14.00") == 14.00)
    check("an ordinary receipt reads as it did", rs.read_amount("Subtotal $20.00\nTotal $21.32") == 21.32)

    print("2. An expense finds its message, whatever the subject")
    before_mail = len(stored_files())
    found = rs.hunt(db.session.get(ReceiptMailbox, box.id), finder=finder)
    check("a recharge the word search never returned", "recharged" in receipt_of(ids["twilio"]), receipt_of(ids["twilio"]))
    check("the real top-up, past the mail that only names the balance",
          "funded" in receipt_of(ids["funded"]), receipt_of(ids["funded"]))
    check("a vendor's month reaches back to its bill, three weeks before its date",
          receipt_of(ids["month"]).startswith("Your invoice"), receipt_of(ids["month"]))
    check("a subject with no receipt word in it", receipt_of(ids["google"]).startswith("Google"), receipt_of(ids["google"]))
    check("the mailbox can belong to another company's owner",
          db.session.get(Expense, ids["google"]).business_id == db.session.get(Business, bbb.id).id + 1)
    check("it is the expense's own to keep", db.session.get(Expense, ids["twilio"]).receipt_filename is not None)

    print("3. Nothing short of the vendor and the exact charge attaches")
    check("the balance it was topped up to proves nothing", receipt_of(ids["twenty"]) == "", receipt_of(ids["twenty"]))
    check("nor does a renewal price", receipt_of(ids["squarespace2"]) == "", receipt_of(ids["squarespace2"]))
    check("a stranger's receipt for the same money", receipt_of(ids["chuys"]) == "", receipt_of(ids["chuys"]))
    check("a payment that failed", receipt_of(ids["ntta"]) == "", receipt_of(ids["ntta"]))
    check("a vendor's marketing that happens to name the figure", receipt_of(ids["promo"]) == "", receipt_of(ids["promo"]))

    print("4. Two rows for one charge, and one bill for several rows")
    check("the earlier of a charge booked twice takes the receipt", "Anthropic" in receipt_of(ids["first"]),
          receipt_of(ids["first"]))
    check("and the other stays missing, which is what shows it", receipt_of(ids["second"]) == "",
          receipt_of(ids["second"]))
    plan, usage = db.session.get(Expense, ids["plan"]), db.session.get(Expense, ids["usage"])
    check("a line inside a bigger bill is not that bill's charge, so a row for it stays missing",
          not plan.receipt_filename and not usage.receipt_filename, (plan.receipt_filename, usage.receipt_filename))
    check("the row for what was really charged takes it", "Railway" in receipt_of(ids["whole"]), receipt_of(ids["whole"]))
    check("the count is of expenses found", found == 6, found)

    print("5. Mail is used, not hoarded")
    used = {e.receipt_filename for e in Expense.query.all() if e.receipt_filename}
    check("every message kept is proving something", set(stored_files()) == used, (stored_files(), used))
    check("nothing the hunt rejected reached the board",
          not Receipt.query.filter(Receipt.sender.like("%othershop%")).count()
          and not Receipt.query.filter(Receipt.sender.like("%ntta%")).count())
    files_now = stored_files()
    check("a second run finds nothing more", rs.hunt(db.session.get(ReceiptMailbox, box.id), finder=finder) == 0)
    check("and stores nothing more", stored_files() == files_now)

    keep = date.today() - timedelta(days=5)
    stamp = mail("Linode <billing@linode.test>", "Your invoice", keep, "Total: $12.34")
    MAILBOX.append(stamp)
    swept = rs.sync_mailbox(db.session.get(ReceiptMailbox, box.id), fetcher=lambda m, s: [stamp[0]])
    check("the sweep keeps it waiting first", Receipt.query.filter_by(status="unmatched").count() == 1, swept)
    kept_before = len(stored_files())
    ids["linode"] = exp(12.34, "Linode", keep)
    db.session.commit()
    rs.hunt(db.session.get(ReceiptMailbox, box.id), finder=finder)
    check("the hunt uses what the sweep kept rather than a second copy",
          len(stored_files()) == kept_before and Receipt.query.filter_by(status="unmatched").count() == 0,
          (kept_before, len(stored_files())))

    print("6. No document anywhere")
    old = date.today() - timedelta(days=40)

    def lined(amount, description, day, ref):
        eid = exp(amount, description, day)
        db.session.add(BankTransaction(connection_id=card.id, business_id=bbb.id, external_id=ref,
                                       amount=-amount, occurred_on=day, status="sent", kind="statement",
                                       counterparty=description.upper(), disposition="expense", expense_id=eid))
        db.session.commit()
        return eid

    ids["small"] = lined(26.40, "Taqueria", old, "s1")
    ids["large"] = lined(107.69, "Cambridge membership", old, "s2")
    ids["recent"] = lined(12.69, "QuikTrip", date.today() - timedelta(days=10), "s3")
    ids["typed"] = exp(4.50, "Twilio phone number registration", old)
    db.session.commit()
    check("one small old charge has its statement line", rs.attach_statement_lines() == 1)
    small = db.session.get(Expense, ids["small"])
    check("named as that and not as a receipt", small.receipt_original_name.startswith(rs.STATEMENT_PROOF),
          small.receipt_original_name)
    import pypdf
    with open(pathlib.Path(TMP) / "receipts" / small.receipt_filename, "rb") as fh:
        text = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(fh.read())).pages)
    check("the document says what it is and what the bank shows",
          "not the merchant's receipt" in text and "TAQUERIA" in text and "$26.40" in text, text[:200])
    check("from $75 up it stays missing", not db.session.get(Expense, ids["large"]).receipt_filename)
    check("a charge from this month may still have a receipt coming", not db.session.get(Expense, ids["recent"]).receipt_filename)
    check("no bank line, nothing to say", not db.session.get(Expense, ids["typed"]).receipt_filename)
    check("running it again writes nothing more", rs.attach_statement_lines() == 0)

    proof_file = small.receipt_filename
    MAILBOX.append(mail("Taqueria <orders@taqueria.test>", "Your order", old - timedelta(days=1), "Total: $26.40"))
    rs.hunt(db.session.get(ReceiptMailbox, box.id), finder=finder)
    small = db.session.get(Expense, ids["small"])
    check("a real receipt turning up later replaces it", small.receipt_original_name.startswith("Your order"),
          small.receipt_original_name)
    check("and the stand-in is gone from the disk", proof_file not in stored_files())

    stale = Receipt(mailbox_id=box.id, message_key="old-1", sender="Mortgage <m@bank.test>", vendor="Mortgage",
                    subject="Your payment has posted", received_on=date.today() - timedelta(days=60), amount=1654.22,
                    filename=None, status="unmatched")
    fresh = Receipt(mailbox_id=box.id, message_key="new-1", sender="Shop <s@shop.test>", vendor="Shop",
                    subject="Your receipt", received_on=date.today() - timedelta(days=5), amount=9.0,
                    filename=None, status="unmatched")
    db.session.add_all([stale, fresh])
    db.session.commit()
    rs.set_aside_old_unmatched()
    check("mail nothing has wanted for 45 days stops asking", db.session.get(Receipt, stale.id).status == "ignored")
    check("a recent one still waits", db.session.get(Receipt, fresh.id).status == "unmatched")

    print("7. Failing out loud, and a statement setting it off")
    real_fetch, real_hunt = rs.fetch, rs.hunt
    rs.fetch = lambda m, s: []

    def broken(mailbox, finder=None):
        raise rs.MailboxError("The mailbox refused the app password.")

    rs.hunt = broken
    rs.sync_mailbox(db.session.get(ReceiptMailbox, box.id))
    reread = db.session.get(ReceiptMailbox, box.id)
    check("a failed search leaves the read standing and says so",
          reread.last_ok is True and "stopped" in reread.last_note, reread.last_note)
    rs.fetch, rs.hunt = real_fetch, real_hunt
    ids.update(boss=boss.id, card=card.id, box=box.id)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

page = re.sub(r"\s+", " ", c.get("/admin/books/receipts?view=statement").get_data(as_text=True))
check("Statement only is a tab of its own", "Statement only" in page, page[:200])
page_missing = re.sub(r"\s+", " ", c.get("/admin/books/receipts").get_data(as_text=True))
check("what is relying on a statement line is not on Missing", "QuikTrip" in page_missing and "Twilio phone number" in page_missing)
started = []
real_bg = rs.sync_in_background
rs.sync_in_background = lambda app, mailbox_id: started.append(mailbox_id) or True
csv = ("Transaction Date,Post Date,Description,Category,Type,Amount\n"
       f"01/15/{Y},01/16/{Y},SOME SHOP,Shopping,Sale,-9.99\n")
res = c.post(f"/admin/books/statements/{ids['card']}/upload",
             data={"statement": (io.BytesIO(csv.encode()), "statement.csv")}, content_type="multipart/form-data")
rs.sync_in_background = real_bg
check("uploading a statement goes looking at once", res.status_code == 302 and started == [ids["box"]],
      (res.status_code, started))

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
