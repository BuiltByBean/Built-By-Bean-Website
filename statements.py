"""Card and bank statements downloaded as CSV, read into the books.

Michael's business charges since April are spread over three things with no
feed: Built by Bean's Chase business debit card, his personal debit card and
his personal credit card. Chase (like every bank) lets a statement be
downloaded as CSV, so a statement is a feed that arrives by hand: each row
becomes a BankTransaction on a BankConnection whose provider is
"statement", and from there it is the same machine as Mercury's: vendor
rules sort it, an expense already typed for the same charge is adopted
rather than doubled, receipts waiting in the mailboxes attach, and what
nobody recognises waits on the review list with Claude's suggestion.

The formats read, by their header row:
  Chase credit card   Transaction Date, Post Date, Description, Category,
                      Type, Amount, Memo   (a purchase is negative)
  Chase checking      Details, Posting Date, Description, Amount, Type,
                      Balance, Check or Slip #   (a debit is negative)
  anything else with a date column, a description column, and either one
  Amount column or Debit and Credit columns.
A card whose export shows charges as POSITIVE numbers (some do) is marked
so on its account, and its amounts are flipped to the bank's sign: money
out is negative, everywhere in the books.

A row's id is a fingerprint of its date, description and amount, plus how
many identical rows came before it in the same file, so uploading the same
statement twice, or two statements that overlap, stores each charge once,
while two genuine same-day coffees at the same price stay two.
"""
import csv
import hashlib
import io
import re
from datetime import date, datetime

DATE_HEADERS = ("transaction date", "trans. date", "trans date", "date", "posting date",
                "post date", "posted date")
DESC_HEADERS = ("description", "merchant", "payee", "name", "details")
AMOUNT_HEADERS = ("amount", "transaction amount")
DEBIT_HEADERS = ("debit", "withdrawal", "withdrawals")
CREDIT_HEADERS = ("credit", "deposit", "deposits")
BALANCE_HEADERS = ("balance", "running balance", "running bal.")
CATEGORY_HEADERS = ("category",)


class StatementError(Exception):
    pass


def _pick(headers, wanted):
    low = [h.strip().lower() for h in headers]
    for w in wanted:
        if w in low:
            return low.index(w)
    return None


def _money(text):
    text = (text or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _date(text):
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse(text, charges_positive=False):
    """[{date, description, amount, kind, ref}] in the bank's sign. Raises
    StatementError when the file is not a statement it can read."""
    text = (text or "").lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise StatementError("That file is empty.")
    head = rows[0]
    di, ti = _pick(head, DATE_HEADERS), _pick(head, DESC_HEADERS)
    ai, dbi, cri = _pick(head, AMOUNT_HEADERS), _pick(head, DEBIT_HEADERS), _pick(head, CREDIT_HEADERS)
    kind_i = _pick(head, ("type",))
    bal_i = _pick(head, BALANCE_HEADERS)
    cat_i = _pick(head, CATEGORY_HEADERS)
    if di is None or ti is None or (ai is None and dbi is None and cri is None):
        raise StatementError("That file has no date, description and amount columns. "
                             "Download the statement as CSV.")
    out = []
    for r in rows[1:]:
        r = r + [""] * (len(head) - len(r))
        when = _date(r[di])
        if when is None:
            continue
        if ai is not None:
            amount = _money(r[ai])
            if amount is None:
                continue
            if charges_positive:
                amount = -amount
        else:
            debit = _money(r[dbi]) if dbi is not None else None
            credit = _money(r[cri]) if cri is not None else None
            if debit is None and credit is None:
                continue
            amount = (credit or 0.0) - abs(debit or 0.0)
        out.append({"date": when, "description": " ".join(r[ti].split())[:300],
                    "amount": round(amount, 2),
                    "kind": (r[kind_i].strip()[:40] if kind_i is not None else ""),
                    "category": (r[cat_i].strip()[:80] if cat_i is not None else ""),
                    "balance": _money(r[bal_i]) if bal_i is not None else None})
    if not out:
        raise StatementError("No transactions could be read from that file.")
    seen = {}
    for row in out:
        base = f"{row['date']}|{row['description'].upper()}|{row['amount']:.2f}"
        seen[base] = seen.get(base, 0) + 1
        row["ref"] = "st:" + hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()[:24]
    return out


_CARD_PAYMENT = re.compile(
    r"\b(PAYMENT THANK YOU|AUTOMATIC PAYMENT|AUTOPAY|ONLINE PAYMENT|PAYMENT RECEIVED|"
    r"CREDIT CARD PAYMENT|EPAY|ACH PAYMENT|MOBILE PAYMENT)\b")


def is_card_payment(description):
    """Paying the card off is money moving between the owner's accounts."""
    return bool(_CARD_PAYMENT.search((description or "").upper()))


def balances_of(rows):
    """(opening, opening_on, closing, closing_on) from a statement whose rows
    carry the balance after each one (Chase checking does), else None.

    The file's order is read from the balances themselves: newest first, each
    balance is the next row's plus this row's amount; oldest first, the
    previous row's plus this one's. Whichever order the arithmetic holds for
    wins, and a file it holds for in neither is not trusted."""
    rows = [r for r in rows if r.get("balance") is not None]
    if not rows:
        return None
    if len(rows) == 1:
        r = rows[0]
        return round(r["balance"] - r["amount"], 2), r["date"], round(r["balance"], 2), r["date"]

    def fits(seq):
        return sum(abs(round(seq[i - 1]["balance"] + seq[i]["amount"], 2) - seq[i]["balance"]) < 0.005
                   for i in range(1, len(seq)))

    forward, backward = fits(rows), fits(list(reversed(rows)))
    if max(forward, backward) < (len(rows) - 1) * 0.9:
        return None
    oldest_first = rows if forward >= backward else list(reversed(rows))
    first, last = oldest_first[0], oldest_first[-1]
    return (round(first["balance"] - first["amount"], 2), first["date"],
            round(last["balance"], 2), last["date"])


def remember_balances(conn, rows):
    """Keep the earliest opening and the latest closing balance any upload has
    shown, so the lines between them can be held to the difference."""
    got = balances_of(rows)
    if got is None:
        return False
    opening, opening_on, closing, closing_on = got
    if conn.opening_on is None or opening_on < conn.opening_on:
        conn.opening_balance, conn.opening_on = opening, opening_on
    if conn.balance_on is None or closing_on >= conn.balance_on:
        conn.balance, conn.balance_on = closing, closing_on
    return True


def board_balance(conn):
    """What the board's own lines say the account held on `balance_on`: the
    opening balance plus every settled line from the opening day on. Equal to
    the bank's figure means no statement is missing in between."""
    from models import db, BankTransaction
    if conn.opening_on is None or conn.balance_on is None:
        return None
    total = (db.session.query(db.func.coalesce(db.func.sum(BankTransaction.amount), 0.0))
             .filter(BankTransaction.connection_id == conn.id, BankTransaction.status == "sent",
                     BankTransaction.occurred_on >= conn.opening_on,
                     BankTransaction.occurred_on <= conn.balance_on).scalar())
    return round((conn.opening_balance or 0.0) + (total or 0.0), 2)


# An alert arrives when the card is used; the statement dates the same charge
# the day it was made (cards) or posted (checking), up to a few days later.
FOLD_BEFORE, FOLD_AFTER = 1, 5


def _fold_alert(conn, row):
    """The provisional line an alert wrote for this statement row, if any."""
    from datetime import timedelta
    from models import BankTransaction
    rows = (BankTransaction.query.filter(BankTransaction.connection_id == conn.id,
                                         BankTransaction.kind == "alert",
                                         BankTransaction.status == "sent",
                                         BankTransaction.occurred_on >= row["date"] - timedelta(days=FOLD_AFTER),
                                         BankTransaction.occurred_on <= row["date"] + timedelta(days=FOLD_BEFORE))
            .all())
    rows = [l for l in rows if abs(l.amount - row["amount"]) < 0.005]
    if not rows:
        return None
    return min(rows, key=lambda l: (abs((l.occurred_on - row["date"]).days), l.id))


def import_rows(conn, rows):
    """Write parsed rows onto the connection as bank lines, classify each,
    and attach any waiting receipts. A row that an alert email already wrote
    as a provisional line is folded onto it rather than written twice, and an
    alert the statement never confirmed is cancelled. Returns counts."""
    from datetime import timedelta
    import bank_feed
    import bank_review
    import receipts_service
    from models import db, BankTransaction, VendorRule
    rules = VendorRule.query.all()
    counts = {"read": 0, "new": 0, "folded_alerts": 0, "cancelled_alerts": 0}
    for row in rows:
        counts["read"] += 1
        line = BankTransaction.query.filter_by(connection_id=conn.id, external_id=row["ref"]).first()
        if line is not None:
            continue  # already read from an earlier upload; leave it as it was settled
        line = _fold_alert(conn, row)
        if line is not None:
            counts["folded_alerts"] += 1
            line.external_id = row["ref"]
        else:
            line = BankTransaction(connection_id=conn.id, business_id=conn.business_id,
                                   external_id=row["ref"], amount=0, occurred_on=row["date"])
            db.session.add(line)
            counts["new"] += 1
        line.account_name = conn.label or ""
        line.status = "sent"
        line.kind = "statement"
        line.amount = row["amount"]
        line.occurred_on = row["date"]
        line.posted_at = datetime(row["date"].year, row["date"].month, row["date"].day)
        line.counterparty = row["description"][:200]
        line.description = (row.get("kind") or "")[:300]
        if row.get("category"):
            line.merchant_category = row["category"][:80]
        bank_feed.classify(line, rules)
    db.session.flush()
    # An alert inside the stretch this statement covers that it did not
    # confirm was declined, reversed or changed amount (a tip): the statement
    # is the truth, so the provisional line goes, and its expense with it.
    # The last few days are left, because they may post on the next one.
    if rows:
        lo, hi = min(r["date"] for r in rows), max(r["date"] for r in rows) - timedelta(days=FOLD_AFTER)
        for line in BankTransaction.query.filter(BankTransaction.connection_id == conn.id,
                                                 BankTransaction.kind == "alert",
                                                 BankTransaction.status == "sent",
                                                 BankTransaction.occurred_on >= lo,
                                                 BankTransaction.occurred_on <= hi).all():
            line.status = "cancelled"
            bank_feed.classify(line, rules)
            counts["cancelled_alerts"] += 1
    remember_balances(conn, rows)
    db.session.flush()
    bank_review.suggest_free(BankTransaction.query.filter_by(connection_id=conn.id, disposition="review").all())
    counts["review"] = BankTransaction.query.filter_by(connection_id=conn.id, disposition="review").count()
    counts["folded"] = bank_feed.fold_duplicates()
    counts["attached"] = receipts_service.rematch()
    conn.last_ok = True
    conn.last_synced_at = datetime.utcnow()
    conn.last_note = (f"{counts['new']:,} new lines from the last upload, "
                      f"{counts['review']:,} to review")
    db.session.commit()
    return counts


# ── Is a statement due ───────────────────────────────────


def statement_through(conn):
    """The last day this source's uploads are known to cover: its newest
    statement line, or the day of its last upload, whichever is later (a card
    nobody used for a fortnight still had its statement read). Alert lines do
    not count: they keep the books current, and the upload is the check."""
    from models import db, BankTransaction
    newest = (db.session.query(db.func.max(BankTransaction.occurred_on))
              .filter(BankTransaction.connection_id == conn.id, BankTransaction.kind == "statement").scalar())
    uploaded = conn.last_synced_at.date() if conn.last_synced_at else None
    if uploaded is not None and newest is None:
        uploaded = None  # nothing ever uploaded: a save of the form is not a statement
    days = [d for d in (newest, uploaded) if d is not None]
    return max(days) if days else None


def statements_due(today=None):
    """[{connection, through}] for every statement source with nothing past
    the end of last month: last month's statement is waiting to be uploaded."""
    from datetime import date, timedelta
    from models import BankConnection
    today = today or date.today()
    month_end = today.replace(day=1) - timedelta(days=1)
    out = []
    for conn in BankConnection.query.filter_by(provider="statement").order_by(BankConnection.id).all():
        through = statement_through(conn)
        if through is None or through <= month_end:
            out.append({"connection": conn, "through": through, "month": month_end.replace(day=1)})
    return out


# ── Chase's per-transaction alert emails ─────────────────
#
# Chase sends an email for every card transaction once its "a card transaction
# is higher than the limit you set" alert is set to $0.00 with email delivery
# (the Chase playbook on the board says where). Each one becomes a provisional
# line on the source whose last four digits it names, so the books are current
# the day the card is used, and the downloaded statement folds over it.

_ALERT_SKIP = re.compile(r"\b(statement|balance|available|minimum|payment (?:is )?due|scheduled|autopay|"
                         r"password|sign[- ]?in|log ?in|profile|security|verify|travel notice|"
                         r"credit (?:limit|score|journey)|reward|offer|paperless)\b", re.I)
_ALERT_IN = re.compile(r"\b(refund|deposit|you received|money received|credited to|returned)\b", re.I)
_DOLLARS = re.compile(r"(?:\$|\(\$?USD\))\s?([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2}|[0-9]+\.[0-9]{2})")
_LAST_FOUR = re.compile(r"(?:\(\s*\.\.\.\s*(\d{4})\s*\)|ending in\s*(\d{4})|\.\.\.\s?(\d{4})|x{2,}(\d{4}))", re.I)
_ALERT_DATE = re.compile(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4})")
_MERCHANT = [
    re.compile(r"Merchant\s*:?\s*\n?\s*([^\n]{2,80})", re.I),
    re.compile(r"\b(?:transaction|charge|purchase) (?:of|for) \$[0-9,]+\.[0-9]{2} (?:with|at|to) ([^\n]{2,80}?)"
               r"(?: has| was| on |\.|$)", re.I | re.M),
    re.compile(r"\bat ([^\n]{2,80}?) has been authorized", re.I),
    re.compile(r"\b(?:with|at|to) ([A-Z0-9][^\n]{1,80}?)\s*$", re.M),
]


def parse_alert(raw):
    """One raw message -> {key, last_four, date, amount, merchant, subject},
    or None when it is not a Chase alert about one transaction."""
    import email as _email
    from email.utils import parseaddr, parsedate_to_datetime
    import receipts_service
    msg = _email.message_from_bytes(raw)
    sender = parseaddr(receipts_service._decode(msg.get("From")))[1].lower()
    if not (sender.endswith("chase.com") or sender.endswith(".chase.com")):
        return None
    subject = " ".join(receipts_service._decode(msg.get("Subject")).split())
    plain, html = receipts_service._text_of(msg)
    text = "\n".join(t for t in (plain, receipts_service._strip(html)) if t)
    text = "\n".join(" ".join(l.split()) for l in text.splitlines() if l.strip())
    if _ALERT_SKIP.search(subject):
        return None
    money = _DOLLARS.search(subject) or _DOLLARS.search(text)
    if not money:
        return None
    amount = float(money.group(1).replace(",", ""))
    merchant = ""
    for pattern in _MERCHANT:
        hit = pattern.search(subject) or pattern.search(text)
        if hit:
            merchant = hit.group(1).strip(" .:-")
            break
    if not merchant or amount <= 0:
        return None
    four = _LAST_FOUR.search(text) or _LAST_FOUR.search(subject)
    last_four = next((g for g in four.groups() if g), "") if four else ""
    when = None
    for hit in _ALERT_DATE.finditer(text):
        try:
            when = datetime.strptime(hit.group(1).replace("Sept ", "Sep "), "%b %d, %Y").date()
            break
        except ValueError:
            try:
                when = datetime.strptime(hit.group(1), "%B %d, %Y").date()
                break
            except ValueError:
                continue
    if when is None:
        try:
            when = parsedate_to_datetime(msg.get("Date")).date()
        except Exception:  # noqa: BLE001
            return None
    sign = 1 if _ALERT_IN.search(subject) else -1
    key = (msg.get("Message-ID") or "").strip()[:200] or "fp:" + hashlib.sha1(
        f"{sender}|{msg.get('Date')}|{subject}".encode()).hexdigest()
    return {"key": key, "last_four": last_four, "date": when, "amount": round(sign * amount, 2),
            "merchant": merchant[:200], "subject": subject[:300]}


def fetch_alerts(mailbox, since):
    """Raw messages from Chase since `since`, read only."""
    import receipts_service
    conn = receipts_service._connect(mailbox)
    try:
        if "gmail" in mailbox.imap_host:
            query = f"from:chase.com after:{since:%Y/%m/%d} -in:spam -in:trash"
            status, data = conn.search(None, "X-GM-RAW", f'"{query}"')
        else:
            status, data = conn.search(None, "FROM", '"chase.com"', "SINCE", since.strftime("%d-%b-%Y"))
        for mid in ((data[0] or b"").split() if status == "OK" else [])[-1500:]:
            status, parts = conn.fetch(mid, "(BODY.PEEK[])")
            if status == "OK" and parts and isinstance(parts[0], tuple):
                yield parts[0][1]
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


ALERT_LOOKBACK_DAYS = 45


def read_alerts(mailbox, fetcher=None):
    """Store the Chase alerts in one mailbox. Returns how many were new."""
    from datetime import date, timedelta
    from sqlalchemy.exc import IntegrityError
    from models import db, CardAlert
    newest = (db.session.query(db.func.max(CardAlert.occurred_on))
              .filter(CardAlert.mailbox_id == mailbox.id).scalar())
    since = (newest - timedelta(days=3)) if newest else date.today() - timedelta(days=ALERT_LOOKBACK_DAYS)
    new = 0
    for raw in (fetcher or fetch_alerts)(mailbox, since):
        got = parse_alert(raw)
        if got is None:
            continue
        if CardAlert.query.filter_by(mailbox_id=mailbox.id, message_key=got["key"]).first():
            continue
        try:
            with db.session.begin_nested():
                db.session.add(CardAlert(mailbox_id=mailbox.id, message_key=got["key"],
                                         last_four=got["last_four"], occurred_on=got["date"],
                                         amount=got["amount"], merchant=got["merchant"],
                                         subject=got["subject"]))
                db.session.flush()
        except IntegrityError:
            continue
        new += 1
    db.session.commit()
    return new


def _learn_last_four(alert, sources):
    """The source an alert's card is, when its digits are not on file yet:
    the one whose label carries them, or the one statement source already
    holding this exact charge."""
    from datetime import timedelta
    from models import BankTransaction
    if not alert.last_four:
        return None
    named = [c for c in sources if alert.last_four in (c.label or "")]
    if len(named) == 1:
        return named[0]
    hits = {l.connection_id for l in BankTransaction.query.filter(
        BankTransaction.connection_id.in_([c.id for c in sources]),
        BankTransaction.kind == "statement",
        BankTransaction.occurred_on >= alert.occurred_on - timedelta(days=FOLD_BEFORE),
        BankTransaction.occurred_on <= alert.occurred_on + timedelta(days=FOLD_AFTER)).all()
        if abs(l.amount - alert.amount) < 0.005}
    if len(hits) == 1:
        return next(c for c in sources if c.id in hits)
    return None


def apply_alerts():
    """Turn every stored alert whose card is known into a provisional line.
    Returns how many lines it wrote."""
    from datetime import timedelta
    import bank_feed
    from models import db, BankConnection, BankTransaction, CardAlert, VendorRule
    sources = BankConnection.query.filter_by(provider="statement").all()
    if not sources:
        return 0
    rules = VendorRule.query.all()
    written = 0
    for alert in CardAlert.query.filter(CardAlert.line_id.is_(None)).order_by(CardAlert.occurred_on).all():
        conn = next((c for c in sources if c.last_four and c.last_four == alert.last_four), None)
        if conn is None:
            conn = _learn_last_four(alert, [c for c in sources if not c.last_four])
            if conn is None:
                continue
            conn.last_four = alert.last_four
        # The statement already has it: point at that line, write nothing.
        taken = db.session.query(CardAlert.line_id).filter(CardAlert.line_id.isnot(None))
        have = [l for l in BankTransaction.query.filter(
            BankTransaction.connection_id == conn.id, BankTransaction.kind == "statement",
            BankTransaction.occurred_on >= alert.occurred_on - timedelta(days=FOLD_BEFORE),
            BankTransaction.occurred_on <= alert.occurred_on + timedelta(days=FOLD_AFTER),
            ~BankTransaction.id.in_(taken)).all() if abs(l.amount - alert.amount) < 0.005]
        if have:
            alert.line_id = min(have, key=lambda l: (abs((l.occurred_on - alert.occurred_on).days), l.id)).id
            continue
        # Inside what an upload already covers and not on it: declined or
        # changed. The statement is the truth there.
        through = statement_through(conn)
        if through is not None and alert.occurred_on + timedelta(days=FOLD_AFTER) <= through:
            alert.line_id = None
            continue
        line = BankTransaction(connection_id=conn.id, business_id=conn.business_id,
                               external_id="alert:" + hashlib.sha1(alert.message_key.encode()).hexdigest()[:24],
                               amount=alert.amount, occurred_on=alert.occurred_on, status="sent",
                               kind="alert", account_name=conn.label or "", counterparty=alert.merchant,
                               description="Card alert",
                               posted_at=datetime(alert.occurred_on.year, alert.occurred_on.month,
                                                  alert.occurred_on.day))
        db.session.add(line)
        db.session.flush()
        bank_feed.classify(line, rules)
        alert.line_id = line.id
        written += 1
    db.session.commit()
    return written


def sync_alerts(fetcher=None):
    """Every receipt mailbox's Chase alerts, read and applied. Returns a short
    summary for the night's record."""
    import bank_review
    from models import db, BankTransaction, ReceiptMailbox
    new, failed = 0, []
    for box in ReceiptMailbox.query.order_by(ReceiptMailbox.id).all():
        try:
            new += read_alerts(box, fetcher)
        except Exception as err:  # noqa: BLE001 - one mailbox never stops the rest
            db.session.rollback()
            failed.append(f"{box.address}: {str(err)[:100]}")
    written = apply_alerts()
    if written:
        bank_review.suggest_free(BankTransaction.query.filter_by(kind="alert", disposition="review").all())
        import bank_feed
        bank_feed.fold_duplicates()
    note = f"{new:,} new alerts, {written:,} provisional lines"
    if failed:
        raise RuntimeError(note + "; " + "; ".join(failed))
    return note

