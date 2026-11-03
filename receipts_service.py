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
"""
import email
import hashlib
import imaplib
import os
import re
import sys
import uuid
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


def read_amount(text):
    """The charge a receipt is for: the amount on a line that says total or
    paid, the last such line winning (totals come last); otherwise the
    largest amount on it. None when it names no amount."""
    best = None
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


def parse(raw):
    """One raw message -> the receipt it is, or None. Returns a dict with
    key, sender, vendor, subject, received_on, amount, file (bytes),
    file_name, file_ext."""
    msg = email.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    if not looks_like_receipt(subject):
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
            "received_on": received, "amount": amount, "file": file, "file_name": file_name,
            "file_ext": ext}


# ── The mailbox ──────────────────────────────────────────


def fetch(mailbox, since):
    """Raw messages since `since` whose subject reads like a receipt. Gmail
    is asked with its own search, which reaches every label; anything else
    gets the plain IMAP equivalent."""
    try:
        conn = imaplib.IMAP4_SSL(mailbox.imap_host, 993, timeout=30)
        conn.login(mailbox.address, mailbox.password or "")
    except imaplib.IMAP4.error as err:
        raise MailboxError("The mailbox refused the app password. Make a new one and save it.") from err
    except OSError as err:
        raise MailboxError(f"Could not reach {mailbox.imap_host}: {str(err)[:100]}") from err
    try:
        folder = '"[Gmail]/All Mail"' if "gmail" in mailbox.imap_host else "INBOX"
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            conn.select("INBOX", readonly=True)
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
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts")
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(folder, name), "wb") as fh:
        fh.write(data)
    return name


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
    exact = [e for e in rows if first is not None and abs(round(e.amount, 2) - first) < 0.005]
    if not exact:
        # Another total on the same receipt: only when it picks out one
        # charge, because a second figure is a weaker reading than the first.
        others = [e for e in rows if any(abs(round(e.amount, 2) - a) < 0.005 for a in amounts - {first})]
        exact = others if len(others) == 1 else []
    word = (receipt.vendor or "").lower()
    said = _words(f"{receipt.vendor} {receipt.subject}")

    def named(e):
        return (bool(word) and word in (e.description or "").lower()) or bool(said & _words(e.description))

    # A single charge that names the vendor wins; a vendor's own split month
    # beats a stranger's charge that merely costs the same.
    if not any(named(e) for e in exact):
        whole = _match_month_of_a_vendor(receipt, amounts)
        if whole is not None or not exact:
            return whole

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
    from models import db, Expense, SalesTaxFiling
    done = 0
    for filing in SalesTaxFiling.query.filter(SalesTaxFiling.filed_at.isnot(None)).all():
        files = list(filing.files)
        if not files:
            continue
        paid = round(filing.amount_paid or 0.0, 2)
        amounts = {paid, round(paid + (filing.processing_fee or 0.0), 2)} - {0.0}
        day = filing.filed_at.date()
        for e in (Expense.query.filter(Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                                       Expense.date >= day - timedelta(days=MATCH_BEFORE),
                                       Expense.date <= day + timedelta(days=MATCH_AFTER)).all()):
            if not any(abs(round(e.amount, 2) - a) < 0.005 for a in amounts):
                continue
            src = os.path.join(current_app.config["UPLOAD_FOLDER"], "tax_filings", files[0].stored_name)
            if not os.path.exists(src):
                break
            ext = os.path.splitext(files[0].stored_name)[1] or ".pdf"
            name = f"{uuid.uuid4().hex}{ext}"
            os.makedirs(_receipts_dir(), exist_ok=True)
            shutil.copyfile(src, os.path.join(_receipts_dir(), name))
            _attach(e, name, files[0].original_name)
            done += 1
            break
    db.session.flush()
    return done


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
    from models import db, Receipt
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
    mailbox.last_ok = True
    mailbox.last_synced_at = now
    mailbox.last_note = (f"{counts['new']:,} new receipt{'' if counts['new'] == 1 else 's'}, "
                         f"{counts['matched']:,} attached")
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
