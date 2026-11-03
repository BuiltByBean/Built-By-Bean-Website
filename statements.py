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
                    "kind": (r[kind_i].strip()[:40] if kind_i is not None else "")})
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


def import_rows(conn, rows):
    """Write parsed rows onto the connection as bank lines, classify each,
    and attach any waiting receipts. Returns counts."""
    import bank_feed
    import receipts_service
    from models import db, BankTransaction, VendorRule
    rules = VendorRule.query.all()
    counts = {"read": 0, "new": 0}
    for row in rows:
        counts["read"] += 1
        line = BankTransaction.query.filter_by(connection_id=conn.id, external_id=row["ref"]).first()
        if line is None:
            line = BankTransaction(connection_id=conn.id, business_id=conn.business_id,
                                   external_id=row["ref"], amount=0, occurred_on=row["date"])
            db.session.add(line)
            counts["new"] += 1
        else:
            continue  # already read from an earlier upload; leave it as it was settled
        line.account_name = conn.label or ""
        line.status = "sent"
        line.kind = "statement"
        line.amount = row["amount"]
        line.occurred_on = row["date"]
        line.posted_at = datetime(row["date"].year, row["date"].month, row["date"].day)
        line.counterparty = row["description"][:200]
        line.description = (row.get("kind") or "")[:300]
        bank_feed.classify(line, rules)
    db.session.flush()
    counts["review"] = BankTransaction.query.filter_by(connection_id=conn.id, disposition="review").count()
    counts["attached"] = receipts_service.rematch()
    conn.last_ok = True
    conn.last_synced_at = datetime.utcnow()
    conn.last_note = (f"{counts['new']:,} new lines from the last upload, "
                      f"{counts['review']:,} to review")
    db.session.commit()
    return counts
