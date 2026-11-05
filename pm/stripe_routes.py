"""Invoices: the list, New invoice, a thin strip of the Stripe balance, and
the time logged that is on no invoice yet.

Every page here is the CEO's (docs/finances_plan.md items 3 and 10), so every
route carries `ceo_required`, except the Stripe webhook, which Stripe calls
with its signature and no login.
"""
import time
from datetime import datetime, timezone, date, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, jsonify,
)
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from models import db, Client, Project, TimeEntry, Expense, Invoice, InvoiceLineItem
from pm.users_routes import ceo_required
from stripe_service import (
    create_stripe_customer, get_stripe_balance, create_stripe_invoice,
    finalize_and_send_invoice, void_stripe_invoice, sync_invoice_from_stripe,
    handle_webhook_event, import_invoices_from_stripe, process_invoice_event,
    get_stripe_invoice_totals, get_stripe_invoices, invoice_earned, invoice_kept,
)

stripe_bp = Blueprint("stripe", __name__, url_prefix="/admin/stripe")

# An invoice holds time while it is a draft, open or paid. A void or
# uncollectible one has let its time go, so that time is waiting again.
HOLDS_TIME = ("draft", "open", "paid")


def _clip(text, limit=380):
    """Trim a free-text body so the derived invoice line-item description stays
    within Stripe's ~500-char description limit and the InvoiceLineItem column.
    Long work-session write-ups live in full on the time entry/expense; the
    invoice line item only needs a readable summary."""
    text = (text or "").strip()
    return (text[:limit].rstrip() + "…") if len(text) > limit else text


# ── Time already on an invoice ──────────────────────────────


def _invoiced_time_ids():
    return db.session.query(InvoiceLineItem.time_entry_id).filter(
        InvoiceLineItem.time_entry_id.isnot(None),
        InvoiceLineItem.invoice.has(Invoice.status.in_(HOLDS_TIME)),
    )


def _for_client(client_id):
    """A time entry is the client's by its own client_id, or by its project's
    when the entry carries none: an entry typed before client_id existed
    would otherwise be counted as waiting and never offered on the invoice."""
    return or_(
        TimeEntry.client_id == client_id,
        and_(TimeEntry.client_id.is_(None),
             TimeEntry.project.has(Project.client_id == client_id)),
    )


# ── The Stripe strip ────────────────────────────────────────


def _decorate(invoices, client_names, local_ids=None):
    """Copy each invoice row with the name the templates should show, and the
    id of the board's own record of it when there is one.

    The local client wins over Stripe's name, because the board is where
    these names are curated; Stripe's is the fallback for a customer with no
    client record.
    """
    local_ids = local_ids or {}
    rows = []
    for inv in invoices:
        row = dict(inv)
        row["client_name"] = (
            client_names.get(inv["customer_id"]) or inv["customer_name"] or "Unknown"
        )
        row["local_id"] = local_ids.get(inv.get("id"))
        rows.append(row)
    return rows


class _Page:
    """Just enough of Flask-SQLAlchemy's pagination for the invoice table.

    The rows come from Stripe rather than a query, and Stripe pages by
    cursor rather than by number. The full list is small and already cached,
    so it is sliced here and the shared pagination macro works unchanged.
    """

    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.per_page = per_page
        self.pages = max(1, -(-self.total // per_page))
        self.page = min(max(page, 1), self.pages)
        start = (self.page - 1) * per_page
        self.items = items[start:start + per_page]
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else None
        self.next_num = self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        """Page numbers with None where the template should draw a gap."""
        last = 0
        for num in range(1, self.pages + 1):
            if (num <= left_edge
                    or (self.page - left_current - 1 < num < self.page + right_current)
                    or num > self.pages - right_edge):
                if last + 1 != num:
                    yield None
                yield num
                last = num


# The balance is asked for on every render of either tab, and a filter pick
# renders the page again on the server even though the strip is never
# swapped. A minute is fresh enough for a balance and keeps Stripe out of
# every pick.
_balance_cache = {"ts": 0.0, "data": None}
BALANCE_TTL = 60


def _balance():
    now = time.time()
    if _balance_cache["data"] is not None and now - _balance_cache["ts"] < BALANCE_TTL:
        return _balance_cache["data"]
    balance = get_stripe_balance()
    if balance is None:
        return None
    figures = {"available": 0.0, "pending": 0.0}
    for key in figures:
        for b in getattr(balance, key, None) or []:
            if getattr(b, "currency", None) == "usd":
                figures[key] += (b.amount or 0) / 100.0
    _balance_cache.update({"ts": now, "data": figures})
    return figures


def _account_overview():
    """The thin strip over both tabs: what sits in the Stripe balance,
    available and pending, and what is open in Stripe across the whole
    account.

    Open in Stripe is read from Stripe, not from local rows, so it holds every
    open invoice, the ones raised in Stripe's own dashboard and by a
    subscription included. The list's own figure is Unpaid in this list,
    which follows the filters; the two were both called Outstanding until
    2026-11-04.

    Every network read is inside a try: a Stripe outage costs the strip,
    never the list under it, and the strip then says Stripe did not answer
    rather than showing $0.00.
    """
    stripe_ok = True
    available = pending = 0.0
    try:
        figures = _balance()
        if figures is None:
            stripe_ok = False
        else:
            available, pending = figures["available"], figures["pending"]
    except Exception:
        stripe_ok = False
    try:
        totals = get_stripe_invoice_totals()
    except Exception:
        totals = {"open": 0.0, "open_count": 0}
    return {
        "stripe_ok": stripe_ok,
        "available_balance": available,
        "pending_balance": pending,
        "account_outstanding": totals["open"],
        "open_invoice_count": totals["open_count"],
    }


def _page_context(tab):
    """What the list draws outside its panel: the Stripe strip."""
    return dict(_account_overview(), tab=tab)


@stripe_bp.route("/")
@ceo_required
def stripe_dashboard():
    """The old Stripe page's address. Nothing on the board links here any
    more; bookmarks still do, so it answers a permanent redirect."""
    return redirect(url_for("stripe.invoices_list"), code=301)


@stripe_bp.route("/clients/sync-all", methods=["POST"])
@stripe_bp.route("/setup-products", methods=["POST"])
@ceo_required
def retired_presses():
    """Sync All Clients and Setup Products went on 2026-11-04 (finances plan
    item 3): a client is linked to its Stripe customer as it is saved or
    invoiced (`stripe_service.link_or_create_customer`), and an invoice line
    carries its own amount, so no product needs setting up. A page left open
    across the deploy still posts here, and lands back on the list rather
    than on a 404."""
    return redirect(url_for("stripe.invoices_list"), code=303)


# ── Invoice List ────────────────────────────────────────────


@stripe_bp.route("/invoices")
@ceo_required
def invoices_list():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status", "")
    client_id = request.args.get("client_id", "", type=str)
    month = request.args.get("month", "")  # 'YYYY-MM'

    # Resolve month -> [start, end) bounds on created_at (the visible "Date").
    month_start = month_end = None
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            # Timezone aware, because they are compared against Stripe's
            # created timestamps. Naive against aware is a TypeError, not a
            # wrong answer, so it would take the whole page down.
            month_start = datetime(y, m, 1, tzinfo=timezone.utc)
            month_end = (
                datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12
                else datetime(y, m + 1, 1, tzinfo=timezone.utc)
            )
        except (ValueError, TypeError):
            month = ""

    clients = Client.query.order_by(Client.name).all()
    client_names = {c.stripe_customer_id: c.name for c in clients if c.stripe_customer_id}
    local_ids = dict(db.session.query(Invoice.stripe_invoice_id, Invoice.id)
                     .filter(Invoice.stripe_invoice_id.isnot(None)).all())

    # The filter is by local client; Stripe knows customers. A client with no
    # Stripe customer matches nothing, which is the truthful answer rather
    # than the whole unfiltered list.
    selected_customer = ""
    if client_id:
        chosen = db.session.get(Client, int(client_id)) if client_id.isdigit() else None
        selected_customer = (chosen.stripe_customer_id or "") if chosen else ""

    def shown(inv):
        if client_id and inv["customer_id"] != selected_customer:
            return False
        if month_start is not None:
            created = inv["created_at"]
            if created is None or not (month_start <= created < month_end):
                return False
        return not status or inv["status"] == status

    # The tiles are of the rows, every filter included, status too: a figure
    # named "in this list" that ignored the status filter would say $500
    # unpaid over a list of paid invoices.
    rows = [i for i in _decorate(get_stripe_invoices(), client_names, local_ids) if shown(i)]
    pagination = _Page(rows, page, 20)

    # "Billed" rather than "Invoiced": everything raised in the list, paid
    # included.
    billed = [i for i in rows if i["status"] != "void"]
    total_billed = sum(i["total"] for i in billed)
    # After refunds, because Stripe keeps a refunded invoice "paid". What is
    # left is the Books page's income once the sales tax beside it comes off.
    total_paid = sum(invoice_kept(i) for i in rows)
    total_refunded = sum(i.get("refunded") or 0.0 for i in rows)
    total_sales_tax = sum(invoice_kept(i) - invoice_earned(i) for i in rows if i["status"] == "paid")
    unpaid = [i for i in rows if i["status"] in ("draft", "open")]
    total_outstanding = sum(i["amount_due"] for i in unpaid)

    today = date.today()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    return render_template("pm/stripe/invoices/list.html",
        **_page_context("invoices"),
        invoices=pagination.items,
        pagination=pagination,
        status=status,
        client_id=client_id,
        month=month,
        this_month=this_month,
        last_month=last_month,
        clients=clients,
        billed_count=len(billed),
        unpaid_count=len(unpaid),
        total_billed=total_billed,
        total_paid=total_paid,
        total_refunded=total_refunded,
        total_sales_tax=total_sales_tax,
        total_outstanding=total_outstanding,
    )


# /invoices/unbilled was the Time not yet billed tab: hours on no invoice, per
# client, with a press that started an invoice with all of them ticked. Nearly
# every hour on it had been logged by Claude sessions, not tracked by a person,
# and Michael, 2026-11-05: "get rid of this time not billed yet thing on the
# invoice. It doesn't need to exist at all." It answers 301 to the list.
@stripe_bp.route("/invoices/unbilled")
@ceo_required
def unbilled():
    return redirect(url_for("stripe.invoices_list"), 301)


@stripe_bp.route("/invoices/stripe/<stripe_id>")
@ceo_required
def invoice_open(stripe_id):
    """A row of the list opens the board's record of the invoice.

    The list reads Stripe live and the record is written by the import
    (nightly, and Record these), so a row from the last few minutes may not
    have one yet: it is written now, from the list already cached. An invoice
    whose Stripe customer is on no client cannot be stored
    (`import_invoices_from_stripe` says why), so that one says so and the
    list comes back.
    """
    local = Invoice.query.filter_by(stripe_invoice_id=stripe_id).first()
    if local is None:
        import_invoices_from_stripe(ttl=300)
        local = Invoice.query.filter_by(stripe_invoice_id=stripe_id).first()
    if local is None:
        flash("That invoice's Stripe customer is on no client here. Set it on the client to open it.",
              "warning")
        return redirect(url_for("stripe.invoices_list"))
    return redirect(url_for("stripe.invoice_detail", id=local.id))


# ── Generate Invoice ────────────────────────────────────────


@stripe_bp.route("/invoices/import", methods=["POST"])
@ceo_required
def invoices_import():
    """Write Stripe's invoices down as local rows, now.

    This page has always been right, because it reads Stripe live. Everything
    else on the board reads local rows, and a local row only existed for an
    invoice the board itself raised, so the client page and the hosting page
    were reading an incomplete copy of what this page was showing correctly.

    Also runs nightly. The button is for the minute after money arrives.
    """
    made, updated, orphans = import_invoices_from_stripe()
    if made:
        flash(f"{made} invoice{'' if made == 1 else 's'} written down, "
              f"{updated} brought up to date.", "success")
    else:
        flash(f"Nothing new. {updated} already recorded and up to date.", "info")
    if orphans:
        # Named rather than swallowed. An import that quietly leaves money out
        # is the bug this whole thing exists to fix.
        names = ", ".join(orphans[:4]) + ("..." if len(orphans) > 4 else "")
        flash(f"{len(orphans)} could not be placed: {names}. Their Stripe "
              "customer is not on any client here; set it on the client.",
              "warning")
    return redirect(request.form.get("next") or url_for("stripe.invoices_list"))


@stripe_bp.route("/invoices/new", methods=["GET", "POST"])
@ceo_required
def invoice_create():
    if request.method == "POST":
        client_id = request.form.get("client_id", type=int)
        project_id = request.form.get("project_id", type=int) or None
        due_days = request.form.get("due_days", 30, type=int)
        notes = request.form.get("notes", "").strip()
        period_start = _parse_date_arg(request.form.get("period_start"))
        period_end = _parse_date_arg(request.form.get("period_end"))
        time_entry_ids = request.form.getlist("time_entries", type=int)
        expense_ids = request.form.getlist("expenses", type=int)

        client = db.session.get(Client, client_id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for("stripe.invoice_create"))

        if not client.stripe_customer_id:
            result = create_stripe_customer(client)
            if not result:
                flash("Failed to create Stripe customer. Check your Stripe API key.", "error")
                return redirect(url_for("stripe.invoice_create"))
            db.session.commit()

        line_items_data = []
        time_entries = []
        expenses = []

        if time_entry_ids:
            time_entries = TimeEntry.query.filter(TimeEntry.id.in_(time_entry_ids)).all()
            for entry in time_entries:
                body = _clip(entry.description or "Development work")
                desc = f"{entry.rate_type.replace('_', ' ').title()} - {body} ({entry.date.strftime('%b %d')})"
                line_items_data.append({
                    "description": desc,
                    "quantity": entry.hours,
                    "unit_amount": entry.rate,
                })

        if expense_ids:
            expenses = Expense.query.filter(Expense.id.in_(expense_ids)).all()
            for expense in expenses:
                body = _clip(expense.description or expense.category)
                desc = f"Expense: {body} ({expense.date.strftime('%b %d')})"
                line_items_data.append({
                    "description": desc,
                    "quantity": 1,
                    "unit_amount": expense.amount,
                })

        if not line_items_data:
            flash("No line items selected.", "error")
            return redirect(url_for("stripe.invoice_create"))

        # Texas sales tax goes on at the moment of writing, because every
        # invoice that went out without it became a balance to chase the
        # client for afterwards. An exempt client gets none. If the rate
        # cannot be made the draft is still written and the sales tax page
        # lists it as a draft missing tax, rather than the press failing.
        tax_rate_ids = None
        if not client.sales_tax_exempt:
            from models import SalesTaxSetting
            from stripe_service import ensure_sales_tax_rate
            sales_settings = SalesTaxSetting.get()
            rate_id, rate_err = ensure_sales_tax_rate(sales_settings)
            if rate_id:
                db.session.commit()
                tax_rate_ids = [rate_id]
            else:
                flash(f"Drafted without sales tax: {rate_err}", "warning")

        stripe_invoice, stripe_line_items = create_stripe_invoice(
            client, line_items_data, due_days=due_days, memo=notes,
            tax_rate_ids=tax_rate_ids,
        )

        if not stripe_invoice:
            flash(f"Stripe error: {stripe_line_items}", "error")
            return redirect(url_for("stripe.invoice_create"))

        subtotal = sum(item["quantity"] * item["unit_amount"] for item in line_items_data)
        local_invoice = Invoice(
            client_id=client.id,
            project_id=project_id,
            stripe_invoice_id=stripe_invoice.id,
            status="draft",
            subtotal=subtotal,
            total=subtotal,
            amount_due=subtotal,
            due_date=date.today() + timedelta(days=due_days),
            period_start=period_start,
            period_end=period_end,
            notes=notes,
        )
        db.session.add(local_invoice)
        db.session.flush()

        for i, entry in enumerate(time_entries):
            li = InvoiceLineItem(
                invoice_id=local_invoice.id,
                time_entry_id=entry.id,
                description=line_items_data[i]["description"],
                quantity=entry.hours,
                unit_amount=entry.rate,
                total=entry.hours * entry.rate,
                item_type="time",
            )
            db.session.add(li)

        offset = len(time_entries)
        for i, expense in enumerate(expenses):
            li = InvoiceLineItem(
                invoice_id=local_invoice.id,
                expense_id=expense.id,
                description=line_items_data[offset + i]["description"],
                quantity=1,
                unit_amount=expense.amount,
                total=expense.amount,
                item_type="expense",
            )
            db.session.add(li)

        db.session.commit()

        sync_invoice_from_stripe(local_invoice)
        db.session.commit()

        flash(f"Invoice draft created successfully.", "success")
        return redirect(url_for("stripe.invoice_detail", id=local_invoice.id))

    clients = Client.query.order_by(Client.name).all()
    projects = Project.query.order_by(Project.name).all()
    preselect_client = request.args.get("client_id", type=int)
    preselect_project = request.args.get("project_id", type=int)
    return render_template("pm/stripe/invoices/generate.html",
        clients=clients,
        projects=projects,
        preselect_client=preselect_client,
        preselect_project=preselect_project,
    )


# ── Invoice Detail ──────────────────────────────────────────


@stripe_bp.route("/invoices/<int:id>")
@ceo_required
def invoice_detail(id):
    invoice = db.session.get(Invoice, id) or abort(404)
    sync_invoice_from_stripe(invoice)
    db.session.commit()
    line_items = invoice.line_items.all()
    return render_template("pm/stripe/invoices/detail.html",
        invoice=invoice,
        line_items=line_items,
    )


# ── Send Invoice ────────────────────────────────────────────


@stripe_bp.route("/invoices/<int:id>/send", methods=["POST"])
@ceo_required
def invoice_send(id):
    invoice = db.session.get(Invoice, id) or abort(404)
    if invoice.status != "draft":
        flash("Only draft invoices can be sent.", "error")
        return redirect(url_for("stripe.invoice_detail", id=id))

    result, error = finalize_and_send_invoice(invoice.stripe_invoice_id)
    if error:
        flash(f"Error sending invoice: {error}", "error")
    else:
        invoice.status = "open"
        invoice.sent_at = datetime.now(timezone.utc)
        sync_invoice_from_stripe(invoice)
        db.session.commit()
        flash("Invoice sent to client.", "success")

    return redirect(url_for("stripe.invoice_detail", id=id))


# ── Void Invoice ────────────────────────────────────────────


@stripe_bp.route("/invoices/<int:id>/void", methods=["POST"])
@ceo_required
def invoice_void(id):
    invoice = db.session.get(Invoice, id) or abort(404)
    if invoice.status not in ("draft", "open"):
        flash("Only draft or open invoices can be voided.", "error")
        return redirect(url_for("stripe.invoice_detail", id=id))

    result, error = void_stripe_invoice(invoice.stripe_invoice_id)
    if error:
        flash(f"Error voiding invoice: {error}", "error")
    else:
        invoice.status = "void"
        db.session.commit()
        flash("Invoice voided.", "success")

    return redirect(url_for("stripe.invoice_detail", id=id))


# ── Sync Invoice ────────────────────────────────────────────


@stripe_bp.route("/invoices/<int:id>/sync", methods=["POST"])
@ceo_required
def invoice_sync(id):
    invoice = db.session.get(Invoice, id) or abort(404)
    if sync_invoice_from_stripe(invoice):
        db.session.commit()
        flash("Invoice synced from Stripe.", "success")
    else:
        flash("Failed to sync from Stripe.", "error")
    return redirect(url_for("stripe.invoice_detail", id=id))


# ── Date-range helper ───────────────────────────────────────


def _parse_date_arg(value):
    """Parse a YYYY-MM-DD query arg into a date, or None if absent/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ── API: Uninvoiced Time Entries ────────────────────────────


@stripe_bp.route("/api/uninvoiced-entries/<int:client_id>")
@ceo_required
def api_uninvoiced_entries(client_id):
    start = _parse_date_arg(request.args.get("start"))
    end = _parse_date_arg(request.args.get("end"))
    project_id = request.args.get("project_id", type=int)

    # The client's own time, and none already on a live invoice. Only New
    # invoice asks, and only with FEATURE_TIME_TRACKING on.
    query = TimeEntry.query.filter(
        _for_client(client_id),
        ~TimeEntry.id.in_(_invoiced_time_ids()),
    )
    if start:
        query = query.filter(TimeEntry.date >= start)
    if end:
        query = query.filter(TimeEntry.date <= end)
    if project_id:
        query = query.filter(TimeEntry.project_id == project_id)

    entries = query.order_by(TimeEntry.date.desc()).all()

    return jsonify([{
        "id": e.id,
        "date": e.date.isoformat(),
        "hours": e.hours,
        "rate_type": e.rate_type,
        "rate": e.rate,
        "cost": e.cost,
        "description": e.description,
        "project_name": e.project.name if e.project else "",
        "is_free": e.is_free_maintenance,
    } for e in entries])


# ── API: Uninvoiced Expenses ────────────────────────────────


@stripe_bp.route("/api/uninvoiced-expenses/<int:client_id>")
@ceo_required
def api_uninvoiced_expenses(client_id):
    start = _parse_date_arg(request.args.get("start"))
    end = _parse_date_arg(request.args.get("end"))
    project_id = request.args.get("project_id", type=int)

    invoiced_ids = db.session.query(InvoiceLineItem.expense_id).filter(
        InvoiceLineItem.expense_id.isnot(None),
        InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
    ).subquery()

    query = Expense.query.filter(
        Expense.client_id == client_id,
        # Exclude auto-generated "billable_time" mirror expenses - the underlying
        # TimeEntry is already billed as its own line item, so surfacing the mirror
        # here would double-bill the same work. Mirrors up via time_entry_id
        # (see _sync_expense_for_time_entry / Project.total_expenses).
        Expense.time_entry_id.is_(None),
        ~Expense.id.in_(db.session.query(invoiced_ids)),
    )
    if start:
        query = query.filter(Expense.date >= start)
    if end:
        query = query.filter(Expense.date <= end)
    if project_id:
        query = query.filter(Expense.project_id == project_id)

    expenses = query.order_by(Expense.date.desc()).all()

    return jsonify([{
        "id": e.id,
        "date": e.date.isoformat(),
        "amount": e.amount,
        "description": e.description,
        "category": e.category,
        "project_name": e.project.name if e.project else "",
    } for e in expenses])


# ── Webhook ─────────────────────────────────────────────────


@stripe_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    event, error = handle_webhook_event(payload, sig_header)
    if error:
        return jsonify({"error": error}), 400

    event_type = event["type"]
    invoice_events = [
        "invoice.finalized", "invoice.sent", "invoice.paid",
        "invoice.payment_failed", "invoice.payment_succeeded",
        "invoice.voided", "invoice.marked_uncollectible",
    ]

    if event_type in invoice_events:
        process_invoice_event(event)

    return jsonify({"status": "ok"}), 200
