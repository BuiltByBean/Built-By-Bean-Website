import stripe
from datetime import datetime, timezone
from flask import current_app


def init_stripe(app):
    key = app.config.get("STRIPE_SECRET_KEY", "")
    if key:
        stripe.api_key = key


# ── Customer Management ─────────────────────────────────────


def create_stripe_customer(client):
    if not stripe.api_key or client.stripe_customer_id:
        return None
    try:
        customer = stripe.Customer.create(
            name=client.name,
            email=client.email or None,
            phone=client.phone or None,
            metadata={"pm_client_id": str(client.id)},
            address={"line1": client.address} if client.address else None,
        )
        client.stripe_customer_id = customer.id
        return customer
    except Exception as e:
        current_app.logger.error(f"Stripe create customer error: {e}")
        return None


def update_stripe_customer(client):
    if not stripe.api_key or not client.stripe_customer_id:
        return None
    try:
        customer = stripe.Customer.modify(
            client.stripe_customer_id,
            name=client.name,
            email=client.email or None,
            phone=client.phone or None,
            address={"line1": client.address} if client.address else None,
        )
        return customer
    except Exception as e:
        current_app.logger.error(f"Stripe update customer error: {e}")
        return None


def get_stripe_customer(stripe_customer_id):
    if not stripe.api_key or not stripe_customer_id:
        return None
    try:
        return stripe.Customer.retrieve(stripe_customer_id)
    except Exception as e:
        current_app.logger.error(f"Stripe get customer error: {e}")
        return None


# ── Product / Price Management ──────────────────────────────


def ensure_products_exist():
    if not stripe.api_key:
        return {}

    rate_configs = {
        "maintenance": {"name": "Maintenance Work", "rate": 10000},
        "new_feature": {"name": "New Feature Development", "rate": 20000},
    }

    existing = stripe.Product.list(active=True, limit=100)
    existing_map = {}
    for p in existing.data:
        meta = p.metadata.to_dict() if p.metadata and hasattr(p.metadata, 'to_dict') else {}
        rt = meta.get("rate_type") if meta else getattr(p.metadata, "rate_type", None)
        if rt:
            existing_map[rt] = p

    products = {}
    for rate_type, config in rate_configs.items():
        if rate_type in existing_map:
            products[rate_type] = existing_map[rate_type]
        else:
            product = stripe.Product.create(
                name=config["name"],
                metadata={"rate_type": rate_type},
            )
            stripe.Price.create(
                product=product.id,
                currency="usd",
                unit_amount=config["rate"],
            )
            products[rate_type] = product

    return products


def get_or_create_price(rate_type):
    rate_map = {"maintenance": 10000, "new_feature": 20000}
    unit_amount = rate_map.get(rate_type, 20000)

    try:
        prices = stripe.Price.list(active=True, limit=100)
        for price in prices.data:
            if (price.unit_amount == unit_amount and
                    price.currency == "usd" and
                    price.type == "one_time"):
                return price

        products = ensure_products_exist()
        product = products.get(rate_type)
        if not product:
            return None

        price = stripe.Price.create(
            product=product.id,
            currency="usd",
            unit_amount=unit_amount,
        )
        return price

    except Exception as e:
        current_app.logger.error(f"Stripe get/create price error: {e}")
        return None


# ── Invoice Management ──────────────────────────────────────


def create_stripe_invoice(client, line_items, due_days=30, memo=""):
    if not stripe.api_key or not client.stripe_customer_id:
        return None, "Client not synced to Stripe"

    try:
        invoice = stripe.Invoice.create(
            customer=client.stripe_customer_id,
            collection_method="send_invoice",
            days_until_due=due_days,
            auto_advance=False,
            metadata={"pm_client_id": str(client.id)},
        )

        if memo:
            stripe.Invoice.modify(invoice.id, description=memo)

        stripe_line_items = []
        for item in line_items:
            li = stripe.InvoiceItem.create(
                customer=client.stripe_customer_id,
                invoice=invoice.id,
                description=item["description"],
                quantity=item.get("quantity", 1) if isinstance(item, dict) else getattr(item, "quantity", 1),
                unit_amount=int(item["unit_amount"] * 100) if isinstance(item, dict) else int(getattr(item, "unit_amount", 0) * 100),
                currency="usd",
            )
            stripe_line_items.append(li)

        updated_invoice = stripe.Invoice.retrieve(invoice.id)
        return updated_invoice, stripe_line_items

    except Exception as e:
        current_app.logger.error(f"Stripe create invoice error: {e}")
        return None, str(e)


def finalize_and_send_invoice(stripe_invoice_id):
    if not stripe.api_key:
        return None, "Stripe not configured"
    try:
        invoice = stripe.Invoice.finalize_invoice(stripe_invoice_id)
        invoice = stripe.Invoice.send_invoice(stripe_invoice_id)
        return invoice, None
    except Exception as e:
        current_app.logger.error(f"Stripe send invoice error: {e}")
        return None, str(e)


def void_stripe_invoice(stripe_invoice_id):
    if not stripe.api_key:
        return None, "Stripe not configured"
    try:
        invoice = stripe.Invoice.void_invoice(stripe_invoice_id)
        return invoice, None
    except Exception as e:
        current_app.logger.error(f"Stripe void invoice error: {e}")
        return None, str(e)


def sync_invoice_from_stripe(local_invoice):
    if not stripe.api_key or not local_invoice.stripe_invoice_id:
        return False
    try:
        si = stripe.Invoice.retrieve(local_invoice.stripe_invoice_id)
        local_invoice.status = si.status or local_invoice.status
        local_invoice.invoice_number = si.number
        local_invoice.stripe_invoice_url = si.hosted_invoice_url
        local_invoice.stripe_pdf_url = si.invoice_pdf
        local_invoice.subtotal = (si.subtotal or 0) / 100.0
        local_invoice.tax = (si.tax or 0) / 100.0
        local_invoice.total = (si.total or 0) / 100.0
        local_invoice.amount_paid = (si.amount_paid or 0) / 100.0
        local_invoice.amount_due = (si.amount_due or 0) / 100.0
        if si.status == "paid" and not local_invoice.paid_at:
            local_invoice.paid_at = datetime.now(timezone.utc)
        return True
    except Exception as e:
        current_app.logger.error(f"Stripe sync invoice error: {e}")
        return False


# ── Dashboard Data ──────────────────────────────────────────


def get_stripe_balance():
    if not stripe.api_key:
        return None
    try:
        return stripe.Balance.retrieve()
    except Exception as e:
        current_app.logger.error(f"Stripe balance error: {e}")
        return None


def get_recent_payments(limit=10):
    if not stripe.api_key:
        return []
    try:
        charges = stripe.Charge.list(limit=limit)
        return charges.data
    except Exception as e:
        current_app.logger.error(f"Stripe payments error: {e}")
        return []


def get_recent_payouts(limit=5):
    if not stripe.api_key:
        return []
    try:
        payouts = stripe.Payout.list(limit=limit)
        return payouts.data
    except Exception as e:
        current_app.logger.error(f"Stripe payouts error: {e}")
        return []


def get_stripe_invoices_list(status=None, limit=20):
    if not stripe.api_key:
        return []
    try:
        params = {"limit": limit}
        if status:
            params["status"] = status
        invoices = stripe.Invoice.list(**params)
        return invoices.data
    except Exception as e:
        current_app.logger.error(f"Stripe list invoices error: {e}")
        return []


# ── Webhook Processing ──────────────────────────────────────


def handle_webhook_event(payload, sig_header):
    webhook_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return None, "Webhook secret not configured"
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event, None
    except stripe.SignatureVerificationError:
        return None, "Invalid signature"
    except ValueError:
        return None, "Invalid payload"


def process_invoice_event(event):
    from models import db, Invoice, StripeWebhookLog

    event_type = event["type"]
    invoice_data = event["data"]["object"]
    stripe_invoice_id = invoice_data["id"]

    existing_log = StripeWebhookLog.query.filter_by(event_id=event["id"]).first()
    if existing_log:
        return True

    log = StripeWebhookLog(
        event_id=event["id"],
        event_type=event_type,
        processed=False,
    )
    db.session.add(log)

    local_invoice = Invoice.query.filter_by(stripe_invoice_id=stripe_invoice_id).first()
    if not local_invoice:
        log.processed = True
        log.error_message = "No matching local invoice"
        db.session.commit()
        return True

    # Use getattr for Stripe SDK v15+ StripeObject compatibility
    if event_type == "invoice.finalized":
        local_invoice.status = "open"
        local_invoice.invoice_number = getattr(invoice_data, "number", None)
        local_invoice.stripe_invoice_url = getattr(invoice_data, "hosted_invoice_url", None)
        local_invoice.stripe_pdf_url = getattr(invoice_data, "invoice_pdf", None)

    elif event_type == "invoice.sent":
        local_invoice.sent_at = datetime.now(timezone.utc)

    elif event_type == "invoice.paid":
        local_invoice.status = "paid"
        local_invoice.paid_at = datetime.now(timezone.utc)
        local_invoice.amount_paid = (getattr(invoice_data, "amount_paid", 0) or 0) / 100.0

    elif event_type == "invoice.payment_failed":
        local_invoice.status = "open"

    elif event_type == "invoice.voided":
        local_invoice.status = "void"

    elif event_type == "invoice.marked_uncollectible":
        local_invoice.status = "uncollectible"

    elif event_type == "invoice.payment_succeeded":
        local_invoice.status = "paid"
        local_invoice.paid_at = datetime.now(timezone.utc)
        local_invoice.amount_paid = (getattr(invoice_data, "amount_paid", 0) or 0) / 100.0

    log.processed = True
    db.session.commit()
    return True
