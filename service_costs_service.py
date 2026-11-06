import json
import re
import os
import requests
import boto3
from datetime import datetime, timezone, date, timedelta
from flask import current_app

from models import db, ServiceProvider, ServiceMapping, ServiceCostEntry, Expense, ProviderInvoice


def _get_credentials(provider):
    if not provider.credentials_json:
        return {}
    try:
        return json.loads(provider.credentials_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _find_mapping(provider_id, resource_identifier):
    return ServiceMapping.query.filter_by(
        provider_id=provider_id,
        resource_identifier=resource_identifier,
        is_active=True,
    ).all()


def _existing_entry(provider_id, resource_id, period_start, period_end, mapping_id=None):
    return ServiceCostEntry.query.filter_by(
        provider_id=provider_id,
        resource_identifier=resource_id,
        period_start=period_start,
        period_end=period_end,
        mapping_id=mapping_id,
    ).first()


# Vendors paid by topping up a balance in advance. Twilio is the one: a $20
# recharge leaves the bank, and the month's usage is drawn from the balance in
# amounts that never add up to any one charge. So the bank line is the expense
# (bank_feed.is_prepaid) and the usage rows only say which client used what:
# they are recorded and attributed and book no expense, or the same money would
# count twice, once as the top-up and once as the usage it paid for.
PREPAID_PROVIDERS = {"twilio"}


# Only the bank line makes an expense (docs/finances_plan.md item 5, Michael,
# 2026-11-04). A vendor's report splits that line across projects and clients
# (bank_feed.split) and books nothing of its own. Stripe is the one exception:
# it takes its fees out of the balance it holds before paying out, so they
# never cross a bank and the Stripe balance is the account they come from.
BALANCE_PROVIDERS = {"stripe"}

# An expense a vendor sync wrote before that day keeps being corrected by the
# sync (a month to date figure grows) until its bank line takes it over.
# Periods starting on or after this get none.
SPLIT_FROM = date(2026, 12, 1)


def writes_expenses(provider):
    """Whether this provider's cost entries become Expenses: only Stripe's
    fees, on an account that is this business's own. The sync and the
    ownership press on the providers page both ask this, never one half of it."""
    return provider.is_ours and provider.name in BALANCE_PROVIDERS


def _keeps_old_expense(provider, entry):
    """An expense the old sync wrote for this row, that no bank line has
    taken over yet: still corrected in place, so a month to date figure
    does not freeze before its charge arrives. Never a new one."""
    expense = entry.expense
    return (provider.is_ours and provider.name not in PREPAID_PROVIDERS
            and expense is not None and expense.bank_line_id is None
            and entry.period_start < SPLIT_FROM)


def _month_bounds(when=None):
    """The calendar month `when` falls in, first and last day inclusive.

    Every sync used to end its period at today. A daily run therefore invented
    a new period each day, each holding the month to date, and because the
    period was part of the key nothing ever matched what yesterday wrote. The
    same spend booked itself over and over. A stable month is the single thing
    that makes running this on a schedule safe.
    """
    when = when or date.today()
    first = when.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _drop_expense(cost_entry):
    """Unbook a cost entry, leaving the entry itself alone.

    Called when the account turns out to belong to a client. The entry stays,
    because what their app costs to run is worth knowing; the expense goes,
    because this business did not spend it. A share of a bank line stays: the
    bank says the money left, and the line's next split decides where.
    """
    expense = cost_entry.expense
    cost_entry.expense_id = None
    if expense is not None:
        if expense.bank_line_id:
            expense.cost_entry_id = None
        else:
            db.session.delete(expense)
    db.session.flush()


def discard_entry(entry):
    """Remove a cost entry and the expense it created.

    An expense that has been put on an invoice is left alone and merely
    detached. Deleting it would silently change an invoice that has already
    gone to a client, which is a worse outcome than an orphan row.
    """
    expense = entry.expense
    if expense is not None and not expense.invoice_line_items and not expense.bank_line_id:
        db.session.delete(expense)
    Expense.query.filter_by(cost_entry_id=entry.id).update({"cost_entry_id": None})
    entry.expense_id = None
    db.session.delete(entry)


def prune_stale_allocations(provider, resource_id, p_start, p_end):
    """Drop rows for an allocation that no longer exists.

    mapping_id is part of the cost entry's unique key, so a resource that was
    unallocated when it was first entered keeps that no-mapping row forever.
    Map it to a client afterwards and the next save writes a second row
    beside the first rather than replacing it, and the month reads double.
    Same story when a mapping is deleted and its row is left behind.
    """
    valid = {m.id for m in _find_mapping(provider.id, resource_id)}
    for e in ServiceCostEntry.query.filter_by(
        provider_id=provider.id,
        resource_identifier=resource_id,
        period_start=p_start,
        period_end=p_end,
    ).all():
        if e.mapping_id in valid:
            continue
        # Nothing to prune when the resource has no mappings at all: the
        # no-mapping row is then the correct and only row.
        if valid or e.mapping_id is not None:
            discard_entry(e)


def _sync_expense(cost_entry, mapping, default_client_id=None):
    """Keep an Expense in step with a cost entry, creating one if absent.

    An unallocated cost gets an expense too, carrying no client. It is money
    the business spent whether or not anybody has said which client it was
    for, and refusing to book it is why the ledger contained nothing but hand
    typed rows while four vendors were syncing happily.

    Updates rather than inserts on a second run, because the entry it mirrors
    is itself updated in place as the month accumulates.

    The DATE is not the period. A cost entry's period is a key and has to be
    the whole calendar month, or a nightly sync writes a new row every night
    instead of correcting the one it wrote before. An expense's date is a fact
    about when money went out, and the end of a month in progress has not
    happened yet: dating September's accruing charges Sep 30 put future dates
    on the ledger while it was the 16th. So the date is the period's end or
    today, whichever came first. It still lands in the month it belongs to,
    and it stops moving the day that month closes.
    """
    expense = cost_entry.expense
    if expense is None:
        expense = Expense(category="service_cost")
        db.session.add(expense)
    # A mapping wins, then whatever the caller already knows. Stripe fees are
    # the case for the second: the customer that paid is on the balance
    # transaction and the client behind it is on Client.stripe_customer_id, so
    # the owner is known without anybody making a mapping by hand. A mapping
    # still overrides, for splitting a cost or reassigning it.
    expense.client_id = mapping.client_id if mapping else default_client_id
    expense.project_id = mapping.project_id if mapping else None
    expense.amount = cost_entry.allocated_amount
    expense.description = cost_entry.description
    expense.date = min(cost_entry.period_end, date.today())
    db.session.flush()
    cost_entry.expense_id = expense.id
    return expense


# ── Main Sync Dispatcher ────────────────────────────────────


def sync_all_providers():
    """Sync every active provider. Returns [(name, count, error), ...].

    One provider's failure does not stop the others: `sync_provider` records
    the error against the provider and returns it rather than raising, so a
    Twilio outage cannot cost you a month of Cloudflare charges.
    """
    results = []
    for provider in ServiceProvider.query.filter_by(is_active=True).order_by(
        ServiceProvider.name
    ).all():
        count, error = sync_provider(provider.id)
        results.append((provider.name, count, error))
    return results


def sync_provider(provider_id):
    provider = db.session.get(ServiceProvider, provider_id)
    if not provider or not provider.is_active:
        return 0, "Provider not found or inactive"
    if not provider.syncs:
        # Found by the night on the bank or in the code: nothing to ask, the
        # bank line is the record (vendor_discovery).
        return 0, None

    sync_funcs = {
        "aws": _sync_aws,
        "railway": _sync_railway,
        "twilio": _sync_twilio,
        "cloudflare": _sync_cloudflare,
        "flat": _sync_flat,
        "stripe": _sync_stripe,
    }

    func = sync_funcs.get(provider.name)
    if not func:
        return 0, f"Unknown provider type: {provider.name}"

    try:
        count = func(provider)
        # The report is how the bank's charges split: split them again now
        # it has changed, rather than wait for the night.
        import bank_feed
        bank_feed.resplit(provider_id=provider.id)
        provider.last_sync_at = datetime.now(timezone.utc)
        provider.sync_error = None
        db.session.commit()
        return count, None
    except Exception as e:
        provider.sync_error = str(e)
        provider.last_sync_at = datetime.now(timezone.utc)
        db.session.commit()
        return 0, str(e)


# ── Stripe processing fees ──────────────────────────────────


def _sync_stripe(provider):
    """Book Stripe's cut as an expense, per customer, per month.

    Every card payment is charged for twice: the customer pays you and Stripe
    keeps roughly 2.9% plus 30 cents. Revenue was being read gross, so the fee
    never appeared anywhere and a deductible cost went unclaimed. It runs about
    3% of everything collected, which is not small.

    Fees come off balance transactions rather than charges, because that is the
    one place every kind of fee lands: card processing, refunds, and Stripe's
    own periodic billing all carry a `fee` there, and reading charges alone
    would miss the last two.

    No credentials on the provider. Stripe is already configured for the app
    and the key lives in STRIPE_SECRET_KEY; storing a second copy on a provider
    row would be one more place to leak it from and one more to rotate.

    Grouped by customer so the fee lands on the client whose payment caused it.
    The owner comes from Client.stripe_customer_id, which is already maintained
    for revenue, so no mapping has to be made by hand. A mapping still wins if
    one exists, for splitting or reassigning.
    """
    import stripe as stripe_sdk
    from models import Client

    if not stripe_sdk.api_key:
        raise ValueError("Stripe is not configured (STRIPE_SECRET_KEY unset)")

    client_by_customer = {
        c.stripe_customer_id: c.id
        for c in Client.query.filter(Client.stripe_customer_id.isnot(None)).all()
    }
    name_by_customer = {
        c.stripe_customer_id: c.name
        for c in Client.query.filter(Client.stripe_customer_id.isnot(None)).all()
    }

    # (customer_id or None, period) -> fee dollars, and the lines behind it
    buckets, lines = {}, {}
    for txn in stripe_sdk.BalanceTransaction.list(limit=100, expand=["data.source"]).auto_paging_iter():
        fee = (getattr(txn, "fee", 0) or 0) / 100.0
        if fee <= 0:
            continue
        created = getattr(txn, "created", None)
        if not created:
            continue
        when = datetime.fromtimestamp(created, timezone.utc).date()

        source = getattr(txn, "source", None)
        customer = None
        if source is not None and not isinstance(source, str):
            customer = getattr(source, "customer", None)
            if customer is not None and not isinstance(customer, str):
                customer = getattr(customer, "id", None)

        key = (customer, _month_bounds(when))
        buckets[key] = buckets.get(key, 0.0) + fee
        lines.setdefault(key, []).append({
            "date": when, "id": getattr(txn, "id", "") or "",
            "type": getattr(txn, "type", "") or "",
            "description": getattr(txn, "description", "") or "",
            "amount": (getattr(txn, "amount", 0) or 0) / 100.0, "fee": fee})

    count = 0
    for (customer, (p_start, p_end)), amount in buckets.items():
        if customer:
            resource_id = f"stripe-fees:{customer}"
            who = name_by_customer.get(customer)
            label = f"Stripe fees - {who}" if who else "Stripe fees"
        else:
            # Stripe's own periodic charges, and anything whose source carries
            # no customer. Real money, nobody in particular to bill it to.
            resource_id = "stripe-fees:account"
            label = "Stripe fees - account"

        count += _record_cost_entry(
            provider, resource_id, p_start, p_end, round(amount, 2), label,
            {"customer": customer}, default_client_id=client_by_customer.get(customer),
        )
        _stripe_fee_statement(provider, resource_id, p_start, label,
                              lines.get((customer, (p_start, p_end)), []))

    db.session.commit()
    return count


def _stripe_fee_statement(provider, resource_id, p_start, label, rows):
    """The receipt for a month of Stripe's fees, written from Stripe's own
    balance transactions: Stripe emails no receipt for what it keeps, so this
    page is the record, one line per transaction with its id to look up in
    Stripe. Rewritten each night while the month is open, under the same
    name, and attached to every expense the month's fees became."""
    import html
    from flask import current_app
    from models import Expense
    expenses = [e for e in (Expense.query.join(ServiceCostEntry, ServiceCostEntry.expense_id == Expense.id)
                            .filter(ServiceCostEntry.provider_id == provider.id,
                                    ServiceCostEntry.resource_identifier == resource_id,
                                    ServiceCostEntry.period_start == p_start).all())
                if not e.receipt_filename or e.receipt_filename.startswith("stripe-fees-")]
    if not expenses or not rows:
        return
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", resource_id.split(":", 1)[-1])[:60]
    name = f"stripe-fees-{safe}-{p_start:%Y-%m}.html"
    body = "".join(
        f"<tr><td>{r['date']:%b %d, %Y}</td><td>{html.escape(r['type'])}</td>"
        f"<td>{html.escape(r['description'])}</td><td>{html.escape(r['id'])}</td>"
        f"<td style='text-align:right'>${r['amount']:,.2f}</td>"
        f"<td style='text-align:right'>${r['fee']:,.2f}</td></tr>"
        for r in sorted(rows, key=lambda r: (r["date"], r["id"])))
    total = round(sum(r["fee"] for r in rows), 2)
    page = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(label)} {p_start:%B %Y}</title>"
            f"<body style='font-family:sans-serif'><h1>{html.escape(label)}, {p_start:%B %Y}</h1>"
            f"<p>Stripe's processing fees, read from Stripe's balance transactions.</p>"
            f"<table cellpadding='6' border='1' style='border-collapse:collapse'>"
            f"<tr><th>Date</th><th>Type</th><th>Description</th><th>Stripe id</th><th>Amount</th><th>Fee</th></tr>"
            f"{body}<tr><td colspan='5'><b>Total fees</b></td>"
            f"<td style='text-align:right'><b>${total:,.2f}</b></td></tr></table></body>")
    import volume_files
    # Written by the nightly Stripe sync, which has no volume: volume_files
    # hands it to the web service's.
    volume_files.write(os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts"), name, page)
    for e in expenses:
        e.receipt_filename = name
        e.receipt_original_name = f"Stripe fees {p_start:%B %Y}.html"


# ── Flat monthly, for a vendor with no billing API ──────────


def _billing_date(when, billing_day):
    """The charge date in `when`'s month, clamped to a day that month has.

    A vendor billing on the 31st still bills in February, so the day is pulled
    back to the last of the month rather than raising or skipping.
    """
    _, last = _month_bounds(when)
    return when.replace(day=min(billing_day or 1, last.day))


def _sync_flat(provider):
    """Book a fixed monthly charge for a vendor that has no billing API.

    Anthropic is the case this was built for: there is no API to ask what a
    Claude subscription cost this month, so the amount is set on the provider
    and this books it on the billing day.

    The period is the single day the charge lands rather than the whole month,
    which does two things. The expense gets dated the day it was actually
    charged, because `_sync_expense` dates from `period_end`. And the entry key
    is unique per charge, so a vendor that bills twice in one month, as this
    one did in March and May, records both instead of the second overwriting
    the first.

    Nothing is booked before the billing day has arrived. A subscription you
    have not been charged for yet is not an expense, and booking it early would
    overstate every month until its billing day passed.
    """
    amount = provider.monthly_cost or 0
    if amount <= 0:
        return 0

    today = date.today()
    charged_on = _billing_date(today, provider.billing_day)
    if today < charged_on:
        return 0

    count = _record_cost_entry(
        provider, f"{provider.name}:subscription", charged_on, charged_on,
        amount, provider.display_name,
        {"billing_day": provider.billing_day, "flat_rate": amount},
    )
    db.session.commit()
    return count


FOLLOW_DAYS = 70


def follow_flat_from_bank(today=None):
    """A flat provider's amount and day are what its last settled bank line
    says (docs/automation_gaps.md, item 15).

    `monthly_cost` and `billing_day` were typed once, so a plan change booked
    the old amount on the old day and the real charge then fell to review as
    a charge the sync did not hold. Now, for each month of the last ten weeks
    with exactly ONE charge from this vendor that is Built by Bean's (its rule
    is split by this provider, the line was not settled by hand, and no
    other company's twin account or mailbox claims it), the month's entry is
    that charge, on its day and to the cent, any other entry the provider
    wrote in that month goes, and the provider takes the newest charge's
    amount and day for the months to come.

    A month with two such charges is left alone: EntertainHQ's own Claude plan
    is on the same card under the same name, and which is whose is a judgement,
    so the one the old figure does not explain waits on review as before.
    Returns how many charges it wrote or corrected.
    """
    import bank_feed
    from models import BankTransaction, VendorRule
    today = today or date.today()
    rules = VendorRule.query.all()
    changed = 0
    for provider in ServiceProvider.query.filter_by(name="flat", is_active=True).all():
        if not provider.is_ours:
            continue
        mine = {r.id for r in rules if r.provider_id == provider.id and r.disposition in ("split", "covered")}
        if not mine:
            continue
        by_month = {}
        for line in (BankTransaction.query.filter(
                BankTransaction.status == "sent", BankTransaction.amount < 0,
                BankTransaction.occurred_on >= today - timedelta(days=FOLLOW_DAYS))
                .order_by(BankTransaction.occurred_on, BankTransaction.id).all()):
            if line.decided_at and line.rule_id is None:
                continue  # somebody settled this one line by hand
            rule = bank_feed.rule_for(line, rules)
            if rule is None or rule.id not in mine:
                continue
            owner = rule.business_id or line.business_id
            if not bank_feed.provider_books(provider, owner):
                continue
            if bank_feed.other_company_for(line, provider, owner):
                continue
            by_month.setdefault(_month_bounds(line.occurred_on), []).append(line)
        newest = None
        resource = f"{provider.name}:subscription"
        for (first, last), lines in sorted(by_month.items()):
            if len(lines) != 1:
                continue
            line = lines[0]
            amount = round(-line.amount, 2)
            day = line.occurred_on
            for entry in ServiceCostEntry.query.filter(
                    ServiceCostEntry.provider_id == provider.id,
                    ServiceCostEntry.resource_identifier == resource,
                    ServiceCostEntry.period_start >= first,
                    ServiceCostEntry.period_start <= last).all():
                if entry.period_start != day:
                    discard_entry(entry)
            before = ServiceCostEntry.query.filter_by(provider_id=provider.id, resource_identifier=resource,
                                                      period_start=day, period_end=day).first()
            if before is None or abs((before.raw_amount or 0) - amount) >= 0.005:
                _record_cost_entry(provider, resource, day, day, amount, provider.display_name,
                                   {"billing_day": day.day, "flat_rate": amount, "bank_line": line.id})
                changed += 1
            db.session.flush()
            bank_feed.classify(line, rules)
            newest = line
        if newest is not None:
            provider.monthly_cost = round(-newest.amount, 2)
            provider.billing_day = newest.occurred_on.day
    db.session.commit()
    return changed


# ── AWS Cost Explorer ───────────────────────────────────────


def _sync_aws(provider):
    creds = _get_credentials(provider)
    region = creds.get("region", "us-east-2")
    key_id = creds.get("aws_access_key_id")
    secret = creds.get("aws_secret_access_key")

    ce = boto3.client("ce", region_name=region,
                       aws_access_key_id=key_id, aws_secret_access_key=secret)

    end = date.today()
    # Aligned to the first of a month, so every MONTHLY bucket Cost Explorer
    # returns starts on the 1st and covers a whole month. Asking from a date
    # mid-month returns a part-month bucket, and a part-month figure keyed to
    # the whole month overwrites the full one next time it is read.
    start = (end - timedelta(days=30)).replace(day=1)

    # 1. Get total cost by service
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    count = 0
    s3_total = 0

    for result in response.get("ResultsByTime", []):
        # The month the bucket belongs to. Cost Explorer ends the current
        # month's bucket at today, which moves, and see the note on Twilio
        # above for what a moving period_end does to a daily sync.
        p_start, p_end = _month_bounds(
            date.fromisoformat(result["TimePeriod"]["Start"]))

        for group in result.get("Groups", []):
            service_name = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if amount <= 0:
                continue

            if "S3" in service_name or "Storage Service" in service_name:
                s3_total = amount
                continue  # handle S3 separately below

            resource_id = f"aws:{service_name}"
            count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                        amount, f"AWS {service_name}", group)

    # 2. Break down S3 costs by bucket using CloudWatch storage metrics
    if s3_total > 0:
        p_start, p_end = _month_bounds()
        count += _sync_aws_s3_by_bucket(provider, creds, s3_total, p_start, p_end)

    db.session.commit()
    return count


def _sync_aws_s3_by_bucket(provider, creds, s3_total, p_start, p_end):
    region = creds.get("region", "us-east-2")
    s3 = boto3.client("s3", region_name=region,
                       aws_access_key_id=creds.get("aws_access_key_id"),
                       aws_secret_access_key=creds.get("aws_secret_access_key"))
    cw = boto3.client("cloudwatch", region_name=region,
                       aws_access_key_id=creds.get("aws_access_key_id"),
                       aws_secret_access_key=creds.get("aws_secret_access_key"))

    # List all buckets
    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except Exception:
        buckets = []

    if not buckets:
        resource_id = "aws-s3:total"
        if not _existing_entry(provider.id, resource_id, p_start, p_end):
            return _record_cost_entry(provider, resource_id, p_start, p_end,
                                      s3_total, "AWS S3 Total", {})
        return 0

    # Get storage size for each bucket via CloudWatch
    bucket_sizes = {}
    now = datetime.now(timezone.utc)
    for bucket in buckets:
        name = bucket["Name"]
        try:
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": name},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=now - timedelta(days=3),
                EndTime=now,
                Period=86400,
                Statistics=["Average"],
            )
            datapoints = resp.get("Datapoints", [])
            if datapoints:
                bucket_sizes[name] = max(dp["Average"] for dp in datapoints)
            else:
                bucket_sizes[name] = 0
        except Exception:
            bucket_sizes[name] = 0

    total_size = sum(bucket_sizes.values())
    if total_size <= 0:
        # Can't determine proportions, split evenly
        total_size = len(buckets)
        bucket_sizes = {b["Name"]: 1 for b in buckets}

    count = 0
    for bucket_name, size in bucket_sizes.items():
        proportion = size / total_size if total_size > 0 else 0
        bucket_cost = round(s3_total * proportion, 4)
        if bucket_cost <= 0:
            continue

        resource_id = f"aws-s3:{bucket_name}"
        count += _record_cost_entry(
            provider, resource_id, p_start, p_end, bucket_cost,
            f"AWS S3 - {bucket_name}",
            {"bucket": bucket_name, "size_bytes": size, "proportion": proportion},
        )

    return count


def _record_cost_entry(provider, resource_id, p_start, p_end, amount, desc_prefix,
                       raw_data, default_client_id=None):
    """Write, or correct, the cost of one resource for one period.

    Upsert rather than insert. A month to date figure grows all month, so a
    daily sync has to correct the row it wrote yesterday rather than stack
    another one beside it. The callers no longer skip a period they have
    already seen, for the same reason.

    One row per mapping when the resource is allocated and one unallocated row
    when it is not, with an Expense against every one of them either way.
    """
    # A one day period is a single dated charge rather than a month's usage, so
    # it gets the day. Anthropic billed twice in March and twice in May, and
    # two expense lines both reading "Claude (Mar 2026)" are indistinguishable
    # on the very screen they exist to explain.
    label = p_start.strftime('%d %b %Y') if p_start == p_end else p_start.strftime('%b %Y')
    description = f"{desc_prefix} ({label})"

    # `or [None]` is the unallocated case: one pass, no mapping, no client.
    for mapping in _find_mapping(provider.id, resource_id) or [None]:
        share = (mapping.split_percentage or 0) / 100.0 if mapping else 1.0
        entry = _existing_entry(provider.id, resource_id, p_start, p_end,
                                mapping.id if mapping else None)
        if entry is None:
            entry = ServiceCostEntry(
                provider_id=provider.id,
                mapping_id=mapping.id if mapping else None,
                resource_identifier=resource_id,
                period_start=p_start,
                period_end=p_end,
            )
            db.session.add(entry)
        entry.raw_amount = amount
        entry.allocated_amount = round(amount * share, 2)
        # "[unallocated]" has to follow whether the cost actually lands on a
        # client, not whether a mapping exists. Since a caller can supply the
        # owner directly, keying the label off the mapping alone labelled every
        # Stripe fee unallocated while it sat correctly on a client's row.
        #
        # An account that BELONGS to a client attributes every cost on it to
        # them by default, because it is their account and their card, and a
        # mapping can still override for one resource.
        owner = provider.account_client_id
        attributed = ((mapping.client_id if mapping else None)
                      or default_client_id or owner)
        entry.description = description if attributed else f"{description} [unallocated]"
        entry.raw_data_json = json.dumps(raw_data) if raw_data else None
        db.session.flush()
        if writes_expenses(provider):
            _sync_expense(entry, mapping, default_client_id=default_client_id)
        elif _keeps_old_expense(provider, entry):
            _sync_expense(entry, mapping, default_client_id=default_client_id)
        elif entry.expense is not None and entry.expense.bank_line_id is None:
            # Their account, their card (or a prepaid vendor's usage): the
            # cost is worth recording and worth seeing against them, and it
            # is not an expense. One a previous sync wrote for it goes, or the
            # ledger would keep counting it for ever.
            _drop_expense(entry)

    return len(_find_mapping(provider.id, resource_id) or [None])


# ── Railway ─────────────────────────────────────────────────


RAILWAY_API = "https://backboard.railway.com/graphql/v2"

# Railway's published prices, per unit its usage API reports in: vCPU-minutes,
# GB-minutes of memory and of volume, GB sent out. They only WEIGH one project
# against another; every month is scaled to the invoice, which is the real
# figure. They match the unit prices on Railway's own invoice lines (memory
# 2.3148148e-07 a MB-minute, volume 3.4722e-06 a GB-minute).
RAILWAY_RATES = {
    "CPU_USAGE": 20.0 / 43200,          # $20 a vCPU-month
    "MEMORY_USAGE_GB": 10.0 / 43200,    # $10 a GB-month
    "DISK_USAGE_GB": 0.15 / 43200,      # $0.15 a GB-month of volume
    "NETWORK_TX_GB": 0.05,              # $0.05 a GB out
}
# A recorded invoice this sync wrote, and so may correct. One typed off the
# bill by hand carries any other note and is never touched.
RAILWAY_NOTE = "From Railway"
RAILWAY_SPLIT_SOURCE = "railway-api"

_WORKSPACE_BILLING = """
query($w: String!) { workspace(workspaceId: $w) {
  name
  projects { edges { node { id name } } }
  customer { invoices { invoiceId periodStart periodEnd total status } }
} }"""
_WORKSPACE_USAGE = """
query($w: String!, $s: DateTime!, $e: DateTime!) {
  usage(workspaceId: $w, startDate: $s, endDate: $e, includeDeleted: true,
        measurements: [CPU_USAGE, MEMORY_USAGE_GB, DISK_USAGE_GB, NETWORK_TX_GB],
        groupBy: [PROJECT_ID]) { measurement value tags { projectId } }
}"""


def railway_token(creds):
    """The token a Railway provider reads with.

    One that names its workspace reads billing, which takes an ACCOUNT token,
    and that token lives in the service's variables (PM_RAILWAY_ACCOUNT_TOKEN)
    rather than on a form or in the database: made 2026-11-01 through the
    Railway API by the session that built this, one token for one login and
    both of its workspaces. A token typed on the provider's form is the
    fallback, and the only one a provider without a workspace uses.
    """
    if (creds.get("workspace_id") or "").strip():
        return os.environ.get("PM_RAILWAY_ACCOUNT_TOKEN") or creds.get("api_token", "")
    return creds.get("api_token", "")


def _railway_gql(token, query, variables=None, timeout=30):
    resp = requests.post(RAILWAY_API, json={"query": query, "variables": variables or {}},
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise ValueError(f"Railway API error: {data['errors'][0].get('message', 'Unknown error')}")
    return data.get("data") or {}


def _railway_when(raw):
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _sync_railway(provider):
    """Railway's bills, each month's split across its projects by usage.

    The comment that stood here from 2026-08-31 said Railway's API will not
    tell you what you are spending, and for the token it was probed with that
    was true: a token scoped below the account cannot see billing at all. An
    ACCOUNT token can (2026-11-01): `workspace.customer.invoices` is every bill
    with its period and total in cents, and `usage` grouped by project is what
    each project used over any range. So once a month nobody types anything:

      - each finished invoice lands in ProviderInvoice under the month its
        period starts (the convention the hand-typed rows already used: the
        bill for Aug 1 to Sep 1 is August's). A row somebody typed by hand is
        left exactly as it is; only rows this sync wrote are corrected;
      - that month's bill is split across the workspace's projects in
        proportion to what each used, priced at RAILWAY_RATES and scaled so
        the projects add up to the invoice to the cent. A month already
        broken down by hand is left alone.

    `workspace_id` in the credentials says which workspace this provider is.
    Without one the sync only proves the token works, as before.
    """
    creds = _get_credentials(provider)
    token = railway_token(creds)
    if not token:
        raise ValueError("Railway API token not configured")
    workspace_id = (creds.get("workspace_id") or "").strip()
    if not workspace_id:
        _railway_gql(token, "query { projects { edges { node { id } } } }")
        return 0

    try:
        ws = _railway_gql(token, _WORKSPACE_BILLING, {"w": workspace_id}).get("workspace")
    except ValueError as exc:
        if "authorized" in str(exc).lower():
            raise ValueError("This Railway token cannot read the workspace's bills. Use an "
                             "account token: Railway, Account Settings, Tokens, with no "
                             "workspace chosen.") from exc
        raise
    if not ws:
        raise ValueError(f"No Railway workspace {workspace_id} for this token")
    provider.account_label = (ws.get("name") or "")[:200] or provider.account_label
    projects = {e["node"]["id"]: e["node"]["name"]
                for e in (ws.get("projects") or {}).get("edges") or []}
    _adopt_sibling_mappings(provider, projects)

    now = datetime.now(timezone.utc)
    months = {}
    for inv in (ws.get("customer") or {}).get("invoices") or []:
        if inv.get("status") not in ("paid", "open"):
            continue
        start, end = _railway_when(inv["periodStart"]), _railway_when(inv["periodEnd"])
        if end > now:
            continue  # the period is still running; it is billed when it closes
        months.setdefault(start.date().replace(day=1), []).append((start, end, inv))

    written = 0
    for month, invs in sorted(months.items()):
        amount = round(sum((inv.get("total") or 0) for _, _, inv in invs) / 100.0, 2)
        dates = ", ".join(f"{s:%b %d} to {e:%b %d}" for s, e, _ in sorted(invs, key=lambda x: x[0]))
        note = f"{RAILWAY_NOTE}: {len(invs)} invoice{'s' if len(invs) != 1 else ''}, {dates}"
        row = ProviderInvoice.query.filter_by(provider_id=provider.id, period_month=month).first()
        if row is None:
            row = ProviderInvoice(provider_id=provider.id, period_month=month)
            db.session.add(row)
        elif not (row.note or "").startswith(RAILWAY_NOTE):
            continue  # typed off the bill by hand: a fact somebody recorded
        row.amount = amount
        row.note = note[:300]
        db.session.flush()
        written += _split_railway_month(provider, token, workspace_id, month, invs,
                                        amount, projects)
    return written


def _adopt_sibling_mappings(provider, projects):
    """A Railway project keeps its id when it moves to another workspace, so a
    mapping made for it under one Railway account is the same answer under the
    other. Copied, never guessed from a name: EntertainHQ's project moved to its
    own workspace on 2026-09-16 and was already mapped to its project here."""
    for pid in projects:
        rid = f"railway:{pid}"
        if ServiceMapping.query.filter_by(provider_id=provider.id, resource_identifier=rid).first():
            continue
        siblings = (ServiceMapping.query.join(ServiceProvider)
                    .filter(ServiceProvider.name == "railway",
                            ServiceProvider.id != provider.id,
                            ServiceMapping.resource_identifier == rid,
                            ServiceMapping.is_active.is_(True)).all())
        for m in siblings:
            db.session.add(ServiceMapping(
                provider_id=provider.id, resource_identifier=rid,
                resource_label=m.resource_label or projects[pid], client_id=m.client_id,
                project_id=m.project_id, split_percentage=m.split_percentage, is_active=True))
    db.session.flush()


def _split_railway_month(provider, token, workspace_id, month, invs, amount, projects):
    """One month's bill across its projects. Returns how many entries it wrote."""
    if amount <= 0:
        return 0
    m_start, m_end = _month_bounds(month)
    for e in ServiceCostEntry.query.filter_by(provider_id=provider.id, period_start=m_start,
                                              period_end=m_end).all():
        try:
            source = json.loads(e.raw_data_json or "{}").get("source")
        except ValueError:
            source = None
        if source != RAILWAY_SPLIT_SOURCE:
            return 0  # broken down by hand already
    start = min(s for s, _, _ in invs)
    end = max(e for _, e, _ in invs)
    rows = _railway_gql(token, _WORKSPACE_USAGE, {
        "w": workspace_id, "s": start.isoformat().replace("+00:00", "Z"),
        "e": end.isoformat().replace("+00:00", "Z")}, timeout=60).get("usage") or []
    weight = {}
    for r in rows:
        pid = (r.get("tags") or {}).get("projectId")
        rate = RAILWAY_RATES.get(r.get("measurement"))
        if pid and rate:
            weight[pid] = weight.get(pid, 0.0) + (r.get("value") or 0.0) * rate
    weight = {pid: w for pid, w in weight.items() if w > 0}
    span = {"period": [start.date().isoformat(), end.date().isoformat()]}
    if not weight:
        _record_cost_entry(provider, f"{provider.name}:other", m_start, m_end, amount,
                           f"{provider.display_name} - Not broken down",
                           {"source": RAILWAY_SPLIT_SOURCE, "label": "Not broken down", **span})
        return 1
    total = sum(weight.values())
    cents = {pid: int(round(amount * 100 * w / total)) for pid, w in weight.items()}
    # Whole cents that add up to the bill exactly: the rounding goes on the
    # largest share, where a cent is the smallest part of anything.
    largest = max(cents, key=lambda pid: weight[pid])
    cents[largest] += int(round(amount * 100)) - sum(cents.values())
    written = set()
    for pid, c in cents.items():
        if c <= 0:
            continue
        rid = f"railway:{pid}"
        label = projects.get(pid) or f"Deleted project {pid[:8]}"
        _record_cost_entry(provider, rid, m_start, m_end, c / 100.0,
                           f"{provider.display_name} - {label}",
                           {"source": RAILWAY_SPLIT_SOURCE, "label": label, **span})
        # A project mapped since the last pull has a no-mapping row from then;
        # left beside the new one it reads double (the page does the same).
        prune_stale_allocations(provider, rid, m_start, m_end)
        written.add(rid)
    # And a row this sync wrote for a project that is no longer in the split.
    for e in ServiceCostEntry.query.filter_by(provider_id=provider.id, period_start=m_start,
                                              period_end=m_end).all():
        if e.resource_identifier not in written:
            discard_entry(e)
    db.session.flush()
    return len(written)


# ── Twilio ──────────────────────────────────────────────────


def _sync_twilio(provider):
    creds = _get_credentials(provider)
    account_sid = creds.get("account_sid", "")
    # An API key made on the account first; the main auth token for an account
    # connected before keys were asked for.
    if creds.get("api_key_sid") and creds.get("api_key_secret"):
        auth = (creds["api_key_sid"], creds["api_key_secret"])
    else:
        auth = (account_sid, creds.get("auth_token", ""))
    if not account_sid or not auth[1]:
        raise ValueError("Twilio credentials not configured")

    now = date.today()
    start = now.replace(day=1)

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Usage/Records/Monthly.json"
    params = {"StartDate": start.isoformat(), "EndDate": now.isoformat()}

    resp = requests.get(url, params=params, auth=auth, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # What Twilio itself calls this account. A SID answers nobody's question
    # about whose account is being read, and the answer decides whether the
    # money on it is this business's or a client's. Never fatal: a sync that
    # read real charges does not fail because a label lookup did.
    try:
        who = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
            auth=auth, timeout=15)
        if who.status_code == 200:
            provider.account_label = (who.json().get("friendly_name") or "")[:200]
    except Exception:
        pass

    records = data.get("usage_records", [])

    count = 0
    for record in records:
        category = record.get("category", "unknown")
        price = float(record.get("price", 0) or 0)
        if price <= 0:
            continue

        resource_id = f"twilio:{category}"
        # The calendar month the record falls in, NOT the slice Twilio happens
        # to be reporting. A monthly usage record's end_date moves with today
        # while the month is open, and period_end is part of the entry's key,
        # so a nightly sync wrote a new row every night holding the month to
        # date instead of correcting the one it wrote the night before.
        # September 2026 booked itself fifteen times and read $462.79 against
        # $59.67 of real usage. Read off the record's own start_date rather
        # than off today, so widening the query range later cannot silently
        # file August's usage under September.
        p_start, p_end = _month_bounds(
            date.fromisoformat(record.get("start_date", start.isoformat())))

        description_text = record.get("description", category)

        count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                    price, f"Twilio - {description_text}", record)

    db.session.commit()
    return count


# ── Cloudflare ──────────────────────────────────────────────


def _cloudflare_registrar_domains(account_id, headers):
    """Domains registered through Cloudflare, or [] if the token cannot see them.

    Deliberately swallows a failure. Registrar is a separate token permission
    from billing, and an account with no Cloudflare-registered domains answers
    403 rather than empty. Neither is a reason to fail a sync that is otherwise
    reading real charges.
    """
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/registrar/domains"
    try:
        data = requests.get(url, headers=headers, timeout=30).json()
    except Exception as e:
        current_app.logger.info(f"Cloudflare registrar unavailable: {e}")
        return []
    if not data.get("success"):
        return []

    domains = []
    for row in data.get("result") or []:
        name, expires = row.get("name"), row.get("expires_at")
        if not name or not expires:
            continue
        try:
            domains.append((name, date.fromisoformat(str(expires)[:10])))
        except ValueError:
            continue
    return domains


def _domain_for_charge(domains, charged_on, tolerance_days=2):
    """Which domain a registrar charge paid for, or None if it is not clear.

    A Cloudflare invoice says nothing about what it bought: no description, no
    domain, just an amount and a receipt number. The link is the date. A
    registration or renewal sets the expiry exactly one year later, so the day
    a domain was last charged is its expiry minus a year, and an invoice
    landing on that day is that domain's.

    Verified against the two real charges on this account: both matched their
    domain to the day, $50.00 on 2026-04-24 to datadungeon.io expiring
    2027-04-24, and $10.46 on 2026-08-21 to kuperplumbing.com expiring
    2027-08-21.

    Returns None when two domains renew close enough together to both match.
    An unattributed cost is a small problem; one confidently billed to the
    wrong client is a much worse one.
    """
    hits = []
    for name, expires in domains:
        try:
            charged = expires.replace(year=expires.year - 1)
        except ValueError:  # 29 February
            charged = expires.replace(year=expires.year - 1, day=28)
        if abs((charged_on - charged).days) <= tolerance_days:
            hits.append(name)
    return hits[0] if len(hits) == 1 else None


def _sync_cloudflare(provider):
    creds = _get_credentials(provider)
    api_token = creds.get("api_token", "")
    account_id = creds.get("account_id", "")
    if not api_token or not account_id:
        raise ValueError("Cloudflare credentials not configured")

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Get zones for this account
    zones_url = f"https://api.cloudflare.com/client/v4/zones?account.id={account_id}&per_page=50"
    resp = requests.get(zones_url, headers=headers, timeout=30)
    resp.raise_for_status()
    zones_data = resp.json()

    if not zones_data.get("success"):
        errors = zones_data.get("errors", [])
        raise ValueError(f"Cloudflare API error: {errors}")

    zones = zones_data.get("result", [])

    # Get billing history
    billing_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/billing/history?per_page=20&order=occurred_at&direction=desc"
    resp2 = requests.get(billing_url, headers=headers, timeout=30)
    resp2.raise_for_status()
    billing_data = resp2.json()

    # Fetched before the charges are walked, so each one can be matched to the
    # domain it paid for. Empty when the token lacks registrar permission, in
    # which case charges fall back to being keyed on the invoice.
    registrar_domains = _cloudflare_registrar_domains(account_id, headers)

    # Zone plan charges are recurring, so they belong to the current calendar
    # month. Billing history items carry their own date and override this.
    p_start, p_end = _month_bounds()

    count = 0

    # Process billing items
    if billing_data.get("success"):
        for item in billing_data.get("result", []):
            amount = float(item.get("amount", 0) or 0)
            if amount <= 0:
                continue

            item_id = item.get("id", "unknown")
            description = item.get("description") or f"{item.get('type', 'charge')} {item.get('receipt_id', '')}".strip()

            # A charge belongs to the month it happened in, not the month the
            # sync happened to run in. This used to stamp every charge with
            # today, which filed an April invoice under July and made the
            # ledger disagree with the card statement.
            occurred = item.get("occurred_at") or item.get("occured_at")
            when = date.fromisoformat(occurred[:10]) if occurred else date.today()
            c_start, c_end = _month_bounds(when)

            # Key a domain charge on the domain, not the invoice. An invoice id
            # is unique per charge, so a mapping made against one would attribute
            # this year's renewal and silently miss every one after it. The
            # domain name is the thing that stays the same, which is what a
            # client mapping needs to hang on.
            domain = _domain_for_charge(registrar_domains, when)
            if domain:
                resource_id = f"cloudflare-domain:{domain}"
                label = f"Cloudflare - {domain} registration"
            else:
                resource_id = f"cloudflare:{item_id}"
                label = f"Cloudflare - {description}"

            count += _record_cost_entry(provider, resource_id, c_start, c_end,
                                        amount, label, item)

    # Also track per-zone as resources (even if free) so they can be mapped
    for zone in zones:
        zone_id = zone.get("id", "")
        zone_name = zone.get("name", "")
        plan = zone.get("plan", {})
        plan_price = float(plan.get("price", 0) or 0)

        resource_id = f"cloudflare-zone:{zone_id}"

        if plan_price <= 0:
            continue

        count += _record_cost_entry(provider, resource_id, p_start, p_end,
                                    plan_price, f"Cloudflare - {zone_name}", zone)

    db.session.commit()
    return count


# ── List Resources (for mapping UI) ────────────────────────


def list_provider_resources(provider):
    creds = _get_credentials(provider)
    resources = []

    try:
        if provider.name == "aws":
            s3 = boto3.client(
                "s3",
                aws_access_key_id=creds.get("aws_access_key_id"),
                aws_secret_access_key=creds.get("aws_secret_access_key"),
                region_name=creds.get("region", "us-east-2"),
            )
            buckets = s3.list_buckets().get("Buckets", [])
            for b in buckets:
                resources.append({
                    "id": f"aws-s3:{b['Name']}",
                    "label": f"S3 Bucket: {b['Name']}",
                })
            for svc in ["Amazon Route 53", "Amazon CloudFront",
                        "AWS Lambda", "Amazon EC2", "AWS Key Management Service"]:
                resources.append({"id": f"aws:{svc}", "label": svc})

        elif provider.name == "railway":
            token = railway_token(creds)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            # This provider's own workspace when it names one, so two Railway
            # accounts never list each other's projects; the token-wide list
            # otherwise, or when the token cannot read the workspace yet.
            edges = None
            if creds.get("workspace_id"):
                try:
                    ws = _railway_gql(token, "query($w: String!) { workspace(workspaceId: $w) "
                                      "{ projects { edges { node { id name } } } } }",
                                      {"w": creds["workspace_id"]}, timeout=15).get("workspace")
                    edges = ((ws or {}).get("projects") or {}).get("edges")
                except Exception:
                    edges = None
            if edges is None:
                query = '{ projects { edges { node { id name } } } }'
                resp = requests.post("https://backboard.railway.com/graphql/v2",
                                     json={"query": query}, headers=headers, timeout=15)
                if resp.status_code == 200:
                    edges = resp.json().get("data", {}).get("projects", {}).get("edges", [])
            if edges is not None:
                for edge in edges:
                    node = edge.get("node", {})
                    resources.append({
                        "id": f"railway:{node.get('id', '')}",
                        "label": node.get("name", "Unknown"),
                    })

        elif provider.name == "twilio":
            sid = creds.get("account_sid", "")
            auth = creds.get("auth_token", "")
            # List common categories
            for cat in ["sms", "calls", "phonenumbers", "recordings", "totalprice"]:
                resources.append({"id": f"twilio:{cat}", "label": f"Twilio: {cat}"})

        elif provider.name == "cloudflare":
            api_token = creds.get("api_token", "")
            account_id = creds.get("account_id", "")
            headers = {"Authorization": f"Bearer {api_token}"}
            resp = requests.get(
                f"https://api.cloudflare.com/client/v4/zones?account.id={account_id}&per_page=50",
                headers=headers, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for zone in data.get("result", []):
                resources.append({
                    "id": f"cloudflare-zone:{zone['id']}",
                    "label": f"Zone: {zone['name']}",
                })

            # Registered domains are the mappable thing here, because a
            # registration or renewal is a real recurring charge and it belongs
            # to whoever the domain is for. Zones are free on this account.
            for name, expires in _cloudflare_registrar_domains(account_id, headers):
                resources.append({
                    "id": f"cloudflare-domain:{name}",
                    "label": f"Domain: {name} (renews {expires:%d %b %Y})",
                })

    except Exception as e:
        current_app.logger.error(f"Error listing resources for {provider.name}: {e}")

    return resources


# ── Dashboard Data ──────────────────────────────────────────


def get_cost_summary(months=6):
    now = date.today()
    start = (now.replace(day=1) - timedelta(days=months * 30)).replace(day=1)

    entries = ServiceCostEntry.query.filter(
        ServiceCostEntry.period_start >= start,
    ).all()

    by_provider = {}
    by_client = {}
    by_month = {}
    unallocated = 0
    total = 0

    for e in entries:
        total += e.allocated_amount

        # By provider
        pname = e.provider.display_name if e.provider else "Unknown"
        by_provider[pname] = by_provider.get(pname, 0) + e.allocated_amount

        # By client
        if e.mapping and e.mapping.client:
            cname = e.mapping.client.name
            by_client[cname] = by_client.get(cname, 0) + e.allocated_amount
        else:
            unallocated += e.allocated_amount

        # By month
        month_key = e.period_start.strftime("%Y-%m")
        by_month[month_key] = by_month.get(month_key, 0) + e.allocated_amount

    return {
        "total": round(total, 2),
        "unallocated": round(unallocated, 2),
        "by_provider": {k: round(v, 2) for k, v in sorted(by_provider.items())},
        "by_client": {k: round(v, 2) for k, v in sorted(by_client.items(), key=lambda x: -x[1])},
        "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
    }
