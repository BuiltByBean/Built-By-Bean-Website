"""Receipts out of every mailbox, attached to the charge each one proves.

    python receipts_service.py

Michael's receipts arrive in three inboxes and none of them is tidy. Each
mailbox (ReceiptMailbox) is opened READ ONLY over IMAP with an app password
its owner made; only messages whose subject reads like a receipt or an
invoice are looked at, and nothing in the mailbox is ever marked, moved or
deleted. For each one the board keeps the sender, the date, the amount it
can read off it, and the document: the PDF it carried, or the message
itself as HTML when the receipt is the email.

Matching is deliberately strict, because a wrong receipt on an expense is
worse than none: an expense in any of the companies' books, with no receipt
yet, for the same amount to the cent, dated from three days before the
email to ten after it (a card posts after the order; an annual renewal can
charge a day before its email). The closest date wins, and a tie goes to
the expense whose description shares a word with the sender. A receipt
that matches nothing waits on the Books page: it may be a charge on a card
whose history is not in yet, or a personal purchase.

That sweep starts from the mail and only sees subjects with the right words,
so it never met a Twilio recharge, a Cloudflare confirmation or Google's "Thank
you". The hunt starts from the expense: for each one with no receipt it asks
the mailbox for that exact amount around that date, and takes a message only
from the vendor it was paid to. Where no document exists anywhere (a restaurant
on a card, a bank's own fee) a small charge gets the bank's statement line as
its proof after a month, named as exactly that, and a real receipt arriving
later replaces it.
"""
import email
import hashlib
import imaplib
import os
import re
import sys
import uuid

import volume_files
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy.exc import IntegrityError

BOOKS_START = date(2026, 4, 1)
OVERLAP_DAYS = 3
MATCH_BEFORE, MATCH_AFTER = 3, 10
SUBJECT_WORDS = ("receipt", "invoice", "payment", "your order", "order confirmation",
                 "billing", "charged", "renewal", "subscription")
SEARCH_WORDS = ("receipt", "invoice", "payment", "order", "billing", "charged", "renewal",
                "subscription")
NOT_A_CHARGE = ("will renew", "upcoming", "reminder", "failed", "declined", "past due",
                "action required", "trial ends", "expiring")
_AMOUNT = re.compile(r"(?:US)?\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+\.[0-9]{2})")
_NOT_THE_CHARGE = re.compile(r"\b(?:balance (?:to|of|is)|renews?|next (?:bill|charge|payment))\b"
                             r"[^\n.$]*(?:\$\s?[0-9,]+\.[0-9]{2})?", re.I)
# Whole words: "Subtotal" is not the total.
_TOTALISH = re.compile(r"(total|amount paid|amount charged|charged|paid|amount due|grand total)",
                       re.I)


class MailboxError(Exception):
    pass


def _decode(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def _text_of(msg):
    """(plain text, html) of a message."""
    plain, html = [], []
    for part in msg.walk():
        kind = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        (plain if kind == "text/plain" else html if kind == "text/html" else plain).append(text)
    return "\n".join(plain), "\n".join(html)


def _strip(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<br\s*/?>|</p>|</tr>|</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text.replace("&nbsp;", " ").replace("&amp;", "&"))


def pdf_text(data):
    try:
        from pypdf import PdfReader
        import io
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:5])
    except Exception:  # noqa: BLE001 - a PDF that will not read still attaches
        return ""


def _without_balances(text):
    """A message's text with the figures that are not the charge taken out.
    Twilio says "we charged the card $10.03 to bring the balance to $20.00" and
    Squarespace "renews on Mar 20, 2027 for $20.00": read as they stand, those
    are a $20 charge that never happened."""
    return _NOT_THE_CHARGE.sub("", text or "")


def read_amount(text):
    """The charge a receipt is for: the amount on a line that says total or
    paid, the last such line winning (totals come last); otherwise the
    largest amount on it. None when it names no amount."""
    best = None
    text = _without_balances(text)
    for line in (text or "").splitlines():
        found = [float(a.replace(",", "")) for a in _AMOUNT.findall(line)]
        if found and _TOTALISH.search(line):
            best = found[-1]
    if best is not None:
        return round(best, 2)
    every = [float(a.replace(",", "")) for a in _AMOUNT.findall(text or "")]
    return round(max(every), 2) if every else None


def looks_like_receipt(subject):
    s = (subject or "").lower()
    return any(w in s for w in SUBJECT_WORDS) and not any(w in s for w in NOT_A_CHARGE)


def vendor_of(sender):
    """'Railway <billing@railway.app>' -> 'Railway'; else the domain's name."""
    name, addr = parseaddr(sender or "")
    if name and "@" not in name:
        return name.strip().strip('"')[:120]
    domain = addr.split("@")[-1] if "@" in addr else addr
    parts = [p for p in domain.split(".") if p not in ("mail", "email", "billing", "noreply", "com",
                                                         "io", "app", "net", "org", "co")]
    return (parts[-1] if parts else domain).capitalize()[:120]


def parse(raw, any_subject=False):
    """One raw message -> the receipt it is, or None. Returns a dict with
    key, sender, vendor, subject, received_on, amount, text, file (bytes),
    file_name, file_ext. The sweep only takes subjects that read as a receipt;
    the hunt has already named the amount and the vendor, so it takes any."""
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    if not any_subject and not looks_like_receipt(subject):
        return None
    sender = _decode(msg.get("From"))
    try:
        received = parsedate_to_datetime(msg.get("Date")).date()
    except Exception:  # noqa: BLE001
        received = None
    key = (msg.get("Message-ID") or "").strip()[:200]
    if not key:
        key = "fp:" + hashlib.sha1(f"{sender}|{msg.get('Date')}|{subject}".encode()).hexdigest()
    plain, html = _text_of(msg)
    pdf, pdf_name = None, None
    for part in msg.walk():
        name = _decode(part.get_filename() or "")
        if name.lower().endswith(".pdf") or part.get_content_type() == "application/pdf":
            pdf, pdf_name = part.get_payload(decode=True), name or "receipt.pdf"
            break
    # Both: a receipt's plain part is often a one-line fallback while the
    # figures live in its HTML.
    text = "\n".join(t for t in (plain, _strip(html)) if t)
    if pdf:
        text = pdf_text(pdf) + "\n" + text
    amount = read_amount(text)
    if pdf:
        file, file_name, ext = pdf, pdf_name, "pdf"
    else:
        body = html or ("<pre>" + (plain or "").replace("<", "&lt;") + "</pre>")
        file = (f"<!doctype html><meta charset='utf-8'><title>{subject}</title>"
                f"<p><b>From:</b> {sender}<br><b>Subject:</b> {subject}<br>"
                f"<b>Date:</b> {msg.get('Date')}</p><hr>{body}").encode("utf-8")
        file_name, ext = (re.sub(r"[^\w .-]+", "", subject)[:80] or "receipt") + ".html", "html"
    return {"key": key, "sender": sender[:200], "vendor": vendor_of(sender), "subject": subject[:300],
            "received_on": received, "amount": amount, "text": text, "file": file, "file_name": file_name,
            "file_ext": ext}


# ── The mailbox ──────────────────────────────────────────


def _connect(mailbox):
    """The mailbox, open read only: nothing here can mark, move or delete."""
    try:
        conn = imaplib.IMAP4_SSL(mailbox.imap_host, 993, timeout=30)
        conn.login(mailbox.address, mailbox.password or "")
    except imaplib.IMAP4.error as err:
        raise MailboxError("The mailbox refused the app password. Make a new one and save it.") from err
    except OSError as err:
        raise MailboxError(f"Could not reach {mailbox.imap_host}: {str(err)[:100]}") from err
    folder = '"[Gmail]/All Mail"' if "gmail" in mailbox.imap_host else "INBOX"
    status, _ = conn.select(folder, readonly=True)
    if status != "OK":
        conn.select("INBOX", readonly=True)
    return conn


def fetch(mailbox, since):
    """Raw messages since `since` whose subject reads like a receipt. Gmail
    is asked with its own search, which reaches every label; anything else
    gets the plain IMAP equivalent."""
    conn = _connect(mailbox)
    try:
        if "gmail" in mailbox.imap_host:
            # Single words only: a quoted phrase inside the quoted IMAP
            # argument would need escaping Gmail does not document. parse()
            # applies the exact subject test afterwards.
            words = " OR ".join(f"subject:{w}" for w in SEARCH_WORDS)
            query = f"after:{since:%Y/%m/%d} ({words}) -in:spam -in:trash"
            status, data = conn.search(None, "X-GM-RAW", f'"{query}"')
        else:
            status, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        ids = (data[0] or b"").split() if status == "OK" else []
        for mid in ids[-800:]:
            status, parts = conn.fetch(mid, "(BODY.PEEK[])")
            if status == "OK" and parts and isinstance(parts[0], tuple):
                yield parts[0][1]
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _store(data, ext):
    from flask import current_app
    import volume_files
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts")
    # The nightly read runs on a service with no volume: volume_files hands
    # the file to the web service's.
    return volume_files.write(folder, f"{uuid.uuid4().hex}.{ext}", data)


_TOTAL_WORD = re.compile(r"\b(total|amount paid|amount charged|charged|paid|amount due|grand total)\b",
                         re.I)
_CANDIDATES = {}


def _receipts_dir():
    from flask import current_app
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts")


def candidate_amounts(receipt):
    """The amount read when the receipt arrived, and every other amount on a
    line that says total or paid. A receipt reads $200.00 on its subtotal
    line and $213.20 once tax is on (Anthropic's, 2026-10-20), and only one
    of them is the charge. Read back off the stored document, so receipts
    that arrived before this existed are tried too."""
    out = {round(receipt.amount, 2)} if receipt.amount else set()
    name = receipt.filename or ""
    if not name:
        return out
    if name not in _CANDIDATES:
        found = set()
        try:
            with open(os.path.join(_receipts_dir(), name), "rb") as fh:
                data = fh.read()
            text = pdf_text(data) if name.endswith(".pdf") else _strip(data.decode("utf-8", "replace"))
            for line in text.splitlines():
                if _TOTAL_WORD.search(line):
                    found.update(round(float(a.replace(",", "")), 2) for a in _AMOUNT.findall(line))
        except Exception:  # noqa: BLE001 - a document that will not read keeps its first amount
            pass
        _CANDIDATES[name] = {a for a in found if a > 0}
    return out | _CANDIDATES[name]


def _attach(expense, filename, original_name):
    expense.receipt_filename = filename
    expense.receipt_original_name = original_name


def _words(text):
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in ("your", "receipt", "from", "invoice", "payment", "corporation", "inc", "llc")}


def _match_month_of_a_vendor(receipt, amounts):
    """A vendor whose month the board splits across projects (Railway's
    bill, as many rows as there are projects) sends one receipt for the
    whole bill. When a vendor named on the receipt has a month whose rows add
    up to one of its totals, that receipt proves every row of it."""
    from models import db, Expense, ServiceCostEntry, ServiceProvider
    lo = receipt.received_on - timedelta(days=MATCH_AFTER)
    hi = receipt.received_on + timedelta(days=MATCH_AFTER)
    said = _words(f"{receipt.vendor} {receipt.sender} {receipt.subject}")
    groups = {}
    for entry, expense, provider in (db.session.query(ServiceCostEntry, Expense, ServiceProvider)
                                     .join(Expense, ServiceCostEntry.expense_id == Expense.id)
                                     .join(ServiceProvider, ServiceCostEntry.provider_id == ServiceProvider.id)
                                     .filter(Expense.date >= lo, Expense.date <= hi,
                                             Expense.time_entry_id.is_(None)).all()):
        if not (said & _words(f"{provider.name} {provider.display_name}")):
            continue
        key = (provider.id, expense.business_id, expense.date.year, expense.date.month)
        groups.setdefault(key, {})[expense.id] = expense
    for rows in groups.values():
        total = round(sum(e.amount for e in rows.values()), 2)
        waiting = [e for e in rows.values() if not e.receipt_filename]
        if waiting and any(abs(total - a) < 0.005 for a in amounts):
            for e in waiting:
                _attach(e, receipt.filename, receipt.original_name)
            receipt.expense_id = waiting[0].id
            receipt.status = "matched"
            db.session.flush()
            return waiting[0]
    return None


def match(receipt):
    """Attach a receipt to the expense it proves, if exactly one is likely,
    or to a vendor's whole split month. Returns an expense or None."""
    from models import db, Expense
    if receipt.received_on is None:
        return None
    amounts = candidate_amounts(receipt)
    if not amounts:
        return None
    lo = receipt.received_on - timedelta(days=MATCH_BEFORE)
    hi = receipt.received_on + timedelta(days=MATCH_AFTER)
    rows = (Expense.query.filter(Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                                 Expense.date >= lo, Expense.date <= hi).all())
    first = round(receipt.amount, 2) if receipt.amount else None
    exact = [e for e in rows if first is not None and abs(e.charged - first) < 0.005]
    if not exact:
        # Another total on the same receipt: only when it picks out one
        # charge, because a second figure is a weaker reading than the first.
        others = [e for e in rows if any(abs(e.charged - a) < 0.005 for a in amounts - {first})]
        exact = others if len(others) == 1 else []
    word = (receipt.vendor or "").lower()
    said = _words(f"{receipt.vendor} {receipt.subject}")
    seen = f"{receipt.vendor} {receipt.sender} {receipt.subject}".lower()

    def named(e):
        return ((bool(word) and word in (e.description or "").lower()) or bool(said & _words(e.description))
                or any(name in seen for name in vendor_names(e)))

    # Only a charge that names the vendor. A stranger's charge that merely costs
    # the same is not proved by this: Railway's April invoice, which mentions
    # $20.00, sat on a $20 Twilio row for seven months.
    exact = [e for e in exact if named(e)]
    if not exact:
        return _match_month_of_a_vendor(receipt, amounts)

    def score(e):
        return (not named(e), abs((e.date - receipt.received_on).days), e.id)

    best = min(exact, key=score)
    _attach(best, receipt.filename, receipt.original_name)
    receipt.expense_id = best.id
    receipt.status = "matched"
    db.session.flush()
    return best


def attach_filings():
    """A sales tax payment's receipt is the confirmation WebFile gave, which
    the board already keeps with the return (SalesTaxFiling). Copied into
    the receipts folder, so removing one never removes the other."""
    import shutil
    from flask import current_app
    import books_service
    from models import db, Expense, SalesTaxFiling
    done = 0
    for filing in SalesTaxFiling.query.filter(SalesTaxFiling.filed_at.isnot(None)).all():
        files = list(filing.files)
        paid = round(filing.amount_paid or 0.0, 2)
        if paid <= 0:
            continue
        amounts = {paid, round(paid + (filing.processing_fee or 0.0), 2)}
        day = filing.filed_at.date()
        near = (Expense.query.filter(Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                                     Expense.date >= day - timedelta(days=MATCH_BEFORE),
                                     Expense.date <= day + timedelta(days=MATCH_AFTER)).all())
        exact = [e for e in near if any(abs(e.charged - a) < 0.005 for a in amounts)]
        # WebFile adds a card fee the return does not show, and it is not
        # always typed in: $739.54 of tax was a $756.43 card charge on
        # 2026-10-30. A charge to the Comptroller up to 3% over the tax is
        # the payment, the nearest one first.
        fee_on = [e for e in near
                  if books_service.STATE_TAX_PAYMENT.search(e.description or "")
                  and paid <= e.charged <= paid * books_service.CARD_FEE_ROOM + 0.01]
        for e in (exact or sorted(fee_on, key=lambda x: x.charged - paid)[:1]):
            os.makedirs(_receipts_dir(), exist_ok=True)
            src = (os.path.join(current_app.config["UPLOAD_FOLDER"], "tax_filings", files[0].stored_name)
                   if files else None)
            if src and os.path.exists(src):
                ext = os.path.splitext(files[0].stored_name)[1] or ".pdf"
                name = f"{uuid.uuid4().hex}{ext}"
                with open(src, "rb") as fh:
                    volume_files.write(_receipts_dir(), name, fh.read())
                original = files[0].original_name
            else:
                # No confirmation uploaded: the board's own record of the
                # return, with WebFile's reference numbers, until one is.
                from pm.business_routes import filing_record_pdf
                name = volume_files.write(_receipts_dir(), f"{uuid.uuid4().hex}.pdf",
                                          bytes(filing_record_pdf(filing)))
                original = f"Sales tax return {filing.year} Q{filing.quarter} (board record).pdf"
            _attach(e, name, original)
            done += 1
            break
    db.session.flush()
    return done


# ── The hunt: from the expense to its receipt ──────────────

# A card posts days after the order, and a typed expense is dated by whoever
# typed it, so the search is wider than the sweep's match. The vendor's name
# and the amount to the cent are what make it safe.
HUNT_BEFORE, HUNT_AFTER = 12, 5
HUNT_MESSAGES = 25
# The name a vendor signs its mail with, where the charge goes by another.
SIGNED_AS = {"claude": {"anthropic"}, "chatgpt": {"openai"}, "openai": {"chatgpt"}}
_CHARGE_WORD = re.compile(r"\b(charged|paid|payment|receipt|invoice|total|amount|purchase|order)\b", re.I)
# The first figure after the words that give a charge. Not the whole line: a
# message whose HTML strips down to one long line would then state every figure
# in it. "Amount" alone is a column heading, so it needs its second word.
_STATES_A_CHARGE = re.compile(r"\b(?:total|amount(?: due| paid| charged|:)|charged|paid|purchase of|payment of)"
                              r"[^$\n]{0,80}?\$\s?([0-9,]+\.[0-9]{2})", re.I)
# A statement line stands in only where a missing document is forgivable: the
# IRS asks for a receipt from $75 up, and a month is long enough for one to
# have turned up if it was ever coming.
STATEMENT_PROOF = "Card statement line"
STATEMENT_UNDER = 75.0
STATEMENT_AFTER_DAYS = 30
# Most of what the sweep keeps is a mortgage notice or a car payment. Past this
# age nothing is coming that would match it, so it stops asking to be read.
UNMATCHED_DAYS = 45


def vendor_names(expense):
    """The names mail from whoever was paid would carry: the first real word of
    the expense, and of the bank's own line when there is one."""
    from models import BankTransaction
    line = BankTransaction.query.filter_by(expense_id=expense.id).first()
    names = set()
    for text in (expense.description, line.counterparty if line else ""):
        words = [w.split("'")[0].lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9']+", text or "")]
        first = next((w for w in words if len(w) >= 4), None)
        if first:
            names.add(first)
            names |= SIGNED_AS.get(first, set())
    return names


def hunt_window(expense):
    """Where its receipt would be, as (from, before). A vendor's month is dated
    its last day, and its bill came whenever in that month it came: Cloudflare's
    September row is dated the 30th and its invoice the 8th."""
    from models import ServiceCostEntry
    entry = ServiceCostEntry.query.filter_by(expense_id=expense.id).first()
    if entry is not None and entry.period_start and entry.period_end and entry.period_end > entry.period_start:
        return entry.period_start - timedelta(days=3), entry.period_end + timedelta(days=HUNT_AFTER)
    return expense.date - timedelta(days=HUNT_BEFORE), expense.date + timedelta(days=HUNT_AFTER)


def charged_amounts(text):
    """What a message says was charged: the figure after each word that gives a
    charge, or every figure when none does. A line item is not a charge:
    Railway's $60.70 invoice lists a $20.00 plan and takes $20.00 of included
    usage off, so $40.70 left the bank and no $20.00 ever did."""
    text = _without_balances(text)
    found = _STATES_A_CHARGE.findall(text) or _AMOUNT.findall(text)
    return {round(float(a.replace(",", "")), 2) for a in found}


def proves(got, charge, names):
    """Whether this message is proof of this charge. All of it, because a wrong
    receipt is worse than none: from the vendor, not a failure or a reminder,
    about money, and giving the amount to the cent as what was charged."""
    said = f"{got['sender']} {got['subject']}".lower()
    if not any(name in said for name in names):
        return False
    if any(word in got["subject"].lower() for word in NOT_A_CHARGE):
        return False
    if not _CHARGE_WORD.search(f"{got['subject']}\n{got['text']}"):
        return False
    return any(abs(a - charge) < 0.005 for a in charged_amounts(got["text"]))


def _receipt_row(mailbox, got):
    """The board's row for this message, kept the first time it proves
    something. The hunt never stores mail it does not use."""
    from models import db, Receipt
    row = Receipt.query.filter_by(mailbox_id=mailbox.id, message_key=got["key"]).first()
    if row is not None:
        return row
    row = Receipt(mailbox_id=mailbox.id, message_key=got["key"], sender=got["sender"], vendor=got["vendor"],
                  subject=got["subject"], received_on=got["received_on"], amount=got["amount"],
                  filename=_store(got["file"], got["file_ext"]), original_name=got["file_name"][:300],
                  status="unmatched")
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
    except IntegrityError:
        return Receipt.query.filter_by(mailbox_id=mailbox.id, message_key=got["key"]).first()
    return row


def _find(conn, mailbox, amount, lo, hi):
    """Raw messages in a window that mention an amount."""
    text = f"{amount:,.2f}"
    if "gmail" in mailbox.imap_host:
        query = f"{text} after:{lo:%Y/%m/%d} before:{hi:%Y/%m/%d} -in:spam -in:trash"
        status, data = conn.search(None, "X-GM-RAW", f'"{query}"')
    else:
        status, data = conn.search(None, "SINCE", lo.strftime("%d-%b-%Y"), "BEFORE", hi.strftime("%d-%b-%Y"),
                                   "TEXT", f'"{text}"')
    found = []
    for mid in ((data[0] or b"").split() if status == "OK" else [])[-HUNT_MESSAGES:]:
        status, parts = conn.fetch(mid, "(BODY.PEEK[])")
        if status == "OK" and parts and isinstance(parts[0], tuple):
            found.append(parts[0][1])
    return found


def waiting_for_a_receipt():
    """Oldest first, so of two rows for one charge the earlier takes the receipt
    and the other stays on Missing, which is what shows it was booked twice.
    This year and last: far enough back to reach a typed expense from before
    the books began, and not a search that grows every night for ever."""
    from models import db, Expense
    rows = (Expense.query.filter(Expense.time_entry_id.is_(None),
                                 Expense.date >= date(date.today().year - 1, 1, 1),
                                 db.or_(Expense.receipt_filename.is_(None),
                                        Expense.receipt_original_name.like(STATEMENT_PROOF + "%")))
            .order_by(Expense.date, Expense.id).all())
    return [e for e in rows if e.charged > 0]


def _hunt_one(mailbox, expense, messages):
    """Attach the best of `messages` to `expense`. Returns True if one was."""
    from models import db
    charge = expense.charged
    names = vendor_names(expense)
    hits = [got for got in (parse(raw, any_subject=True) for raw in messages)
            if got is not None and proves(got, charge, names)]
    hits.sort(key=lambda g: (abs((g["received_on"] - expense.date).days) if g["received_on"] else 9999, g["key"]))
    for got in hits:
        row = _receipt_row(mailbox, got)
        if row is None:
            continue
        # One message proves one charge. A vendor's month split across rows is
        # the sweep's to attach (_match_month_of_a_vendor), and only when the
        # rows add up to the bill. A second row left wanting is how a charge
        # booked twice shows itself.
        if row.status == "matched" and row.expense_id and row.expense_id != expense.id:
            continue
        old = expense.receipt_filename
        _attach(expense, row.filename, row.original_name)
        row.expense_id, row.status = expense.id, "matched"
        db.session.flush()
        if old and old != row.filename and not in_use(old):
            _remove(old)
        db.session.commit()
        return True
    return False


def hunt(mailbox, finder=None):
    """Look in one mailbox for every expense still without a receipt. Returns
    how many were found. `finder(amount, lo, hi)` is the mailbox in a test."""
    from models import db
    expenses = waiting_for_a_receipt()
    if not expenses:
        return 0
    # Nothing held open across the network: this runs for minutes on a thread,
    # beside pages and the nightly job that all want to write.
    db.session.commit()
    conn = None
    if finder is None:
        conn = _connect(mailbox)
        finder = lambda amount, lo, hi: _find(conn, mailbox, amount, lo, hi)  # noqa: E731
    found = 0
    try:
        for expense in expenses:
            lo, hi = hunt_window(expense)
            if _hunt_one(mailbox, expense, finder(expense.charged, lo, hi)):
                found += 1
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    return found


def _remove(filename):
    try:
        os.remove(os.path.join(_receipts_dir(), filename))
    except OSError:
        pass


def statement_line_pdf(line, expense):
    """The bank's record of a charge, written out as a document. It says what
    it is: the proof of payment, not the merchant's receipt."""
    from fpdf import FPDF

    def clean(text):
        return str(text or "").encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, STATEMENT_PROOF, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "The bank's record of this charge, not the merchant's receipt.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    conn = line.connection
    for label, value in (("Merchant, as the bank shows it", line.counterparty),
                         ("Date", line.occurred_on.strftime("%b %d, %Y").replace(" 0", " ")),
                         ("Amount", f"${abs(line.amount):,.2f}"),
                         ("Account", conn.label if conn else line.account_name),
                         ("Card holder", (conn.owner_name if conn else "") or "The company"),
                         ("Company", expense.business.name if expense.business else ""),
                         ("Booked as", expense.description)):
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(62, 7, clean(label))
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 7, clean(value), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def attach_statement_lines():
    """Give a small charge that no mailbox has proved its statement line."""
    from models import db, BankTransaction, Expense
    cutoff = date.today() - timedelta(days=STATEMENT_AFTER_DAYS)
    done = 0
    rows = (db.session.query(BankTransaction, Expense).join(Expense, BankTransaction.expense_id == Expense.id)
            .filter(Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                    Expense.date <= cutoff, BankTransaction.status == "sent").all())
    for line, expense in rows:
        if not 0 < expense.charged < STATEMENT_UNDER:
            continue
        name = _store(statement_line_pdf(line, expense), "pdf")
        when = line.occurred_on.isoformat()
        account = line.connection.label if line.connection else "bank"
        _attach(expense, name, f"{STATEMENT_PROOF}, {account}, {when}.pdf"[:300])
        done += 1
    db.session.commit()
    return done


def set_aside_old_unmatched():
    """Mail nothing has wanted for this long stops asking to be read. Kept, and
    the hunt can still use it if a charge for it ever turns up."""
    from models import db, Receipt
    cutoff = date.today() - timedelta(days=UNMATCHED_DAYS)
    rows = Receipt.query.filter(Receipt.status == "unmatched", Receipt.received_on < cutoff).all()
    for row in rows:
        row.status = "ignored"
    db.session.commit()
    return len(rows)


def in_use(filename, but_not_expense_id=None):
    """Whether a receipt file still proves something: one document can stand
    for a whole split month, so deleting one expense must not delete it."""
    from models import Expense, Receipt
    if not filename:
        return False
    q = Expense.query.filter(Expense.receipt_filename == filename)
    if but_not_expense_id is not None:
        q = q.filter(Expense.id != but_not_expense_id)
    return q.first() is not None or Receipt.query.filter_by(filename=filename).first() is not None


def rematch():
    """Try every waiting receipt again: an expense may have arrived since
    (a bank line settles, a statement is imported)."""
    import books_service
    from models import db, Receipt
    # A charge typed on the expense form reaches no bank path, so the nightly
    # run is what catches one that paid a recorded return.
    books_service.settle_sales_tax()
    done = attach_filings()
    for r in Receipt.query.filter_by(status="unmatched").all():
        if match(r) is not None:
            done += 1
    db.session.commit()
    return done


def sync_mailbox(mailbox, fetcher=None):
    """Read one mailbox. Returns counts, or {"error": ...}."""
    from models import db, Receipt
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = mailbox.read_from or BOOKS_START
    if mailbox.last_synced_at and mailbox.last_ok:
        since = max(since, (mailbox.last_synced_at - timedelta(days=OVERLAP_DAYS)).date())
    counts = {"read": 0, "new": 0, "matched": 0}
    try:
        for raw in (fetcher or fetch)(mailbox, since):
            got = parse(raw)
            if got is None:
                continue
            counts["read"] += 1
            if Receipt.query.filter_by(mailbox_id=mailbox.id, message_key=got["key"]).first():
                continue
            row = Receipt(mailbox_id=mailbox.id, message_key=got["key"], sender=got["sender"],
                          vendor=got["vendor"], subject=got["subject"],
                          received_on=got["received_on"], amount=got["amount"],
                          filename=_store(got["file"], got["file_ext"]),
                          original_name=got["file_name"][:300], status="unmatched")
            # In a savepoint: a second read of the same mailbox running at
            # the same moment (2026-11-03, Connect pressed while the first
            # read was still going) saves the same message first, and one
            # duplicate must not throw away every receipt read before it.
            try:
                with db.session.begin_nested():
                    db.session.add(row)
                    db.session.flush()
            except IntegrityError:
                continue
            counts["new"] += 1
            if match(row) is not None:
                counts["matched"] += 1
    except MailboxError as err:
        db.session.rollback()
        mailbox.last_ok = False
        mailbox.last_note = str(err)[:300]
        mailbox.last_synced_at = now
        db.session.commit()
        return {"error": str(err)}
    counts["matched"] += rematch()
    # A test's fetcher stands in for the mailbox, and these need the real one.
    hunt_stopped = ""
    if fetcher is None:
        try:
            counts["matched"] += hunt(mailbox)
        except (MailboxError, imaplib.IMAP4.error, OSError) as err:
            hunt_stopped = f". The search for missing receipts stopped: {str(err)[:120]}"
        counts["matched"] += attach_statement_lines()
        set_aside_old_unmatched()
    mailbox.last_ok = True
    mailbox.last_synced_at = now
    mailbox.last_note = (f"{counts['new']:,} new receipt{'' if counts['new'] == 1 else 's'}, "
                         f"{counts['matched']:,} attached{hunt_stopped}")[:300]
    db.session.commit()
    return counts


_running = set()
_lock = __import__("threading").Lock()


def sync_in_background(app, mailbox_id):
    """Read one mailbox on a thread of its own, so the page that asked
    answers at once (a first read back to April runs past gunicorn's sixty
    seconds) and a second press while it runs starts nothing. Returns False
    when a read of that mailbox is already going."""
    import threading
    with _lock:
        if mailbox_id in _running:
            return False
        _running.add(mailbox_id)

    def run():
        try:
            with app.app_context():
                from models import db, ReceiptMailbox
                box = db.session.get(ReceiptMailbox, mailbox_id)
                if box is not None:
                    sync_mailbox(box)
        except Exception as err:  # noqa: BLE001 - a background read never takes the site down
            app.logger.warning("receipts: background read of %s failed: %s", mailbox_id, err)
        finally:
            with _lock:
                _running.discard(mailbox_id)

    threading.Thread(target=run, name=f"receipts-{mailbox_id}", daemon=True).start()
    return True


def reading(mailbox_id):
    return mailbox_id in _running


def sync_all(app):
    from models import ReceiptMailbox
    with app.app_context():
        boxes = ReceiptMailbox.query.order_by(ReceiptMailbox.id).all()
        for box in boxes:
            result = sync_mailbox(box)
            print(f"  receipts {box.address:34} {result.get('error') or box.last_note}", flush=True)
        if not boxes:
            print(f"  receipts: {rematch():,} attached from what the board already keeps", flush=True)


def main():
    from app import create_app
    sync_all(create_app())
    return 0


if __name__ == "__main__":
    sys.exit(main())
