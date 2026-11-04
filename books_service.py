"""The books: what each company earned, spent and was given, by month and year.

Pure readings over the rows the board already keeps, so the year-end
report, the monthly close and EntertainHQ's read-only view in its own admin
(the hub, /api/hub/books) can never disagree: they are the same function.

  income        cash basis. For the business this board bills from it is
                the board's paid invoices less their sales tax (the same
                reading as the dashboard's Total Revenue, and sales tax is a
                debt to Texas, never income). For a company with its own
                Stripe connected it is what customers paid there, gross, on
                the day they paid, less refunds, whether or not Stripe has
                paid it out yet (Michael, 2026-11-03: "what if there's a
                bunch of money sitting in Stripe that we haven't transferred
                over"). Otherwise the sales its app reports, and failing that
                what its bank received.
  expenses      every Expense in the company's books (its DBAs' included),
                billable-time rows excluded because they are revenue in the
                pipeline, not money spent. Grouped into the lines a tax
                return asks for (TAX_LINES).
  owner money   what each owner put in and took out, off the bank lines
                settled as contribution and draw. A multi-member company's
                accountant needs it per member for each K-1.
"""
import re
from collections import OrderedDict
from datetime import date, timedelta

# Category -> (the line on the return, Schedule C line number). The number is
# shown only for a single-member company, which files Schedule C; a
# partnership's 1065 groups the same way under other numbers.
TAX_LINES = OrderedDict([
    ("advertising", ("Advertising", "8")),
    ("subcontractor", ("Contract labor", "11")),
    ("design", ("Contract labor", "11")),
    ("hardware", ("Equipment (ask about depreciation)", "13")),
    ("legal_professional", ("Legal and professional services", "17")),
    ("office", ("Office expense and supplies", "18")),
    ("taxes_licenses", ("Taxes and licenses", "23")),
    ("travel", ("Travel", "24a")),
    ("meals", ("Meals (generally 50% deductible)", "24b")),
    ("phone_internet", ("Utilities: phone and internet", "25")),
    ("software", ("Software and subscriptions", "27a")),
    ("ai_services", ("Software and subscriptions", "27a")),
    ("hosting", ("Hosting and infrastructure", "27a")),
    ("service_cost", ("Hosting and infrastructure", "27a")),
    ("domain", ("Domains", "27a")),
    ("bank_fees", ("Bank and payment processing fees", "27a")),
    ("education", ("Education and training", "27a")),
    ("misc", ("Other expenses", "27a")),
])
OTHER_LINE = ("Other expenses", "27a")


def tax_line(category):
    return TAX_LINES.get(category or "misc", OTHER_LINE)


def month_bounds(month):
    start = date(month.year, month.month, 1)
    end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return start, end


def family_ids(business):
    """The company and every DBA under it: one set of books."""
    from models import Business
    root = business.parent or business
    return [root.id] + [b.id for b in Business.query.filter_by(parent_id=root.id).all()]


def expenses_between(business, start, end):
    from models import Expense
    return (Expense.query.filter(Expense.business_id.in_(family_ids(business)),
                                 Expense.time_entry_id.is_(None),
                                 Expense.date >= start, Expense.date < end)
            .order_by(Expense.date, Expense.id).all())


def board_business():
    """The company this board bills from (Built by Bean LLC): its Stripe is
    the app's own, and the finance dashboard and the Taxes page are its."""
    from models import Business
    return (Business.query.filter(Business.sales_source == "board", Business.parent_id.is_(None))
            .order_by(Business.id).first())


def board_expense_total(start=None, end=None):
    """The board company's expenses (its DBAs' included), all time unless a
    period is given. The dashboard and the Taxes page read this, so neither
    can count another company's spending as Built by Bean's."""
    from models import Expense, db
    business = board_business()
    q = db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0.0)).filter(
        Expense.time_entry_id.is_(None))
    if business is not None:
        q = q.filter(Expense.business_id.in_(family_ids(business)))
    if start is not None:
        q = q.filter(Expense.date >= start)
    if end is not None:
        q = q.filter(Expense.date < end)
    return round(q.scalar() or 0.0, 2)


def _stripe_paid_invoices():
    """The board's Stripe invoices, live, or None when Stripe is not set up
    (the tests, a dev machine). Live is the dashboard's source, and the books
    read the same one: on 2026-11-03 the books read the local invoice rows and
    came out $5.97 under the dashboard for the same year. That $5.97 was three
    refunded charges the dashboard was counting, so both now read refunds."""
    try:
        import stripe
        if not stripe.api_key:
            return None
        from stripe_service import get_stripe_invoices
        rows = get_stripe_invoices()
    except Exception:  # noqa: BLE001 - fall back to the local rows
        return None
    return rows or None


def income_between(business, start, end, sales=None):
    """[(date, amount, description)] of money earned, cash basis."""
    from models import BankTransaction, Invoice
    root = business.parent or business
    out = []
    if root.sales_source == "board":
        from stripe_service import earned_share
        live = _stripe_paid_invoices()
        if live is not None:
            for inv in live:
                if inv.get("status") != "paid" or inv.get("catchup"):
                    continue
                when = inv.get("paid_at") or inv.get("issued_at")
                when = when.date() if when else None
                label = f"Invoice {inv.get('number') or inv.get('id')}"
                if inv.get("customer_name"):
                    label += f", {inv['customer_name']}"
                if when is not None and start <= when < end:
                    out.append((when, round((inv.get("amount_paid") or 0.0) - (inv.get("tax") or 0.0), 2),
                                label))
                # Cash basis both ways: the sale on the day it was paid, the
                # refund on the day it went back, which may be another month.
                for refund in inv.get("refunds") or []:
                    if start <= refund["on"] < end:
                        out.append((refund["on"], -round(refund["amount"] * earned_share(inv), 2),
                                    f"Refund, {label}"))
            return sorted(out)
        for inv in Invoice.query.filter(Invoice.status == "paid").all():
            when = (inv.paid_at.date() if inv.paid_at else inv.issued_on)
            if when is None or not (start <= when < end) or inv.sales_tax_catchup:
                continue
            label = f"Invoice {inv.invoice_number or inv.id}"
            if inv.client:
                label += f", {inv.client.name}"
            out.append((when, inv.earned, label))
        return sorted(out)
    if root.stripe_key:
        import stripe_books
        return stripe_books.income_between(root, start, end)
    if sales is not None:
        return sorted((s["date"], round(s["total"], 2), s.get("ref") or "Sale")
                      for s in sales if start <= s["date"] < end)
    for line in (BankTransaction.query.filter(BankTransaction.business_id.in_(family_ids(business)),
                                              BankTransaction.disposition == "income",
                                              BankTransaction.occurred_on >= start,
                                              BankTransaction.occurred_on < end).all()):
        out.append((line.occurred_on, round(line.amount, 2), line.counterparty or "Deposit"))
    return sorted(out)


def owner_money_between(business, start, end):
    """{owner name: {"in": x, "out": y}} off settled bank lines, plus every
    expense an owner paid personally, which is that owner putting money in."""
    from models import BankTransaction, Expense
    out = {}
    for e in (Expense.query.filter(Expense.business_id.in_(family_ids(business)),
                                   Expense.paid_by.isnot(None), Expense.paid_by != "",
                                   Expense.date >= start, Expense.date < end).all()):
        # The whole charge: the sales tax on a Comptroller payment is not this
        # company's cost, but it was still the owner's money that paid it.
        out.setdefault(e.paid_by, {"in": 0.0, "out": 0.0})["in"] += e.charged
    # A vendor sync books some charges itself (Railway, Cloudflare, Claude);
    # when one of those was paid on an owner's own card, the owner still put
    # that money in.
    from models import BankConnection
    for line in (BankTransaction.query.join(BankConnection, BankTransaction.connection_id == BankConnection.id)
                 .filter(BankTransaction.business_id.in_(family_ids(business)),
                         BankTransaction.disposition == "covered", BankConnection.kind == "personal",
                         BankTransaction.occurred_on >= start, BankTransaction.occurred_on < end).all()):
        who = line.connection.owner_name or "Owner not named"
        out.setdefault(who, {"in": 0.0, "out": 0.0})["in"] += abs(line.amount)
    for line in (BankTransaction.query.filter(BankTransaction.business_id.in_(family_ids(business)),
                                              BankTransaction.disposition.in_(("contribution", "draw")),
                                              BankTransaction.status == "sent",
                                              BankTransaction.occurred_on >= start,
                                              BankTransaction.occurred_on < end).all()):
        who = line.owner_name or "Owner not named"
        row = out.setdefault(who, {"in": 0.0, "out": 0.0})
        if line.disposition == "contribution":
            row["in"] += abs(line.amount)
        else:
            row["out"] += abs(line.amount)
    return {k: {"in": round(v["in"], 2), "out": round(v["out"], 2)} for k, v in out.items()}


# What a payment to the state reads as on a card, a bank line or a typed expense.
STATE_TAX_PAYMENT = re.compile(r"comptroller|texas tax|state tax|webfile", re.I)
# WebFile adds a card fee the return does not show, and it is not always typed
# in: $739.54 paid on a return was a $756.43 card charge on 2026-10-30.
CARD_FEE_ROOM = 1.03
FILED_BEFORE, FILED_AFTER = 3, 10


def leaves_sales_tax_out_of_income(business):
    """Whether this company's income is already net of sales tax. Only the
    company the board bills from: its invoices are read less their tax.
    A company on its own Stripe or its own app counts its sales gross, tax and
    all, and there the payment to the state IS what takes the tax back out, so
    its Comptroller charges stay whole expenses. Each is right on its own; one
    company doing half of each is what took the tax off twice."""
    return (business.parent or business).sales_source == "board"


def filing_payment(filing):
    """The expense that paid this return, if it has arrived. Named as the
    state AND within a card fee of what the return says was paid, so a
    franchise tax payment or another Comptroller charge is never taken for it."""
    from models import Expense
    paid = round(filing.amount_paid or 0.0, 2)
    if paid <= 0:
        return None
    day = filing.filed_at.date()
    rows = Expense.query.filter(Expense.business_id.in_(family_ids(filing.business)),
                                Expense.sales_tax_filing_id.is_(None),
                                Expense.time_entry_id.is_(None),
                                Expense.date >= day - timedelta(days=FILED_BEFORE),
                                Expense.date <= day + timedelta(days=FILED_AFTER)).all()
    rows = [e for e in rows if STATE_TAX_PAYMENT.search(e.description or "")
            and paid <= e.charged <= paid * CARD_FEE_ROOM + 0.01]
    return min(rows, key=lambda e: (e.charged - paid, e.id)) if rows else None


def settle_sales_tax(filing=None):
    """Take the sales tax out of what a return's payment cost.

    Sales tax collected is left out of income, so paying it over must not also
    be an expense, or it comes off the profit twice: on 2026-11-03 that was
    $996.60 of the $1,193.22 paid to the Comptroller. The penalties, interest
    and card fee stay, because those were real money this company lost.

    Works in either order, because a return can be recorded before its charge
    arrives or after, and is safe to run on every read. Returns how many
    expenses changed; the caller commits.
    """
    from models import db, Expense, SalesTaxFiling
    filings = ([filing] if filing is not None
               else SalesTaxFiling.query.filter(SalesTaxFiling.filed_at.isnot(None)).all())
    done = 0
    for f in filings:
        if f.filed_at is None or f.business is None or not leaves_sales_tax_out_of_income(f.business):
            continue
        expense = Expense.query.filter_by(sales_tax_filing_id=f.id).first() or filing_payment(f)
        if expense is None:
            continue
        charged = expense.charged
        # A timely filing discount is tax the state let the seller keep.
        tax = min(round(max(0.0, (f.tax_due or 0.0) - (f.discount or 0.0)), 2), charged)
        if expense.sales_tax_filing_id == f.id and abs((expense.sales_tax_remitted or 0.0) - tax) < 0.005:
            continue
        expense.sales_tax_filing_id = f.id
        expense.sales_tax_remitted = tax
        expense.amount = round(charged - tax, 2)
        done += 1
    db.session.flush()
    return done


def unsettle_sales_tax(filing):
    """A return taken off the board puts its charge back to a whole expense,
    because nothing now says any of it was tax. The caller commits."""
    from models import Expense
    for expense in Expense.query.filter_by(sales_tax_filing_id=filing.id).all():
        expense.amount = expense.charged
        expense.sales_tax_remitted = 0.0
        expense.sales_tax_filing_id = None


def source_of(expense):
    """Where an expense came from, for the accountant's export."""
    if expense.paid_by:
        return f"paid personally by {expense.paid_by}"
    if expense.bank_lines.first() is not None:
        return "bank"
    from models import ServiceCostEntry
    if ServiceCostEntry.query.filter_by(expense_id=expense.id).first() is not None:
        return "vendor sync"
    return "entered"


def summarize(business, start, end, sales=None):
    """Everything the report, the close and the hub read, for one period."""
    from models import BankTransaction
    expenses = expenses_between(business, start, end)
    income = income_between(business, start, end, sales)
    lines = OrderedDict()
    for e in expenses:
        label, number = tax_line(e.category)
        row = lines.setdefault(label, {"label": label, "number": number, "total": 0.0, "count": 0})
        row["total"] += e.amount
        row["count"] += 1
    by_month = OrderedDict()
    for e in expenses:
        key = e.date.strftime("%Y-%m")
        by_month.setdefault(key, {"expenses": 0.0, "income": 0.0})["expenses"] += e.amount
    for when, amount, _ in income:
        key = when.strftime("%Y-%m")
        by_month.setdefault(key, {"expenses": 0.0, "income": 0.0})["income"] += amount
    expense_total = round(sum(e.amount for e in expenses), 2)
    income_total = round(sum(a for _, a, _ in income), 2)
    family = family_ids(business)
    unsorted = (BankTransaction.query.filter(BankTransaction.business_id.in_(family),
                                             BankTransaction.disposition == "review",
                                             BankTransaction.occurred_on >= start,
                                             BankTransaction.occurred_on < end).count())
    return {
        "start": start, "end": end,
        "expenses": expenses, "income": income,
        "expense_total": expense_total, "income_total": income_total,
        "net": round(income_total - expense_total, 2),
        "tax_lines": sorted(({**v, "total": round(v["total"], 2)} for v in lines.values()),
                            key=lambda r: (r["number"], r["label"])),
        "by_month": OrderedDict(sorted((k, {"expenses": round(v["expenses"], 2),
                                            "income": round(v["income"], 2)})
                                       for k, v in by_month.items())),
        "owner_money": owner_money_between(business, start, end),
        "no_receipt": [e for e in expenses if not e.receipt_filename and e.amount > 0],
        "unsorted": unsorted,
    }


def bank_check(business, through):
    """Each connected account's balance as the bank reports it, beside the
    sum of every settled line the board has read for it. Equal means the
    board has every movement; a difference is a line missing or history read
    from after the account opened."""
    from models import BankConnection, BankTransaction, db
    out = []
    for conn in BankConnection.query.filter(BankConnection.business_id.in_(family_ids(business))).all():
        balances = conn.balances
        for account_id, name in conn.accounts.items():
            total = (db.session.query(db.func.coalesce(db.func.sum(BankTransaction.amount), 0.0))
                     .filter(BankTransaction.connection_id == conn.id,
                             BankTransaction.account_id == account_id,
                             BankTransaction.status == "sent").scalar())
            bank = balances.get(account_id)
            out.append({"name": name, "bank": bank, "board": round(total or 0.0, 2),
                        "agrees": bank is not None and abs(bank - (total or 0.0)) < 0.005,
                        "read_from": conn.synced_from})
    return out
