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
        # The customer comes back expanded, because the only name a charge
        # carries on its own is the cardholder name off the payment method,
        # which an invoice paid against a saved card does not have. One
        # expanded list request beats a customer lookup per row.
        charges = stripe.Charge.list(limit=limit, expand=["data.customer"])
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


# What a Stripe invoice status means for money that has actually been asked
# for. `draft` was never sent, so nobody owes it. `void` was cancelled after
# the fact, so nobody owes it any more. `uncollectible` was issued and then
# written off, which still means it was invoiced, so it counts as billed and
# not as outstanding.
ISSUED_STATUSES = ("open", "paid", "uncollectible")

_invoice_cache = {"ts": 0, "data": None}


def _empty_invoice_totals():
    """One bucket per state an invoice's money can be in.

    Deliberately no "invoiced" key. The dashboard uses that word for something
    narrower, money billed or committed and not yet paid, and a second meaning
    for the same word in the layer underneath it is how the two quietly drift
    apart. Callers add the buckets they mean.
    """
    return {
        "paid": 0.0,          # collected
        "open": 0.0,          # sent, still owed
        "draft": 0.0,         # written, possibly dated, not sent yet
        "open_count": 0,      # how many invoices are sitting sent and unpaid
        "paid_by_customer": {},
        "open_by_customer": {},
        "draft_by_customer": {},
    }


def get_stripe_invoices(ttl=300):
    """Every Stripe invoice, flattened into plain dicts, newest first.

    The single source for everything invoice-shaped on the admin: the totals,
    the dashboard's two lists and the invoice table all read this, so a page
    load makes one invoice request instead of one per panel.

    Plain dicts rather than StripeObjects on purpose. A StripeObject raises on
    `.get`, which templates and ordinary Python both reach for, and it keeps a
    live client attached to something that only needs to be read.

    The customer is expanded so a name is available without a second lookup.
    A deleted customer still expands, to a stub with no name, so `deleted` is
    checked before the field is trusted.

    Cached for `ttl` seconds, falling back to the last good list on a Stripe
    error, because an empty invoice table is a far more convincing lie than a
    slightly stale one.
    """
    import time
    from datetime import datetime, timezone

    if not stripe.api_key:
        return []

    now = time.time()
    if _invoice_cache["data"] is not None and (now - _invoice_cache["ts"] < ttl):
        return _invoice_cache["data"]

    def _at(value):
        return datetime.fromtimestamp(value, timezone.utc) if value else None

    rows = []
    try:
        for inv in stripe.Invoice.list(limit=100, expand=["data.customer"]).auto_paging_iter():
            customer = getattr(inv, "customer", None)
            if isinstance(customer, str):
                customer_id, customer_name = customer, None
            elif customer is None:
                customer_id, customer_name = None, None
            else:
                customer_id = getattr(customer, "id", None)
                customer_name = None if getattr(customer, "deleted", False) else (
                    getattr(customer, "name", None) or getattr(customer, "email", None)
                )

            transitions = getattr(inv, "status_transitions", None)
            invoice_id = getattr(inv, "id", None)
            rows.append({
                "id": invoice_id,
                "number": getattr(inv, "number", None),
                "status": getattr(inv, "status", None),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "total": (getattr(inv, "total", 0) or 0) / 100.0,
                "amount_due": (getattr(inv, "amount_due", 0) or 0) / 100.0,
                "amount_paid": (getattr(inv, "amount_paid", 0) or 0) / 100.0,
                "created_at": _at(getattr(inv, "created", None)),
                "due_date": _at(getattr(inv, "due_date", None)),
                "paid_at": _at(getattr(transitions, "paid_at", None) if transitions else None),
                "description": getattr(inv, "description", None),
                # Where the customer pays. Absent on a draft, which has not
                # been finalised and so has no public page yet.
                "hosted_url": getattr(inv, "hosted_invoice_url", None),
                "pdf_url": getattr(inv, "invoice_pdf", None),
                # Where *we* go to act on it. Exists for every status, drafts
                # included, which is why the lists link here and not to the
                # hosted page.
                "admin_url": f"https://dashboard.stripe.com/invoices/{invoice_id}" if invoice_id else None,
            })
    except Exception as e:
        current_app.logger.error(f"Stripe invoice list error: {e}")
        return _invoice_cache["data"] or []

    epoch = datetime.fromtimestamp(0, timezone.utc)
    rows.sort(key=lambda r: r["created_at"] or epoch, reverse=True)
    _invoice_cache.update({"ts": now, "data": rows})
    return rows


def get_stripe_invoice_totals(ttl=300):
    """Every Stripe invoice, bucketed by what state its money is in.

    Derived from `get_stripe_invoices` rather than fetching again, so the
    numbers and the lists below them can never disagree about what is in
    Stripe.

    Amounts are read per bucket rather than all from one field, because they
    answer different questions. `paid` uses `amount_paid` and `open` uses
    `amount_due`, so a part-paid invoice contributes only what has actually
    landed to one and only what is still owed to the other. `draft` uses the
    invoice total, since nothing has been paid against it by definition.
    """
    out = _empty_invoice_totals()
    for inv in get_stripe_invoices(ttl=ttl):
        status, customer = inv["status"], inv["customer_id"]

        if status == "draft":
            out["draft"] += inv["total"]
            if customer:
                out["draft_by_customer"][customer] = out["draft_by_customer"].get(customer, 0.0) + inv["total"]
            continue
        if status not in ISSUED_STATUSES:
            continue

        if status == "paid":
            out["paid"] += inv["amount_paid"]
            if customer:
                out["paid_by_customer"][customer] = out["paid_by_customer"].get(customer, 0.0) + inv["amount_paid"]
        elif status == "open":
            out["open"] += inv["amount_due"]
            out["open_count"] += 1
            if customer:
                out["open_by_customer"][customer] = out["open_by_customer"].get(customer, 0.0) + inv["amount_due"]
    return out


def get_overdue_invoices(ttl=300):
    """Invoices that were sent, are still owed, and are past their due date.

    Read off the same cached list everything else uses, so this costs no extra
    Stripe call and can never disagree with the totals above it.

    An open invoice with no due date is not overdue. Stripe leaves the field
    empty on a subscription charge and on anything created without one, and
    calling those late would mean the panel cried wolf on the day it was
    raised — which is how a panel stops being read.

    Oldest first, because that is the order they should be chased in.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    out = []
    for inv in get_stripe_invoices(ttl=ttl):
        if inv["status"] != "open" or inv["amount_due"] <= 0 or not inv["due_date"]:
            continue
        days = (now - inv["due_date"]).days
        if days > 0:
            out.append(dict(inv, days_overdue=days))
    out.sort(key=lambda r: r["days_overdue"], reverse=True)
    return out


_stalled_cache = {"ts": 0, "data": None}

# Stripe tried to collect and could not. `incomplete` is the first charge
# failing, `past_due` a renewal failing, `unpaid` the end of the retry
# schedule. All three mean the same thing here: a plan that has stopped
# turning into money and needs a person.
STALLED_STATUSES = ("past_due", "unpaid", "incomplete")


def get_stalled_subscriptions(ttl=300):
    """Recurring plans Stripe has stopped being able to collect on.

    Its own call rather than a flag on `_recurring_plan`, which exists to
    project revenue forward and treats a past_due subscription as still
    billing — correct for a forecast, wrong for a list of things to go and fix.
    """
    import time
    from datetime import datetime, timezone

    if not stripe.api_key:
        return []
    now = time.time()
    if _stalled_cache["data"] is not None and (now - _stalled_cache["ts"] < ttl):
        return _stalled_cache["data"]

    rows = []
    try:
        for status in STALLED_STATUSES:
            for sub in stripe.Subscription.list(
                status=status, limit=100, expand=["data.customer"]
            ).auto_paging_iter():
                customer = getattr(sub, "customer", None)
                name = None
                if customer is not None and not isinstance(customer, str):
                    name = None if getattr(customer, "deleted", False) else (
                        getattr(customer, "name", None) or getattr(customer, "email", None)
                    )
                amount = 0.0
                interval = None
                for item in sub["items"].data:
                    price = getattr(item, "price", None)
                    amount += ((getattr(price, "unit_amount", 0) or 0) / 100.0) * (
                        getattr(item, "quantity", 1) or 1)
                    recurring = getattr(price, "recurring", None) if price else None
                    interval = getattr(recurring, "interval", None) if recurring else interval
                sub_id = getattr(sub, "id", None)
                rows.append({
                    "id": sub_id,
                    "customer_name": name,
                    "customer_id": getattr(customer, "id", None) if not isinstance(customer, str) else customer,
                    "status": status,
                    "amount": amount,
                    "interval": interval,
                    "collection_method": getattr(sub, "collection_method", None),
                    "admin_url": f"https://dashboard.stripe.com/subscriptions/{sub_id}" if sub_id else None,
                })
    except Exception as e:
        current_app.logger.error(f"Stripe stalled subscription error: {e}")
        return _stalled_cache["data"] or []

    _stalled_cache.update({"ts": now, "data": rows})
    return rows


_recurring_cache = {"ts": 0, "data": None}

# A recurring price can be billed on any of these; only the two that convert
# cleanly to whole months are projected. A weekly or daily plan would need a
# different cursor and there are none.
_MONTHS_PER_INTERVAL = {"month": 1, "year": 12}


def _recurring_plan(ttl=300):
    """Every recurring charge Stripe is going to raise, as plain tuples.

    (customer_id, amount_dollars, first_charge_at, months_between, stop_before)

    `stop_before` is None for a running subscription, which bills until someone
    cancels it, and the phase end for a scheduled one, which stops when its
    phase does. Collapsing both into one shape lets the caller project them
    with a single loop.

    Two sources, because they are two different objects. A subscription that is
    already running is a Subscription; one that starts next month is a
    SubscriptionSchedule with no Subscription behind it yet, and listing only
    the first would silently miss it.

    Note `current_period_end` is read off the subscription *item*. Stripe moved
    it there, and the field on the subscription itself now comes back empty.
    """
    import time
    from datetime import datetime, timezone

    if not stripe.api_key:
        return []
    now = time.time()
    if _recurring_cache["data"] is not None and (now - _recurring_cache["ts"] < ttl):
        return _recurring_cache["data"]

    def _at(value):
        return datetime.fromtimestamp(value, timezone.utc) if value else None

    plan = []
    try:
        for sub in stripe.Subscription.list(status="all", limit=100).auto_paging_iter():
            if getattr(sub, "status", None) not in ("active", "trialing", "past_due"):
                continue
            customer = getattr(sub, "customer", None)
            for item in sub["items"].data:
                price = getattr(item, "price", None)
                recurring = getattr(price, "recurring", None) if price else None
                months = _MONTHS_PER_INTERVAL.get(getattr(recurring, "interval", None), 0)
                months *= getattr(recurring, "interval_count", 1) or 1 if recurring else 0
                starts = _at(getattr(item, "current_period_end", None)
                             or getattr(sub, "current_period_end", None))
                amount = ((getattr(price, "unit_amount", 0) or 0) / 100.0) * (getattr(item, "quantity", 1) or 1)
                if months and starts and amount:
                    plan.append((customer, amount, starts, months, None))

        for sched in stripe.SubscriptionSchedule.list(limit=100).auto_paging_iter():
            if getattr(sched, "status", None) != "not_started":
                continue  # a running schedule already shows up as a Subscription
            customer = getattr(sched, "customer", None)
            for phase in getattr(sched, "phases", None) or []:
                starts, ends = _at(phase["start_date"]), _at(phase["end_date"])
                for item in phase["items"]:
                    price = item["price"]
                    if isinstance(price, str):
                        price = stripe.Price.retrieve(price)
                    recurring = getattr(price, "recurring", None)
                    months = _MONTHS_PER_INTERVAL.get(getattr(recurring, "interval", None), 0)
                    months *= getattr(recurring, "interval_count", 1) or 1 if recurring else 0
                    amount = ((getattr(price, "unit_amount", 0) or 0) / 100.0) * (getattr(item, "quantity", None) or 1)
                    if months and starts and amount:
                        plan.append((customer, amount, starts, months, ends))
    except Exception as e:
        current_app.logger.error(f"Stripe recurring plan error: {e}")
        return _recurring_cache["data"] or []

    _recurring_cache.update({"ts": now, "data": plan})
    return plan


def get_scheduled_subscription_revenue(customer_ids, until=None, ttl=300):
    """What the recurring plans will bill between now and `until`.

    `customer_ids` is an allowlist, and it is not optional by accident: this
    figure sits on a client dashboard, so a subscriber who is not a client has
    no business inflating it.

    Defaults to the end of the current calendar year. Counts whole billing
    cycles only, so a plan whose next charge falls after the horizon
    contributes nothing rather than a fraction.

    Returns (total_dollars, {customer_id: dollars}).
    """
    from datetime import datetime, timezone
    from dateutil.relativedelta import relativedelta

    now = datetime.now(timezone.utc)
    if until is None:
        until = datetime(now.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    total = 0.0
    by_customer = {}
    for customer, amount, first, months, stop_before in _recurring_plan(ttl=ttl):
        if customer not in customer_ids:
            continue
        cursor = max(first, now)
        while cursor <= until and (stop_before is None or cursor < stop_before):
            total += amount
            by_customer[customer] = by_customer.get(customer, 0.0) + amount
            cursor += relativedelta(months=months)
    return total, by_customer


_income_cache = {"ts": 0, "data": None}

# The balance transaction types that are money in or money back out to a
# customer. Payouts, holds and topups are the bank moving what you already
# earned, and counting them as income would book the same money twice.
_INCOME_TYPES = ("charge", "payment", "refund", "payment_refund", "adjustment")


def get_stripe_income_transactions(ttl=300):
    """Every payment in and refund out, with what Stripe kept, newest last.

    Read off balance transactions rather than charges because they carry gross,
    fee and net on the same object already reconciled. A refund arrives as a
    negative, which is what makes the totals here agree with the bank rather
    than with the invoices.

    Cached, and falls back to the last good list on an error, for the same
    reason as everything else: an empty tax page is a more convincing lie than
    a slightly stale one.
    """
    import time
    from datetime import date as _date, datetime, timezone

    if not stripe.api_key:
        return []
    now = time.time()
    if _income_cache["data"] is not None and (now - _income_cache["ts"] < ttl):
        return _income_cache["data"]

    rows = []
    try:
        for txn in stripe.BalanceTransaction.list(limit=100, expand=["data.source"]).auto_paging_iter():
            kind = getattr(txn, "type", None)
            if kind not in _INCOME_TYPES:
                continue
            source = getattr(txn, "source", None)
            customer = getattr(source, "customer", None) if (source is not None and not isinstance(source, str)) else None
            if customer is not None and not isinstance(customer, str):
                customer = getattr(customer, "id", None)
            created = getattr(txn, "created", None)
            rows.append({
                "id": getattr(txn, "id", None),
                "date": datetime.fromtimestamp(created, timezone.utc).date() if created else None,
                "type": kind,
                "gross": (getattr(txn, "amount", 0) or 0) / 100.0,
                "fee": (getattr(txn, "fee", 0) or 0) / 100.0,
                "net": (getattr(txn, "net", 0) or 0) / 100.0,
                "customer_id": customer,
                "description": getattr(txn, "description", None) or "",
            })
    except Exception as e:
        current_app.logger.error(f"Stripe income transactions error: {e}")
        return _income_cache["data"] or []

    rows.sort(key=lambda r: (r["date"] or _date.min))
    _income_cache.update({"ts": now, "data": rows})
    return rows


def get_stripe_revenue(ttl=300):
    """Actual paid revenue pulled live from Stripe.

    Returns (total_paid_dollars, {stripe_customer_id: paid_dollars}), which is
    the shape the dashboard has always taken. The work now happens in
    `get_stripe_invoice_totals`, which reads the other statuses in the same
    pass.
    """
    totals = get_stripe_invoice_totals(ttl=ttl)
    return totals["paid"], totals["paid_by_customer"]


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
