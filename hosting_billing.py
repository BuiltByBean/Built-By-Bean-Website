"""The hosting fee agreed against the hosting fee Stripe actually bills.

docs/automation_gaps.md item 10. Project.hosting_fee comes from the contract
and nothing compared it with the subscription: a signed fee update never
changed what Stripe charged, and a project with an agreed fee and no
subscription at all was agreed money never billed.

Hosting money belongs to a client, not a project (the page already says so
of what was collected), so the comparison is per client: the sum of its
priced projects' monthly fees against the sum of its hosting subscription
items, both as a month. A subscription item is hosting when its product's
name (or the price's nickname) says hosting, the same word the invoices are
read by (stripe_service.HOSTING_LINE).

Reading Stripe is a network call, and the Hosting badge is built on every
page, so the badge only ever reads `snapshot()`, which never waits: it
answers from the last read and starts a fresh one in the background when that
is stale. The Hosting page itself reads synchronously.

`change` is the one press: the subscription's single hosting item moved to
the agreed fee from the next cycle, no proration. The page asks first, the
same way "Tax the subscription" does, because it changes what a client pays.
"""
import threading
import time

BILLING_STATUSES = ("active", "trialing", "past_due", "unpaid", "incomplete")
STALE_SECONDS = 1800
INTERVAL_MONTHS = {"month": 1, "year": 12, "week": 12 / 52, "day": 12 / 365}

_CACHE = {"at": 0.0, "data": None, "busy": False, "ended": {}}
_PRODUCTS = {}


def _stripe():
    import stripe
    return stripe if stripe.api_key else None


def _product_name(stripe, product):
    if product is None:
        return ""
    if not isinstance(product, str):
        return getattr(product, "name", "") or ""
    if product not in _PRODUCTS:
        try:
            _PRODUCTS[product] = getattr(stripe.Product.retrieve(product), "name", "") or ""
        except Exception:  # noqa: BLE001
            _PRODUCTS[product] = ""
    return _PRODUCTS[product]


def item_rows(stripe, subscriptions):
    """{customer_id: [hosting item]} from Stripe's subscriptions."""
    from stripe_service import HOSTING_LINE
    out = {}
    ended = {}
    for sub in subscriptions:
        customer = getattr(sub, "customer", None)
        customer = customer if isinstance(customer, str) else getattr(customer, "id", None)
        if getattr(sub, "status", None) not in BILLING_STATUSES:
            # A hosting subscription that has stopped is the answer to "why
            # is nothing billing them": both of Michael's $50 subscriptions
            # were canceled on 2026-10-28 and the page said only "no hosting
            # subscription", which read as the board not seeing them.
            if getattr(sub, "status", None) == "canceled" and _is_hosting(stripe, sub, HOSTING_LINE):
                when = getattr(sub, "ended_at", None) or getattr(sub, "canceled_at", None)
                if when and when > (ended.get(customer) or {}).get("at", 0):
                    details = getattr(sub, "cancellation_details", None)
                    ended[customer] = {"at": when, "reason": getattr(details, "reason", None) if details else None}
            continue
        for item in sub["items"].data:
            row = _hosting_item(stripe, getattr(item, "price", None), getattr(item, "quantity", 1), HOSTING_LINE)
            if row:
                row.update(subscription_id=getattr(sub, "id", None), item_id=getattr(item, "id", None),
                           status=sub.status)
                out.setdefault(customer, []).append(row)
    _CACHE["ended"] = ended
    return out


def _hosting_item(stripe, price, quantity, word):
    """One recurring hosting price as a row, or None when it is not hosting."""
    recurring = getattr(price, "recurring", None)
    if price is None or isinstance(price, str) or recurring is None:
        return None
    product = getattr(price, "product", None)
    name = f"{_product_name(stripe, product)} {getattr(price, 'nickname', '') or ''}"
    if word not in name.lower():
        return None
    interval = getattr(recurring, "interval", "month") or "month"
    count = getattr(recurring, "interval_count", 1) or 1
    months = INTERVAL_MONTHS.get(interval, 1) * count
    cents = (getattr(price, "unit_amount", 0) or 0) * (quantity or 1)
    return {"subscription_id": None, "item_id": None, "status": None,
            "amount": cents / 100.0, "monthly": round(cents / 100.0 / months, 2),
            "interval": interval, "interval_count": count,
            "product": product if isinstance(product, str) else getattr(product, "id", None),
            "currency": getattr(price, "currency", "usd") or "usd"}


def schedule_rows(stripe, schedules, out):
    """Add each hosting price a schedule that has not started yet will bill.

    Michael, 2026-11-05: Kenali's new hosting starts on the 11th, set up as a
    schedule, and until the first day there is no subscription at all, so the
    page read "no hosting subscription in Stripe" about a client who is set up
    to be billed. A row from a schedule carries `starts` and no subscription
    id, so nothing offers to change it: there is nothing to modify yet.
    """
    from datetime import datetime, timezone
    from stripe_service import HOSTING_LINE
    for sched in schedules:
        if getattr(sched, "status", None) != "not_started":
            continue
        customer = getattr(sched, "customer", None)
        customer = customer if isinstance(customer, str) else getattr(customer, "id", None)
        phases = getattr(sched, "phases", None) or []
        if not phases:
            continue
        first = phases[0]
        start = getattr(first, "start_date", None)
        # first["items"], never first.items: a Stripe object is a dict, and
        # .items is the dict's own method.
        try:
            items = first["items"] or []
        except (KeyError, TypeError):
            items = []
        for item in items:
            row = _hosting_item(stripe, getattr(item, "price", None), getattr(item, "quantity", 1), HOSTING_LINE)
            if row:
                row.update(status="scheduled", schedule_id=getattr(sched, "id", None),
                           starts=datetime.fromtimestamp(start, timezone.utc).date() if start else None)
                out.setdefault(customer, []).append(row)
    return out


def _is_hosting(stripe, sub, word):
    for item in sub["items"].data:
        price = getattr(item, "price", None)
        if price is None or getattr(price, "recurring", None) is None:
            continue
        name = f"{_product_name(stripe, getattr(price, 'product', None))} {getattr(price, 'nickname', '') or ''}"
        if word in name.lower():
            return True
    return False


def ended_for(customer):
    """The newest canceled hosting subscription for a customer that has no
    live one: {"on": date, "after_failed_payment": bool}, or None."""
    from datetime import datetime, timezone
    row = _CACHE.get("ended", {}).get(customer or "")
    if not row:
        return None
    return {"on": datetime.fromtimestamp(row["at"], timezone.utc).date(),
            "after_failed_payment": row["reason"] == "payment_failed"}


def read():
    """{customer_id: [hosting item]} now, or None when Stripe is not set up."""
    stripe = _stripe()
    if stripe is None:
        return None
    subs = list(stripe.Subscription.list(status="all", limit=100).auto_paging_iter())
    data = item_rows(stripe, subs)
    schedules = list(stripe.SubscriptionSchedule.list(
        limit=100, expand=["data.phases.items.price"]).auto_paging_iter())
    schedule_rows(stripe, schedules, data)
    _CACHE.update(at=time.monotonic(), data=data)
    return data


def current(ttl=300):
    """The page's read: fresh within ttl, else read now. None on failure."""
    if _CACHE["data"] is not None and time.monotonic() - _CACHE["at"] < ttl:
        return _CACHE["data"]
    try:
        return read()
    except Exception:  # noqa: BLE001 - Stripe down is a page without the comparison
        return _CACHE["data"]


def snapshot(app=None):
    """The badge's read: never waits. Starts a background read when stale."""
    stale = _CACHE["data"] is None or time.monotonic() - _CACHE["at"] > STALE_SECONDS
    if stale and app is not None and not _CACHE["busy"] and _stripe() is not None:
        _CACHE["busy"] = True

        def go():
            try:
                with app.app_context():
                    read()
            except Exception:  # noqa: BLE001
                pass
            finally:
                _CACHE["busy"] = False
        threading.Thread(target=go, daemon=True).start()
    return _CACHE["data"]


def forget():
    _CACHE["at"] = 0.0


def compare(client, agreed_monthly, items):
    """{state, billed, agreed, items} for one client. state is "ok",
    "unbilled" (an agreed fee and no hosting subscription) or "differs"."""
    billed = round(sum(i["monthly"] for i in items or []), 2)
    agreed = round(agreed_monthly or 0.0, 2)
    if agreed <= 0:
        state = "ok"
    elif not items:
        state = "unbilled"
    elif abs(billed - agreed) >= 0.01:
        state = "differs"
    else:
        state = "ok"
    return {"state": state, "billed": billed, "agreed": agreed, "items": items or [],
            "starts": min((i["starts"] for i in items or [] if i.get("starts")), default=None),
            "changeable": state == "differs" and len(items or []) == 1
            and bool((items or [{}])[0].get("subscription_id"))}


def agreed_by_client(projects):
    out = {}
    for p in projects:
        if p.hosting_fee is None:
            continue
        out[p.client_id] = out.get(p.client_id, 0.0) + (p.monthly_hosting_fee or 0.0)
    return out


def by_client(projects, data):
    """{client_id: compare(...)} for every client with a priced project, or
    {} when there is no Stripe answer to compare against."""
    if data is None:
        return {}
    clients = {p.client_id: p.client for p in projects if p.hosting_fee is not None}
    out = {}
    for client_id, agreed in agreed_by_client(projects).items():
        client = clients.get(client_id)
        customer = (client.stripe_customer_id if client else None) or ""
        items = data.get(customer, [])
        out[client_id] = compare(client, agreed, items)
        if out[client_id]["state"] == "unbilled":
            out[client_id]["ended"] = ended_for(customer)
    return out


def change(item, monthly):
    """Move one subscription item to `monthly` a month, from the next cycle.
    Returns an error string or None."""
    stripe = _stripe()
    if stripe is None:
        return "Stripe is not set up."
    months = INTERVAL_MONTHS.get(item["interval"], 1) * (item["interval_count"] or 1)
    try:
        stripe.Subscription.modify(
            item["subscription_id"],
            items=[{"id": item["item_id"], "price_data": {
                "currency": item["currency"], "product": item["product"],
                "unit_amount": int(round(monthly * months * 100)),
                "recurring": {"interval": item["interval"],
                              "interval_count": item["interval_count"] or 1}}}],
            proration_behavior="none")
    except Exception as err:  # noqa: BLE001
        return str(err)[:300]
    forget()
    return None
