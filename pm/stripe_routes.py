from datetime import datetime, timezone, date, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, jsonify,
)
from flask_login import login_required

from models import db, Client, Project, TimeEntry, Expense, Invoice, InvoiceLineItem, StripeWebhookLog
from stripe_service import (
    create_stripe_customer, get_stripe_balance, get_recent_payments,
    get_recent_payouts, create_stripe_invoice, finalize_and_send_invoice,
    void_stripe_invoice, sync_invoice_from_stripe, handle_webhook_event,
    process_invoice_event, ensure_products_exist, get_stripe_invoice_totals,
    get_stripe_invoices,
)

stripe_bp = Blueprint("stripe", __name__, url_prefix="/admin/stripe")


def _clip(text, limit=380):
    """Trim a free-text body so the derived invoice line-item description stays
    within Stripe's ~500-char description limit and the InvoiceLineItem column.
    Long work-session write-ups live in full on the time entry/expense; the
    invoice line item only needs a readable summary."""
    text = (text or "").strip()
    return (text[:limit].rstrip() + "…") if len(text) > limit else text


# ── Stripe Dashboard ────────────────────────────────────────


def _payer_name(charge, client_names):
    """Who paid, in the name this business actually uses for them.

    This used to read `billing_details.name`, which is the cardholder name a
    payment form captured rather than anything about the customer. Stripe fills
    it for a Checkout session that collected a name and leaves it empty for an
    invoice paid against a saved payment method. That is the whole reason the
    two subscription signups showed a name here and every invoice payment
    showed "Unknown" while having a perfectly good customer attached to it.

    So read the customer, and prefer the local client's name over Stripe's.
    The PM is where these names are curated: a client renamed here should not
    go on showing whatever was typed into Stripe when the account was opened.

    Falls back through the customer's own name, then their email, then the
    cardholder name, and only says "Unknown" when a charge genuinely has
    nobody attached to it.
    """
    customer = getattr(charge, "customer", None)
    customer_id = customer if isinstance(customer, str) else getattr(customer, "id", None)

    if customer_id and customer_id in client_names:
        return client_names[customer_id]

    # A deleted customer still expands, but to a stub carrying an id and
    # nothing else, so `deleted` has to be checked before trusting the fields.
    if customer is not None and not isinstance(customer, str) and not getattr(customer, "deleted", False):
        for field in ("name", "email"):
            value = getattr(customer, field, None)
            if value:
                return value

    billing = getattr(charge, "billing_details", None)
    return (getattr(billing, "name", None) if billing else None) or "Unknown"


def _client_name_map():
    """Stripe customer id to the name this business uses for them."""
    return {
        c.stripe_customer_id: c.name
        for c in Client.query.filter(Client.stripe_customer_id.isnot(None)).all()
    }


def _decorate(invoices, client_names):
    """Copy each invoice row with the name the templates should show.

    Same precedence as the payments panel: the local client wins, because the
    PM is where these names are curated, and Stripe's own name is the fallback
    for a customer with no client record.
    """
    rows = []
    for inv in invoices:
        row = dict(inv)
        row["client_name"] = (
            client_names.get(inv["customer_id"]) or inv["customer_name"] or "Unknown"
        )
        rows.append(row)
    return rows


class _Page:
    """Just enough of Flask-SQLAlchemy's pagination for the invoice table.

    The rows come from Stripe now rather than a query, and Stripe pages by
    cursor rather than by number. The full list is small and already cached, so
    it gets sliced here and the template's existing page links keep working
    without being rewritten around cursors.
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


def _account_overview():
    """Balance, payments and payouts - the half of the Invoices page
    that only Stripe can answer for.

    Every network read here is inside the try: a Stripe outage must
    cost the account panel, not the invoice list beside it.
    """
    available = 0
    pending = 0
    payments = []
    payouts = []

    try:
        balance = get_stripe_balance()
        if balance:
            for b in balance.available:
                if b.currency == "usd":
                    available = b.amount / 100.0
            for b in balance.pending:
                if b.currency == "usd":
                    pending = b.amount / 100.0

        # Read once for the whole page rather than per row. Duplicated ids
        # would be a mapping mistake somewhere else; last one wins here.
        client_names = _client_name_map()

        raw_payments = get_recent_payments(limit=10)
        for p in raw_payments:
            payments.append({
                "name": _payer_name(p, client_names),
                "description": p.description or "Payment",
                "amount": (p.amount or 0) / 100.0,
                "status": p.status or "unknown",
            })

        raw_payouts = get_recent_payouts(limit=5)
        for p in raw_payouts:
            arrival = None
            if p.arrival_date:
                arrival = datetime.fromtimestamp(p.arrival_date, tz=timezone.utc)
            payouts.append({
                "amount": (p.amount or 0) / 100.0,
                "status": p.status or "unknown",
                "arrival_date": arrival,
                "type": p.type or "bank_account",
            })
    except Exception as e:
        import traceback
        traceback.print_exc()

    # Outstanding is read from Stripe, not from local Invoice rows: a
    # local record only exists for an invoice raised through this app's
    # own New Invoice flow, and production has none. Reading the local
    # rows showed nothing owed while real money sat open, which is the
    # most misleading thing a finance page can do.
    try:
        invoice_totals = get_stripe_invoice_totals()
    except Exception:
        invoice_totals = {"open": 0, "open_count": 0}

    return {
        "available_balance": available,
        "pending_balance": pending,
        "payments": payments,
        "payouts": payouts,
        # Named apart from the invoice list's own total_outstanding,
        # which is scoped to whatever the filters show. Same word, two
        # numbers, and they share a template context now.
        "account_outstanding": invoice_totals["open"],
        "open_invoice_count": invoice_totals["open_count"],
    }


@stripe_bp.route("/")
@login_required
def stripe_dashboard():
    """Kept as a redirect.

    Stripe is how the invoices go out and how the money comes back, so
    it is half of the Invoices page rather than a page of its own. This
    route stays because bookmarks and old links point at it.
    """
    return redirect(url_for("stripe.invoices_list") + "#stripe")


# ── Invoice List ────────────────────────────────────────────


@stripe_bp.route("/invoices")
@login_required
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

    # The filter is by local client; Stripe knows customers. A client with no
    # Stripe customer matches nothing, which is the truthful answer rather
    # than the whole unfiltered list.
    selected_customer = ""
    if client_id:
        chosen = db.session.get(Client, int(client_id)) if client_id.isdigit() else None
        selected_customer = (chosen.stripe_customer_id or "") if chosen else ""

    # Scope = client + month. Drives both the table and the summary cards, so
    # the totals answer "for this client, this month". The status dropdown
    # narrows only the table rows, keeping all three cards meaningful.
    def in_scope(inv):
        if client_id and inv["customer_id"] != selected_customer:
            return False
        if month_start is not None:
            created = inv["created_at"]
            if created is None or not (month_start <= created < month_end):
                return False
        return True

    scoped = [i for i in _decorate(get_stripe_invoices(), client_names) if in_scope(i)]
    rows = [i for i in scoped if not status or i["status"] == status]
    pagination = _Page(rows, page, 20)

    # "Billed" rather than "Invoiced" deliberately. The dashboard's Invoiced
    # means money still to come; this is a ledger of everything raised in the
    # selected scope, paid included, and one word cannot be both.
    total_billed = sum(i["total"] for i in scoped if i["status"] != "void")
    total_paid = sum(i["amount_paid"] for i in scoped)
    total_outstanding = sum(
        i["amount_due"] for i in scoped if i["status"] in ("draft", "open")
    )

    today = date.today()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    return render_template("pm/stripe/invoices/list.html",
        **_account_overview(),
        invoices=pagination.items,
        pagination=pagination,
        status=status,
        client_id=client_id,
        month=month,
        this_month=this_month,
        last_month=last_month,
        clients=clients,
        total_billed=total_billed,
        total_paid=total_paid,
        total_outstanding=total_outstanding,
    )


# ── Generate Invoice ────────────────────────────────────────


@stripe_bp.route("/invoices/new", methods=["GET", "POST"])
@login_required
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

        stripe_invoice, stripe_line_items = create_stripe_invoice(
            client, line_items_data, due_days=due_days, memo=notes
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def api_uninvoiced_entries(client_id):
    start = _parse_date_arg(request.args.get("start"))
    end = _parse_date_arg(request.args.get("end"))
    project_id = request.args.get("project_id", type=int)

    invoiced_ids = db.session.query(InvoiceLineItem.time_entry_id).filter(
        InvoiceLineItem.time_entry_id.isnot(None),
        InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
    ).subquery()

    query = TimeEntry.query.filter(
        TimeEntry.client_id == client_id,
        ~TimeEntry.id.in_(db.session.query(invoiced_ids)),
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
@login_required
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
        # Exclude auto-generated "billable_time" mirror expenses — the underlying
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


# ── Sync All Clients ────────────────────────────────────────


@stripe_bp.route("/clients/sync-all", methods=["POST"])
@login_required
def sync_all_clients():
    try:
        clients = Client.query.filter(Client.stripe_customer_id.is_(None)).all()
        synced = 0
        for client in clients:
            result = create_stripe_customer(client)
            if result:
                synced += 1
        db.session.commit()
        flash(f"Synced {synced} client(s) to Stripe.", "success")
    except Exception as e:
        flash(f"Stripe sync error: {e}", "error")
    return redirect(url_for("stripe.stripe_dashboard"))


# ── Setup Products ──────────────────────────────────────────


@stripe_bp.route("/setup-products", methods=["POST"])
@login_required
def setup_products():
    try:
        import stripe
        # Quick test that the key works
        stripe.Balance.retrieve()
        products = ensure_products_exist()
        if products:
            flash(f"Stripe products configured: {', '.join(products.keys())}", "success")
        else:
            flash("Products returned empty — check Stripe dashboard for errors.", "error")
    except Exception as e:
        flash(f"Stripe error: {type(e).__name__}: {e}", "error")
    return redirect(url_for("stripe.stripe_dashboard"))
