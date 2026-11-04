"""The books keep themselves, nightly (docs/automation_gaps.md, items 13 to 15
and the receipt with no bank line).

Each function is one step of the night (sync_costs._sweep runs them through
night.step), returns a short summary, and writes what it found wrong as
BooksFlag rows. Needs attention draws one row per flag, so the sidebar badge,
which is built on every page, reads a table instead of working out a month of
books (a month's income reads Stripe live).

  close_months         a finished month closes itself once nothing is
                       unsorted, every receipt is in and every account agrees;
                       otherwise one row per company saying why
  end_recurring        a recurring expense whose vendor the bank now books by
                       rule stops making children, and a child no bank line
                       has claimed within ten days is listed
  receipts_without_line
                       a known vendor's receipt with no bank line within five
                       days on any connection: a card the board cannot see
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

BOOKS_START = date(2026, 4, 1)
UNCLAIMED_DAYS = 10
NO_LINE_DAYS = 5
# How far back a receipt with no bank line is still asked about: the window
# after which receipts_service sets unmatched mail aside anyway, so the row
# clears itself rather than carrying a card nobody can connect for ever.
NO_LINE_WINDOW_DAYS = 45
NIGHT_NOTE = "Closed by the nightly run"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _set_flags(kind, rows):
    """Replace every flag of one kind with `rows` (dicts of BooksFlag fields)."""
    from models import db, BooksFlag
    # Through the session, not a bulk delete: a bulk delete leaves the old
    # rows in the identity map while a new one takes the same id.
    for old in BooksFlag.query.filter_by(kind=kind).all():
        db.session.delete(old)
    db.session.flush()
    for row in rows:
        items = row.pop("items", [])
        db.session.add(BooksFlag(kind=kind, items_json=json.dumps(items, default=str),
                                 checked_at=_now(), **row))
    db.session.commit()


def _plural(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# ── The month closes itself ──────────────────────────────


def _finished_months(today):
    out, m = [], BOOKS_START
    this = today.replace(day=1)
    while m < this:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def month_reasons(business, month, bank=None):
    """Why this month cannot close yet, as short phrases ([] when it can).
    Unsorted lines, every expense without its receipt (Michael, 2026-11-04:
    every one, not only those over $75), and each account that does not agree
    or has no statement past the month's end."""
    import books_service
    from models import BankTransaction, Expense
    start, end = books_service.month_bounds(month)
    family = books_service.family_ids(business)
    unsorted = BankTransaction.query.filter(BankTransaction.business_id.in_(family),
                                            BankTransaction.disposition == "review",
                                            BankTransaction.occurred_on >= start,
                                            BankTransaction.occurred_on < end).count()
    missing = Expense.query.filter(Expense.business_id.in_(family), Expense.time_entry_id.is_(None),
                                   Expense.receipt_filename.is_(None), Expense.amount > 0,
                                   Expense.date >= start, Expense.date < end).count()
    reasons = []
    if unsorted:
        reasons.append(f"{unsorted:,} unsorted")
    if missing:
        reasons.append(_plural(missing, "receipt"))
    rows = bank if bank is not None else books_service.bank_check(business, end - timedelta(days=1))
    for a in rows:
        if not a.get("agrees"):
            reasons.append(a.get("message") or f"{a['name']} does not agree with the bank")
    return reasons


def close_months(today=None):
    """Close every finished month that is clean; flag each company whose
    newest finished month is not. Returns a summary."""
    import books_service
    from models import db, Business, MonthClose
    today = today or date.today()
    closed, flags = [], []
    for business in Business.query.filter_by(parent_id=None, is_active=True).order_by(Business.id).all():
        done = {m.month for m in MonthClose.query.filter_by(business_id=business.id).all()}
        blocked = []
        for month in _finished_months(today):
            if month in done:
                continue
            start, end = books_service.month_bounds(month)
            reasons = month_reasons(business, month)
            if reasons:
                blocked.append({"month": month.strftime("%Y-%m"), "reasons": ", ".join(reasons)})
                continue
            s = books_service.summarize(business, start, end)
            db.session.add(MonthClose(business_id=business.id, month=start, expenses_total=s["expense_total"],
                                      income_total=s["income_total"], closed_at=_now(), note=NIGHT_NOTE))
            db.session.commit()
            closed.append(f"{business.short_name or business.name} {month:%b %Y}")
        if blocked:
            flags.append(_month_flag(business, blocked))
    _set_flags("month", flags)
    note = f"closed {', '.join(closed)}" if closed else "nothing new to close"
    return note + (f"; {len(flags)} compan{'y' if len(flags) == 1 else 'ies'} with a month that will not close"
                   if flags else "")


def _month_flag(business, blocked):
    newest = blocked[-1]
    month = datetime.strptime(newest["month"], "%Y-%m")
    earlier = len(blocked) - 1
    link = f"/admin/books/{business.id}/month/{newest['month']}"
    return {"key": str(business.id), "business_id": business.id,
            "title": f"{month:%B} will not close: {newest['reasons']}"[:200],
            "detail": (f"{business.short_name or business.name}"
                       + (f", and {_plural(earlier, 'earlier month')} still open" if earlier else ""))[:300],
            "link": link, "count": len(blocked), "items": blocked}


def month_closed_by_hand(business_id, month):
    """A month closed on its page leaves the night's flag at once rather than
    tomorrow morning."""
    from models import db, BooksFlag
    flag = BooksFlag.query.filter_by(kind="month", key=str(business_id)).first()
    if flag is None:
        return
    items = [i for i in flag.items if i.get("month") != month.strftime("%Y-%m")]
    if not items:
        db.session.delete(flag)
    else:
        from models import Business
        refreshed = _month_flag(db.session.get(Business, business_id), items)
        flag.title, flag.detail, flag.link = refreshed["title"], refreshed["detail"], refreshed["link"]
        flag.count, flag.items_json = refreshed["count"], json.dumps(items)
    db.session.commit()


# ── Recurring expenses the bank now books ────────────────


def _rule_matching(text, rules):
    import bank_feed
    hay = f" {bank_feed.norm(text)} "
    best = None
    for r in rules:
        pat = bank_feed.norm(r.pattern)
        if pat and (f" {pat} " in hay or (len(pat) >= 6 and pat in hay)):
            if best is None or len(bank_feed.norm(best.pattern)) < len(pat):
                best = r
    return best


def end_recurring(today=None):
    """A recurring expense whose vendor has a rule is ended: the bank books
    every charge from that vendor now, and its children at the old fixed
    amount were the duplicates adopt() missed whenever the price moved. Then
    every child dated ten days ago or more that no bank line has claimed is
    listed, because it is either a double count or a card the board cannot
    see. Returns a summary."""
    from models import db, Expense, ServiceCostEntry, VendorRule
    today = today or date.today()
    rules = [r for r in VendorRule.query.all()
             if r.disposition in ("expense", "covered") and (r.applies_to or "all") == "all"]
    ended = []
    for parent in Expense.query.filter(Expense.is_recurring.is_(True)).all():
        rule = _rule_matching(parent.description, rules)
        if rule is None:
            continue
        parent.is_recurring = False
        parent.recurring_end_date = today
        parent.next_due_date = None
        ended.append(parent.description or rule.vendor or rule.pattern)
    db.session.commit()
    synced = db.session.query(ServiceCostEntry.expense_id).filter(ServiceCostEntry.expense_id.isnot(None))
    children = (Expense.query.filter(Expense.parent_expense_id.isnot(None), Expense.time_entry_id.is_(None),
                                     Expense.date >= BOOKS_START,
                                     Expense.date <= today - timedelta(days=UNCLAIMED_DAYS),
                                     ~Expense.id.in_(synced))
                .order_by(Expense.date, Expense.id).all())
    unclaimed = [e for e in children if e.bank_lines.first() is None]
    flags = []
    if unclaimed:
        link = "/admin/books/checks?kind=recurring"
        flags.append({"key": "all", "title": f"{_plural(len(unclaimed), 'recurring expense')} no bank line has claimed",
                      "detail": "Each is a charge counted twice, or paid on a card the board cannot see",
                      "link": link, "count": len(unclaimed),
                      "items": [{"id": e.id, "date": e.date.isoformat(), "description": e.description or "",
                                 "amount": round(e.amount, 2), "business_id": e.business_id} for e in unclaimed]})
    _set_flags("recurring", flags)
    return (f"{len(ended)} recurring ended ({', '.join(ended[:5])})" if ended else "no recurring to end") + \
        f"; {len(unclaimed)} children unclaimed"


# ── A receipt with no bank line ──────────────────────────


def known_vendor_names():
    """Lower-case names of vendors the board already pays: its rules, its
    providers and the vendors the free suggester knows."""
    import bank_review
    from models import ServiceProvider, VendorRule
    names = set(bank_review.KNOWN_VENDORS)
    for r in VendorRule.query.filter(VendorRule.disposition.in_(("expense", "covered"))).all():
        if (r.applies_to or "all") != "all":
            continue
        word = next((w for w in re.findall(r"[a-z][a-z0-9]+", (r.vendor or r.pattern or "").lower())
                     if len(w) >= 4), None)
        if word:
            names.add(word)
    for p in ServiceProvider.query.filter_by(is_active=True).all():
        word = next((w for w in re.findall(r"[a-z][a-z0-9]+", (p.display_name or "").lower()) if len(w) >= 4), None)
        if word:
            names.add(word)
    return names


def receipts_without_line(today=None):
    """Every receipt from a known vendor, old enough that every connection's
    lines reach five days past it, with no bank line for any of its amounts
    within five days on any connection. Returns a summary."""
    import receipts_service
    from models import db, BankTransaction, Receipt
    today = today or date.today()
    reach = [d for (d,) in db.session.query(db.func.max(BankTransaction.occurred_on))
             .group_by(BankTransaction.connection_id).all() if d]
    items = []
    if reach:
        horizon = min(reach) - timedelta(days=NO_LINE_DAYS)
        names = known_vendor_names()
        since = max(BOOKS_START, today - timedelta(days=NO_LINE_WINDOW_DAYS))
        rows = (Receipt.query.filter(Receipt.received_on >= since, Receipt.received_on <= horizon,
                                     Receipt.status != "ignored")
                .order_by(Receipt.received_on, Receipt.id).all())
        for r in rows:
            said = f"{r.vendor} {r.sender} {r.subject}".lower()
            if not any(name in said for name in names):
                continue
            try:
                amounts = receipts_service.candidate_amounts(r)
            except Exception:  # noqa: BLE001
                amounts = {round(r.amount, 2)} if r.amount else set()
            amounts = {a for a in amounts if a > 0}
            if not amounts:
                continue
            near = BankTransaction.query.filter(
                BankTransaction.status != "void",
                BankTransaction.occurred_on >= r.received_on - timedelta(days=NO_LINE_DAYS),
                BankTransaction.occurred_on <= r.received_on + timedelta(days=NO_LINE_DAYS)).all()
            if any(abs(-l.amount - a) < 0.005 for l in near for a in amounts):
                continue
            items.append({"id": r.id, "date": r.received_on.isoformat(), "vendor": r.vendor or "",
                          "subject": r.subject or "", "amount": r.amount or max(amounts)})
    flags = []
    if items:
        link = "/admin/books/checks?kind=receipts"
        flags.append({"key": "all", "title": f"{_plural(len(items), 'receipt')} with no bank line",
                      "detail": "A known vendor charged a card the board cannot see",
                      "link": link, "count": len(items), "items": items})
    _set_flags("receipts", flags)
    return f"{len(items)} receipts with no bank line"


def receipt_set_aside(receipt_id):
    """A receipt set aside by hand leaves the night's list at once."""
    from models import db, BooksFlag
    flag = BooksFlag.query.filter_by(kind="receipts", key="all").first()
    if flag is None:
        return
    items = [i for i in flag.items if i.get("id") != receipt_id]
    if not items:
        db.session.delete(flag)
    else:
        flag.items_json, flag.count = json.dumps(items), len(items)
        flag.title = f"{_plural(len(items), 'receipt')} with no bank line"
    db.session.commit()


# ── What Needs attention reads ───────────────────────────


def attention_rows():
    """The books' rows for Needs attention: every flag the night left, then
    one row naming the statements that are due. Cheap: a table read and one
    aggregate per statement source."""
    from flask import url_for
    from models import db, BooksFlag
    out = []
    try:
        for flag in BooksFlag.query.order_by(BooksFlag.kind, BooksFlag.key).all():
            out.append({"title": flag.title, "detail": flag.detail, "link": flag.link,
                        "label": {"month": "Books", "recurring": "Recurring",
                                  "receipts": "Receipts"}.get(flag.kind, "Books")})
        import statements
        due = statements.statements_due()
        if due:
            names = ", ".join(d["connection"].label or "Statement" for d in due)
            out.append({"title": f"{due[0]['month']:%B} statement{'' if len(due) == 1 else 's'} to upload",
                        "detail": names[:300], "link": url_for("books.index", tab="connections"),
                        "label": "Statement"})
    except Exception:  # noqa: BLE001 - a table that is not there yet never takes the board down
        db.session.rollback()
        return []
    return out
