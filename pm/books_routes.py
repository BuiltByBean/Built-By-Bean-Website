"""Books: each company's year, its months, its owners and its receipts.

Michael, 2026-11-03: "we're effectively building out our own bookkeeping
system". The board keeps the books for every company it knows about, and
this is where they are read. Since 2026-11-04 (docs/finances_plan.md item 2)
it is each company's one place for its money, a tab per company and under it:

  /admin/books/<id>/               Months: the year so far, its months (closed
                                   or not, and what is left to do), its owners
  /admin/books/<id>/bank           the bank lines to sort (the review list,
                                   moved in from /admin/bank/), and the charges
                                   a session tagged that no line has taken
  /admin/books/<id>/expenses       the ledger and its breakdown (moved in from
                                   /admin/expenses), with Add expense
  /admin/books/<id>/receipts       missing, statement only, unmatched
  /admin/books/<id>/connections    Mercury, its own Stripe, card statements,
                                   receipt mailboxes and vendor reports
  /admin/books/<id>/year/<y>       the year-end report the accountant works
                                   from, grouped the way the return groups it,
                                   with a CSV of every line
  /admin/books/<id>/month/<y-m>    the monthly close: every bank line sorted,
                                   every expense with its receipt, the bank's
                                   balance agreeing, then one press
  /admin/books/receipts            receipts that matched no charge yet
  /api/hub/books                   the same figures for a company's own app,
                                   signed with its hub secret: EntertainHQ's
                                   admin shows its partners these numbers read
                                   only, so there is one set of books, not two

Every figure on all of them comes from books_service, so no two can differ.
"""
import csv
import io
import json
import os
from datetime import date, datetime, timedelta, timezone

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)

import books_service
import receipts_service
from forms import EXPENSE_CATEGORY_CHOICES
from models import (db, Business, BusinessOwner, MonthClose, Receipt, ReceiptMailbox)
from pm.users_routes import ceo_required
from sqlalchemy import false as sa_false

books_bp = Blueprint("books", __name__)
BOOKS_START = date(2026, 4, 1)


def _companies():
    return Business.query.filter_by(parent_id=None, is_active=True).order_by(Business.id).all()


def _month(value):
    try:
        y, m = (int(x) for x in value.split("-"))
        return date(y, m, 1)
    except (ValueError, AttributeError):
        abort(404)


def _months(through):
    out, m = [], BOOKS_START
    while m <= through:
        out.append(m)
        m = books_service.month_bounds(m)[1]
    return out


def month_status(business, month):
    """What is left before a month can close."""
    start, end = books_service.month_bounds(month)
    summary = books_service.summarize(business, start, end)
    closed = MonthClose.query.filter_by(business_id=business.id, month=start).first()
    return {"month": start, "summary": summary, "closed": closed,
            "unsorted": summary["unsorted"], "no_receipt": len(summary["no_receipt"]),
            "finished": end <= date.today()}


@books_bp.route("/admin/books/")
@ceo_required
def index():
    """The front door: the company the board bills from, on Months. The old
    one-page Books took `?tab=<company id>` or `?tab=connections`, and Needs
    attention still links `?tab=connections` and `?tab=tags`, so each lands
    where it meant."""
    tab = request.args.get("tab") or ""
    year = request.args.get("year", type=int)
    business = _company(int(tab)) if tab.isdigit() else _home()
    if business is None:
        abort(404)
    if tab == "connections":
        return redirect(url_for("books.connections", id=business.id), 301)
    if tab == "tags":
        return redirect(url_for("books.bank", id=business.id, view="tags"), 301)
    return redirect(url_for("books.company", id=business.id, **({"year": year} if year else {})), 301)


def _home():
    from models import home_business_id
    home = home_business_id()
    return db.session.get(Business, home) if home else (_companies() or [None])[0]


def _company(id):
    """A company's books: a DBA's are its parent's (one set of books, one tax
    return), so a DBA's id opens the company it trades under."""
    business = db.session.get(Business, id)
    if business is None:
        abort(404)
    if business.parent_id:
        business = db.session.get(Business, business.parent_id) or abort(404)
    return business


def family_ids(business):
    return books_service.family_ids(business)


def review_count(business):
    """Bank lines this company's banks and cards read that wait to be sorted.
    One query, the Bank tab's own list and its count share it."""
    from models import BankTransaction
    return BankTransaction.query.filter(BankTransaction.business_id.in_(family_ids(business)),
                                        BankTransaction.disposition == "review").count()


def _missing_receipts(business):
    from models import Expense
    return (Expense.query.filter(Expense.business_id.in_(family_ids(business)),
                                 Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                                 Expense.amount > 0, Expense.date >= receipts_service.BOOKS_START)
            .order_by(Expense.date.desc(), Expense.id.desc()))


HUB_ENDPOINTS = {"months": "books.company", "bank": "books.bank", "expenses": "books.expenses",
                 "receipts": "books.company_receipts", "connections": "books.connections"}


def _hub(template, business, active, **ctx):
    """Render a Books page: the companies across the top (each opening the same
    tab for itself), the company's tabs, and the page under them."""
    year = ctx.get("year") or date.today().year

    def href(tab, bid):
        if tab == "year":
            return url_for("books.year_report", id=bid, year=year)
        if tab == "months":
            return url_for("books.company", id=bid, year=year)
        return url_for(HUB_ENDPOINTS[tab], id=bid)

    companies = _companies()
    company_tabs = [(str(b.id), b.short_name or b.name, href(active, b.id)) for b in companies]
    hub_tabs = [("months", "Months", href("months", business.id)),
                ("bank", "Bank", href("bank", business.id), review_count(business)),
                ("expenses", "Expenses", href("expenses", business.id)),
                ("receipts", "Receipts", href("receipts", business.id)),
                ("year", "Year report", href("year", business.id)),
                ("connections", "Connections", href("connections", business.id))]
    return render_template(template, business=business, hub_tab=active, hub_tabs=hub_tabs,
                           company_tabs=company_tabs, **ctx)


# ── What the Overview was: the year's tax and what is left to do ─────────
# Michael retired the Overview the evening it shipped (2026-11-04) and put
# Books in its place; these are drawn at the top of a company's Months tab.

def estimated_tax(business, year, summary=None):
    """The year's estimated income tax, as the Taxes page works it out.
    None when it cannot be worked out, which the tile says in words."""
    try:
        import income_tax
    except ImportError:
        return None
    try:
        return income_tax.estimate(business, year, summary=summary)
    except Exception:  # noqa: BLE001 - a tile never takes the page down
        current_app.logger.exception("income tax estimate failed")
        return None


def todo(business, is_home, today):
    """What is waiting on Michael about this company's money, one row per
    thing to press: [(kind, title, detail, href, count)]."""
    import books_service
    rows = []
    family = books_service.family_ids(business)
    if is_home:
        try:
            from stripe_service import get_overdue_invoices, get_stalled_subscriptions
            overdue = get_overdue_invoices()
            stalled = get_stalled_subscriptions()
        except Exception:  # noqa: BLE001 - Stripe down is not a page down
            overdue, stalled = [], []
        if overdue:
            total = sum(i["amount_due"] for i in overdue)
            rows.append(("invoice", f"{len(overdue):,} invoice{'' if len(overdue) == 1 else 's'} overdue",
                         f"${total:,.2f} owed, oldest {max(i['days_overdue'] for i in overdue):,} days late"
                         if overdue and "days_overdue" in overdue[0] else f"${total:,.2f} owed",
                         url_for("stripe.invoices_list", status="open"), len(overdue)))
        if stalled:
            rows.append(("invoice", f"{len(stalled):,} plan{'' if len(stalled) == 1 else 's'} not collecting",
                         ", ".join(s.get("customer_name") or s.get("customer") or "" for s in stalled)[:200],
                         url_for("stripe.invoices_list"), len(stalled)))
    n = review_count(business)
    if n:
        rows.append(("bank", f"{n:,} bank line{'' if n == 1 else 's'} to sort", "",
                     url_for("books.bank", id=business.id), n))
    n = _missing_receipts(business).count()
    if n:
        rows.append(("receipt", f"{n:,} expense{'' if n == 1 else 's'} without a receipt", "",
                     url_for("books.company_receipts", id=business.id), n))
    try:
        from pm.attention_routes import _bills_to_enter
        for bill in _bills_to_enter():
            p = bill["provider"]
            owner = p.account_business_id or (_home().id if p.is_ours else None)
            if owner not in family:
                continue
            rows.append(("bill", f"{p.display_name}: {bill['latest']:%B %Y} bill not recorded",
                         f"{bill['count']:,} months missing" if bill["count"] > 1 else "",
                         url_for("service_costs.provider_monthly", id=p.id, month=bill["latest"].strftime("%Y-%m")),
                         bill["count"]))
    except Exception:  # noqa: BLE001
        current_app.logger.exception("vendor bills for the overview")
    if is_home:
        try:
            from pm.hosting_routes import increases_due_count
            n = increases_due_count()
        except Exception:  # noqa: BLE001
            n = 0
        if n:
            rows.append(("hosting", f"{n:,} hosting fee{'' if n == 1 else 's'} under the floor", "",
                         url_for("hosting.hosting_index"), n))
    return rows


@books_bp.route("/admin/books/<int:id>/")
@ceo_required
def company(id):
    """Months and close: the year so far, where its money came from, each
    month newest first with what is left before it closes, and the owners."""
    business = _company(id)
    if business.id != id:
        return redirect(url_for("books.company", id=business.id), 301)
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    months = [month_status(business, m) for m in _months(min(today, date(year, 12, 1))) if m.year == year]
    years = sorted({m.year for m in _months(today)} | {today.year}, reverse=True)
    summary = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    home = _home()
    return _hub("pm/books/months.html", business, "months", year=year, years=years,
                summary=summary, tax=estimated_tax(business, year, summary),
                todo=todo(business, bool(home and business.id == home.id), today),
                months=list(reversed(months)))


@books_bp.route("/admin/books/<int:id>/bank")
@ceo_required
def bank(id):
    """The bank lines this company's accounts and cards read: the ones to
    sort first, every line on request, and the charges a session tagged
    (log_expense) that no line has taken yet."""
    from models import BankConnection, BankTransaction, ExpenseTag, Project, VendorRule
    from pm.bank_routes import CATEGORIES, DISPOSITIONS, _first_owner
    import bank_feed
    business = _company(id)
    family = family_ids(business)
    view = request.args.get("view", "review")
    if view not in ("review", "all", "tags"):
        view = "review"
    q = BankTransaction.query.filter(BankTransaction.business_id.in_(family))
    if view == "review":
        q = q.filter_by(disposition="review")
    lines = (q.order_by(BankTransaction.occurred_on.desc(), BankTransaction.id.desc()).limit(300).all()
             if view != "tags" else [])
    tags = (ExpenseTag.query.filter(ExpenseTag.line_id.is_(None), ExpenseTag.dismissed_at.is_(None),
                                    db.or_(ExpenseTag.business_id.in_(family),
                                           ExpenseTag.business_id.is_(None) if business.id == _home().id
                                           else sa_false()))
            .order_by(ExpenseTag.occurred_on.desc(), ExpenseTag.id.desc()).all())
    businesses = Business.query.order_by(Business.parent_id.isnot(None), Business.name).all()
    waiting = review_count(business)
    suggested = (BankTransaction.query.filter(BankTransaction.business_id.in_(family),
                                              BankTransaction.disposition == "review",
                                              BankTransaction.suggestion_json.isnot(None)).count())
    connections = (BankConnection.query.filter(BankConnection.business_id.in_(family))
                   .order_by(BankConnection.provider, BankConnection.id).all())
    projects = Project.query.order_by(Project.name).all()
    return _hub("pm/books/bank.html", business, "bank", lines=lines, view=view, waiting=waiting,
                suggested=suggested, connections=connections, tags=tags,
                business_options=[(b.id, b.name) for b in businesses],
                project_options=[(0, "No project")] + [(p.id, p.name) for p in projects],
                disposition_options=DISPOSITIONS, category_options=CATEGORIES, norm=bank_feed.norm,
                category_labels=dict(EXPENSE_CATEGORY_CHOICES),
                business_names={b.id: (b.short_name or b.name) for b in businesses},
                owners_by_business={b.id: _first_owner(b.id) for b in businesses},
                disposition_labels=dict(VendorRule.DISPOSITIONS, review="To review", void="Cancelled"))


@books_bp.route("/admin/books/tags/<int:tid>/dismiss", methods=["POST"])
@ceo_required
def tag_dismiss(tid):
    """A logged charge that will never reach a bank the board reads (cash, a
    card it cannot see, or it never happened): off the list for good."""
    from models import ExpenseTag
    tag = db.session.get(ExpenseTag, tid) or abort(404)
    tag.dismissed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash("Set aside.", "success")
    return redirect(_next(url_for("books.index", tab="tags")))


def _next(default):
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return default


def ledger_context(business, args):
    """The company's expenses, filtered, paged, and read four ways off the one
    list, so the totals at the top and the rows beneath are the same money."""
    from models import Client, Expense, Project, ServiceCostEntry, ServiceProvider
    category = args.get("category", "")
    project_id = args.get("project_id", "")
    client_id = args.get("client_id", "")
    year = args.get("year", "")
    page = args.get("page", 1, type=int)
    family = family_ids(business)

    def filtered(q):
        q = q.filter(Expense.time_entry_id.is_(None), Expense.business_id.in_(family))
        if category:
            q = q.filter(Expense.category == category)
        if project_id.isdigit():
            q = q.filter(Expense.project_id == int(project_id))
        if client_id.isdigit():
            q = q.filter(Expense.client_id == int(client_id))
        if year.isdigit():
            q = q.filter(Expense.date >= date(int(year), 1, 1), Expense.date < date(int(year) + 1, 1, 1))
        return q

    # The id last: a date alone is not a total order, and paging through a
    # block of same-day rows would show some twice and others never.
    pagination = (filtered(Expense.query).order_by(Expense.date.desc(), Expense.id.desc())
                  .paginate(page=page, per_page=25, error_out=False))
    rows = filtered(Expense.query).all()
    vendor_of = {}
    for eid, ceid, pid, label, start, finish in (
            db.session.query(Expense.id, Expense.cost_entry_id, ServiceProvider.id, ServiceProvider.display_name,
                             ServiceCostEntry.period_start, ServiceCostEntry.period_end)
            .join(ServiceCostEntry, db.or_(ServiceCostEntry.expense_id == Expense.id,
                                           ServiceCostEntry.id == Expense.cost_entry_id))
            .join(ServiceProvider, ServiceCostEntry.provider_id == ServiceProvider.id)
            .filter(Expense.business_id.in_(family)).all()):
        spans = bool(start and finish and finish > start)
        vendor_of[eid] = {"provider_id": pid, "label": label,
                          "covers": start.strftime("%b %Y") if spans else "",
                          "to_date": spans and finish > date.today()}
    total = round(sum(e.amount for e in rows), 2)
    by_category, by_client, by_month = {}, {}, {}
    labels = dict(EXPENSE_CATEGORY_CHOICES)
    for e in rows:
        cat = labels.get(e.category, e.category or "Other")
        by_category[cat] = by_category.get(cat, 0.0) + e.amount
        who = e.client.name if e.client else "No client"
        by_client[who] = by_client.get(who, 0.0) + e.amount
        if e.date:
            key = e.date.strftime("%Y-%m")
            by_month[key] = by_month.get(key, 0.0) + e.amount
    recent = sorted(by_month)[-6:]
    years = sorted({e.date.year for e in rows if e.date} | {date.today().year}, reverse=True)
    active = bool(category or project_id or client_id or year)
    return {
        "expenses": pagination.items, "pagination": pagination, "total": total,
        "from_bank": round(sum(e.amount for e in rows if e.bank_line_id), 2),
        "by_hand": round(sum(e.amount for e in rows if not e.bank_line_id), 2),
        "unallocated": round(sum(e.amount for e in rows if e.client_id is None), 2),
        "count": len(rows), "vendor_of": vendor_of,
        "by_category": sorted(by_category.items(), key=lambda kv: -kv[1]),
        "by_client": sorted(by_client.items(), key=lambda kv: -kv[1]),
        "by_month": [(m, round(by_month[m], 2)) for m in recent],
        "filters": {"category": category, "project_id": project_id, "client_id": client_id, "year": year},
        "filtered": active, "years": years,
        "projects": Project.query.order_by(Project.name).all(),
        "clients": Client.query.order_by(Client.name).all(),
    }


@books_bp.route("/admin/books/<int:id>/expenses")
@ceo_required
def expenses(id):
    business = _company(id)
    if business.id != id:
        return redirect(url_for("books.expenses", id=business.id, **request.args), 301)
    return _hub("pm/books/expenses.html", business, "expenses", **ledger_context(business, request.args))


@books_bp.route("/admin/books/<int:id>/receipts")
@ceo_required
def company_receipts(id):
    """This company's expenses without a receipt (the job, first), the ones
    standing on a statement line, and mail receipts that matched nothing."""
    from models import Expense
    business = _company(id)
    family = family_ids(business)
    view = request.args.get("view", "missing")
    if view not in ("missing", "statement", "unmatched"):
        view = "missing"
    home = _home()
    rows = (Receipt.query.join(ReceiptMailbox, Receipt.mailbox_id == ReceiptMailbox.id)
            .filter(Receipt.status == "unmatched",
                    db.or_(ReceiptMailbox.business_id.in_(family),
                           ReceiptMailbox.business_id.is_(None) if home and business.id == home.id else sa_false()))
            .order_by(Receipt.received_on.desc(), Receipt.id.desc()).limit(300).all())
    missing = _missing_receipts(business).all()
    statement_only = (Expense.query.filter(
        Expense.business_id.in_(family),
        Expense.receipt_original_name.like(receipts_service.STATEMENT_PROOF + "%"),
        Expense.time_entry_id.is_(None)).order_by(Expense.date.desc(), Expense.id.desc()).all())
    names = {b.id: (b.short_name or b.name) for b in Business.query.all()}
    return _hub("pm/books/receipts.html", business, "receipts", rows=rows, missing=missing, view=view,
                statement_only=statement_only, business_names=names)


@books_bp.route("/admin/books/<int:id>/connections")
@ceo_required
def connections(id):
    """Everything that feeds this company's books, in one place: its Mercury
    banks, its own Stripe, its cards with no feed (statements), the mailboxes
    its receipts come to, and the vendors whose reports split its charges."""
    from models import BankConnection, BankTransaction, ServiceProvider
    business = _company(id)
    family = family_ids(business)
    home = _home()
    banks = (BankConnection.query.filter(BankConnection.business_id.in_(family),
                                         BankConnection.provider == "mercury")
             .order_by(BankConnection.id).all())
    sources = (BankConnection.query.filter(BankConnection.business_id.in_(family),
                                           BankConnection.provider == "statement")
               .order_by(BankConnection.id).all())
    for src in sources:
        src.line_count = BankTransaction.query.filter_by(connection_id=src.id).count()
        src.through = (db.session.query(db.func.max(BankTransaction.occurred_on))
                       .filter(BankTransaction.connection_id == src.id).scalar())
    is_home = bool(home and business.id == home.id)
    mailboxes = (ReceiptMailbox.query.filter(db.or_(ReceiptMailbox.business_id.in_(family),
                                                    ReceiptMailbox.business_id.is_(None) if is_home else sa_false()))
                 .order_by(ReceiptMailbox.id).all())
    providers = (ServiceProvider.query.filter(
        db.or_(ServiceProvider.account_business_id.in_(family),
               db.and_(ServiceProvider.account_business_id.is_(None),
                       ServiceProvider.account_client_id.is_(None)) if is_home else sa_false()))
        .order_by(ServiceProvider.display_name).all())
    return _hub("pm/books/connections.html", business, "connections", banks=banks, sources=sources,
                mailboxes=mailboxes, providers=providers, reading=receipts_service.reading,
                today=date.today(), business_options=[(b.id, b.name) for b in _companies()])


@books_bp.route("/admin/books/<int:id>/year/<int:year>")
@ceo_required
def year_report(id, year):
    business = _company(id)
    if business.id != id:
        return redirect(url_for("books.year_report", id=business.id, year=year), 301)
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    # Schedule C numbers only for a company known to have exactly one owner;
    # with none on file it may be a partnership, as EntertainHQ is.
    single = len(business.owners) == 1
    years = sorted({m.year for m in _months(date.today())} | {date.today().year}, reverse=True)
    return _hub("pm/books/year.html", business, "year", year=year, s=s, years=years,
                single=single, category_labels=dict(EXPENSE_CATEGORY_CHOICES))


@books_bp.route("/admin/books/<int:id>/year/<int:year>.csv")
@ceo_required
def year_csv(id, year):
    business = db.session.get(Business, id) or abort(404)
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    labels = dict(EXPENSE_CATEGORY_CHOICES)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Kind", "Date", "Description", "Category", "Tax line", "Amount", "Company",
                "Client", "Project", "Receipt", "Source"])
    dba_rows = {(w_, a, lbl): name for w_, a, lbl, name in
                books_service.dba_income_between(business, date(year, 1, 1), date(year + 1, 1, 1))}
    for when, amount, label in s["income"]:
        dba = dba_rows.get((when, amount, label))
        w.writerow(["Income", when.isoformat(), label, "", "", f"{amount:.2f}",
                    f"{business.name} d/b/a {dba}" if dba else business.name, "", "", "",
                    "bank" if dba or business.sales_source != "board" else "invoices"])
    for e in s["expenses"]:
        line, number = books_service.tax_line(e.category)
        w.writerow(["Expense", e.date.isoformat(),
                    " ".join(p for p in (e.description, e.sales_tax_note and f"({e.sales_tax_note})") if p),
                    labels.get(e.category, e.category or ""), f"{line} ({number})",
                    f"{e.amount:.2f}", e.business.name if e.business else "",
                    e.client.name if e.client else "", e.project.name if e.project else "",
                    "yes" if e.receipt_filename else "no", books_service.source_of(e)])
    for who, money in s["owner_money"].items():
        if money["in"]:
            w.writerow(["Owner put in", "", who, "", "", f"{money['in']:.2f}", business.name])
        if money["out"]:
            w.writerow(["Owner took out", "", who, "", "", f"{money['out']:.2f}", business.name])
    name = f"{business.short_name or business.name} books {year}.csv".replace("/", "-")
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@books_bp.route("/admin/books/<int:id>/month/<ym>")
@ceo_required
def month_page(id, ym):
    business = _company(id)
    status = month_status(business, _month(ym))
    month_end = books_service.month_bounds(status["month"])[1] - timedelta(days=1)
    return _hub("pm/books/month.html", business, "months", st=status, year=status["month"].year,
                s=status["summary"], bank=books_service.bank_check(business, month_end),
                category_labels=dict(EXPENSE_CATEGORY_CHOICES))


@books_bp.route("/admin/books/<int:id>/month/<ym>/close", methods=["POST"])
@ceo_required
def close_month(id, ym):
    business = db.session.get(Business, id) or abort(404)
    start = _month(ym)
    st = month_status(business, start)
    if not st["finished"]:
        flash("A month can close once it has ended.", "warning")
        return redirect(url_for("books.month_page", id=id, ym=ym))
    row = MonthClose.query.filter_by(business_id=id, month=start).first() or MonthClose(
        business_id=id, month=start)
    row.expenses_total = st["summary"]["expense_total"]
    row.income_total = st["summary"]["income_total"]
    row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.note = (request.form.get("note") or "")[:300]
    db.session.add(row)
    db.session.commit()
    import books_upkeep
    books_upkeep.month_closed_by_hand(id, start)
    flash(f"{start:%B %Y} is closed.", "success")
    return redirect(url_for("books.month_page", id=id, ym=ym))


@books_bp.route("/admin/books/<int:id>/month/<ym>/reopen", methods=["POST"])
@ceo_required
def reopen_month(id, ym):
    row = MonthClose.query.filter_by(business_id=id, month=_month(ym)).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Reopened.", "success")
    return redirect(url_for("books.month_page", id=id, ym=ym))


@books_bp.route("/admin/books/checks")
@ceo_required
def checks():
    """The detail behind a books row on Needs attention: the receipts from
    known vendors that no bank line matches, or the recurring expenses no bank
    line has claimed (books_upkeep.py writes both each night)."""
    from models import BooksFlag
    kind = request.args.get("kind", "receipts")
    if kind not in ("receipts", "recurring"):
        abort(404)
    flag = BooksFlag.query.filter_by(kind=kind, key="all").first()
    names = {b.id: (b.short_name or b.name) for b in Business.query.all()}
    return render_template("pm/books/checks.html", kind=kind, flag=flag,
                           items=flag.items if flag else [], business_names=names)


@books_bp.route("/admin/books/owners", methods=["POST"])
@ceo_required
def owner_add():
    business = db.session.get(Business, request.form.get("business_id", type=int) or 0) or abort(404)
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        flash("Name the owner.", "warning")
        return redirect(url_for("books.company", id=business.id))
    share = request.form.get("share_percent", type=float)
    db.session.add(BusinessOwner(business_id=business.id, name=name, share_percent=share))
    db.session.commit()
    total = sum(o.share_percent or 0 for o in business.owners)
    flash(f"{name} added." + ("" if abs(total - 100) < 0.01 else f" Shares add up to {total:g}%."),
          "success")
    return redirect(url_for("books.company", id=business.id))


@books_bp.route("/admin/books/owners/<int:oid>/delete", methods=["POST"])
@ceo_required
def owner_delete(oid):
    owner = db.session.get(BusinessOwner, oid) or abort(404)
    bid = owner.business_id
    db.session.delete(owner)
    db.session.commit()
    flash("Removed.", "success")
    return redirect(url_for("books.company", id=bid))


@books_bp.route("/admin/books/mailboxes", methods=["POST"])
@ceo_required
def mailbox_add():
    address = (request.form.get("address") or "").strip().lower()[:200]
    password = (request.form.get("password") or "").replace(" ", "").strip()
    if "@" not in address or not password:
        flash("Give the address and its app password.", "warning")
        return redirect(_connections_of(request.form.get("business_id", type=int)))
    box = ReceiptMailbox.query.filter_by(address=address).first() or ReceiptMailbox(address=address)
    box.password = password
    box.business_id = request.form.get("business_id", type=int) or None
    box.imap_host = (request.form.get("imap_host") or "imap.gmail.com").strip()[:120]
    try:
        box.read_from = date.fromisoformat(request.form.get("read_from") or "")
    except ValueError:
        box.read_from = BOOKS_START
    box.last_ok = None
    db.session.add(box)
    db.session.commit()
    _read(box)
    return redirect(_connections_of(request.form.get("business_id", type=int)))


def _connections_of(business_id=None):
    """Back to the Connections tab of the company a form was about."""
    business = _company(business_id) if business_id else _home()
    return _next(url_for("books.connections", id=business.id))


def _read(box):
    """Start reading a mailbox in the background and say so."""
    if receipts_service.sync_in_background(current_app._get_current_object(), box.id):
        flash(f"Reading {box.address}. Receipts appear here as it goes.", "success")
    else:
        flash(f"Already reading {box.address}.", "success")


@books_bp.route("/admin/books/mailboxes/<int:mid>/sync", methods=["POST"])
@ceo_required
def mailbox_sync(mid):
    box = db.session.get(ReceiptMailbox, mid) or abort(404)
    _read(box)
    return redirect(_connections_of(request.form.get("business_id", type=int)))


@books_bp.route("/admin/books/mailboxes/<int:mid>/delete", methods=["POST"])
@ceo_required
def mailbox_delete(mid):
    box = db.session.get(ReceiptMailbox, mid) or abort(404)
    db.session.delete(box)
    db.session.commit()
    flash("Disconnected. Receipts already attached stay on their expenses.", "success")
    return redirect(_connections_of(request.form.get("business_id", type=int)))


@books_bp.route("/admin/books/receipts")
@ceo_required
def receipts():
    """The receipts list lives on each company's Receipts tab now."""
    view = request.args.get("view")
    return redirect(url_for("books.company_receipts", id=_home().id, **({"view": view} if view else {})), 301)


@books_bp.route("/admin/books/receipts/<int:rid>/file")
@ceo_required
def receipt_file(rid):
    r = db.session.get(Receipt, rid) or abort(404)
    if not r.filename:
        abort(404)
    resp = send_from_directory(os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts"),
                               r.filename, download_name=r.original_name or r.filename)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # A receipt saved as HTML is somebody else's markup: it never runs here.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src * data:; style-src 'unsafe-inline'"
    return resp


@books_bp.route("/admin/books/receipts/<int:rid>/ignore", methods=["POST"])
@ceo_required
def receipt_ignore(rid):
    r = db.session.get(Receipt, rid) or abort(404)
    r.status = "ignored"
    db.session.commit()
    import books_upkeep
    books_upkeep.receipt_set_aside(rid)
    flash("Set aside.", "success")
    if request.form.get("next") == "checks":
        return redirect(url_for("books.checks", kind="receipts"))
    return redirect(_next(url_for("books.receipts")))


# ── The hub: a company's own app reads its books ─────────


@books_bp.route("/api/hub/books", methods=["POST"])
def hub_books():
    """A company's books for its own app to show, read only.

    Signed with the company's hub secret like every hub call. The app may
    send its own sales ({"sales": [{date, total, ref}]}) and they are the
    income; without them the income is what its bank received. The board
    never calls back into the app from inside this request.
    """
    from pm.business_routes import _hub_business, _hub_json
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    year = int(data.get("year") or date.today().year)
    sales = None
    if isinstance(data.get("sales"), list):
        sales = []
        for s in data["sales"]:
            try:
                sales.append({"date": date.fromisoformat(str(s["date"])[:10]),
                              "total": float(s["total"]), "ref": str(s.get("ref") or "")[:120]})
            except (KeyError, TypeError, ValueError):
                continue
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1), sales)
    labels = dict(EXPENSE_CATEGORY_CHOICES)
    closes = {m.month.strftime("%Y-%m"): m.closed_at.isoformat() if m.closed_at else None
              for m in MonthClose.query.filter_by(business_id=business.id).all()}
    return jsonify({
        "business": business.name, "year": year,
        "income_total": s["income_total"], "expense_total": s["expense_total"], "net": s["net"],
        "by_month": [{"month": k, **v, "closed_at": closes.get(k)} for k, v in s["by_month"].items()],
        "by_line": [{"label": r["label"], "total": r["total"], "count": r["count"]}
                    for r in s["tax_lines"]],
        "expenses": [{"date": e.date.isoformat(), "description": e.description or "",
                      "category": labels.get(e.category, e.category or ""), "amount": e.amount,
                      "receipt": bool(e.receipt_filename)} for e in s["expenses"]],
        "income": [{"date": d.isoformat(), "amount": a, "description": l} for d, a, l in s["income"]],
        "owners": [{"name": o.name, "share_percent": o.share_percent,
                    "put_in": s["owner_money"].get(o.name, {}).get("in", 0.0),
                    "took_out": s["owner_money"].get(o.name, {}).get("out", 0.0)}
                   for o in business.owners],
        "unsorted_bank_lines": s["unsorted"],
    })


# ── A company's own Stripe ────────────────────────────────


@books_bp.route("/admin/books/<int:id>/stripe", methods=["POST"])
@ceo_required
def stripe_connect(id):
    import stripe_books
    business = db.session.get(Business, id) or abort(404)
    back = url_for("books.connections", id=_company(id).id)
    key = (request.form.get("key") or "").strip()
    if not key:
        flash("Paste the restricted key from Stripe.", "warning")
        return redirect(back)
    try:
        stripe_books.check_key(key)
    except stripe_books.StripeKeyError as err:
        flash(str(err), "warning")
        return redirect(back)
    business.stripe_key = key
    business.stripe_ok = None
    business.stripe_synced_at = None
    db.session.commit()
    result = stripe_books.sync(business)
    flash(result.get("error") or f"Connected. {business.stripe_note}.",
          "warning" if result.get("error") else "success")
    return redirect(back)


@books_bp.route("/admin/books/<int:id>/stripe/sync", methods=["POST"])
@ceo_required
def stripe_sync(id):
    import stripe_books
    business = db.session.get(Business, id) or abort(404)
    if not business.stripe_key:
        abort(404)
    result = stripe_books.sync(business)
    flash(result.get("error") or f"{business.stripe_note}.",
          "warning" if result.get("error") else "success")
    return redirect(url_for("books.connections", id=_company(id).id))


@books_bp.route("/admin/books/<int:id>/stripe/disconnect", methods=["POST"])
@ceo_required
def stripe_disconnect(id):
    business = db.session.get(Business, id) or abort(404)
    business.stripe_key = None
    business.stripe_ok = None
    business.stripe_note = ""
    db.session.commit()
    flash("Disconnected. What it read stays in the books.", "success")
    return redirect(url_for("books.connections", id=_company(id).id))


# ── Cards and accounts with no feed: their statements ─────


@books_bp.route("/admin/books/statements", methods=["POST"])
@ceo_required
def statement_source_add():
    from models import BankConnection
    business = db.session.get(Business, request.form.get("business_id", type=int) or 0) or abort(404)
    label = (request.form.get("label") or "").strip()[:120]
    if not label:
        flash("Name the card or account.", "warning")
        return redirect(_connections_of(request.form.get("business_id", type=int)))
    kind = "personal" if request.form.get("kind") == "personal" else "business"
    conn = BankConnection(business_id=business.id, provider="statement", label=label, token="",
                          kind=kind, owner_name=(request.form.get("owner_name") or "").strip()[:120],
                          charges_positive=request.form.get("charges_positive") == "1")
    db.session.add(conn)
    db.session.commit()
    flash(f"{label} added. Upload its statements below.", "success")
    return redirect(_connections_of(request.form.get("business_id", type=int)))


@books_bp.route("/admin/books/statements/<int:cid>/upload", methods=["POST"])
@ceo_required
def statement_upload(cid):
    import statements
    from models import BankConnection
    conn = db.session.get(BankConnection, cid) or abort(404)
    if conn.provider != "statement":
        abort(404)
    files = [f for f in request.files.getlist("statement") if f and f.filename]
    if not files:
        flash("Choose the statement file you downloaded.", "warning")
        return redirect(_connections_of(request.form.get("business_id", type=int)))
    total = {"read": 0, "new": 0}
    for f in files:
        raw = f.read(5 * 1024 * 1024)
        try:
            rows = statements.parse(raw.decode("utf-8-sig", "replace"), conn.charges_positive)
        except statements.StatementError as err:
            flash(f"{f.filename}: {err}", "warning")
            return redirect(_connections_of(request.form.get("business_id", type=int)))
        got = statements.import_rows(conn, rows)
        total["read"] += got["read"]
        total["new"] += got["new"]
    # The charges just arrived, so go and look for their receipts now rather
    # than tonight. On its own thread, because a big statement outlives the page.
    import receipts_service
    from models import ReceiptMailbox
    for box in ReceiptMailbox.query.all():
        receipts_service.sync_in_background(current_app._get_current_object(), box.id)
    waiting = got.get("review", 0)
    flash(f"{conn.label}: {total['new']:,} new line{'' if total['new'] == 1 else 's'} of "
          f"{total['read']:,} read, {waiting:,} to sort.", "success")
    return redirect(url_for("books.bank", id=_company(conn.business_id).id) if waiting
                    else _connections_of(conn.business_id))


@books_bp.route("/admin/books/statements/<int:cid>/delete", methods=["POST"])
@ceo_required
def statement_source_delete(cid):
    from models import BankConnection
    conn = db.session.get(BankConnection, cid) or abort(404)
    if conn.provider != "statement":
        abort(404)
    db.session.delete(conn)
    db.session.commit()
    flash("Removed. The expenses it booked are still in the books.", "success")
    return redirect(_connections_of(request.form.get("business_id", type=int)))
