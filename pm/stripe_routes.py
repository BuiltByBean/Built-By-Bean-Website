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
    process_invoice_event, ensure_products_exist,
)

stripe_bp = Blueprint("stripe", __name__, url_prefix="/admin/pm/stripe")


# ── Stripe Dashboard ────────────────────────────────────────


@stripe_bp.route("/")
@login_required
def stripe_dashboard():
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

        raw_payments = get_recent_payments(limit=10)
        for p in raw_payments:
            payments.append({
                "name": (p.billing_details.name if p.billing_details else None) or "Unknown",
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

    open_invoices = Invoice.query.filter(Invoice.status.in_(["draft", "open"])).order_by(
        Invoice.created_at.desc()
    ).all()

    paid_invoices = Invoice.query.filter_by(status="paid").order_by(
        Invoice.paid_at.desc()
    ).limit(10).all()

    total_outstanding = sum(inv.amount_due for inv in open_invoices)

    return render_template("pm/stripe/dashboard.html",
        available_balance=available,
        pending_balance=pending,
        payments=payments,
        payouts=payouts,
        open_invoices=open_invoices,
        paid_invoices=paid_invoices,
        total_outstanding=total_outstanding,
    )


# ── Invoice List ────────────────────────────────────────────


@stripe_bp.route("/invoices")
@login_required
def invoices_list():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status", "")
    client_id = request.args.get("client_id", "", type=str)

    query = Invoice.query
    if status:
        query = query.filter(Invoice.status == status)
    if client_id:
        query = query.filter(Invoice.client_id == int(client_id))

    query = query.order_by(Invoice.created_at.desc())
    pagination = query.paginate(page=page, per_page=20, error_out=False)

    clients = Client.query.order_by(Client.name).all()

    total_invoiced = db.session.query(db.func.sum(Invoice.total)).scalar() or 0
    total_paid = db.session.query(db.func.sum(Invoice.amount_paid)).scalar() or 0
    total_outstanding = db.session.query(
        db.func.sum(Invoice.amount_due)
    ).filter(Invoice.status.in_(["draft", "open"])).scalar() or 0

    return render_template("pm/stripe/invoices/list.html",
        invoices=pagination.items,
        pagination=pagination,
        status=status,
        client_id=client_id,
        clients=clients,
        total_invoiced=total_invoiced,
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
                desc = f"{entry.rate_type.replace('_', ' ').title()} - {entry.description or 'Development work'} ({entry.date.strftime('%b %d')})"
                line_items_data.append({
                    "description": desc,
                    "quantity": entry.hours,
                    "unit_amount": entry.rate,
                })

        if expense_ids:
            expenses = Expense.query.filter(Expense.id.in_(expense_ids)).all()
            for expense in expenses:
                desc = f"Expense: {expense.description or expense.category} ({expense.date.strftime('%b %d')})"
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


# ── API: Uninvoiced Time Entries ────────────────────────────


@stripe_bp.route("/api/uninvoiced-entries/<int:client_id>")
@login_required
def api_uninvoiced_entries(client_id):
    invoiced_ids = db.session.query(InvoiceLineItem.time_entry_id).filter(
        InvoiceLineItem.time_entry_id.isnot(None),
        InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
    ).subquery()

    entries = TimeEntry.query.filter(
        TimeEntry.client_id == client_id,
        ~TimeEntry.id.in_(db.session.query(invoiced_ids)),
    ).order_by(TimeEntry.date.desc()).all()

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
    invoiced_ids = db.session.query(InvoiceLineItem.expense_id).filter(
        InvoiceLineItem.expense_id.isnot(None),
        InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
    ).subquery()

    expenses = Expense.query.filter(
        Expense.client_id == client_id,
        ~Expense.id.in_(db.session.query(invoiced_ids)),
    ).order_by(Expense.date.desc()).all()

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
