"""Which of a vendor's monthly bills the board is still missing.

One answer, read by Needs attention (`_bills_to_enter`) and by the door's
`get_costs`. Each used to work it out for itself, and only one of them knew
that a Railway account whose bills are PULLED need not bill on the 1st:
EntertainHQ's runs 16th to 16th, so its October bill does not exist until
November 16. Needs attention gave it that month; the door reported October as
not recorded, so a session checking the figures was told a bill was missing
that Railway had not written yet (audit fault 8).
"""
import json
from datetime import date, timedelta


# Vendors whose bill is recorded month by month on the Railway months page of
# Hosting (typed off the invoice, or pulled with an account token), so a month
# with no bill is a hole in what the vendor cost. Only Railway: Cloudflare and
# Twilio read their own billing, and a flat provider is its charge on the bank.
MANUAL_MONTHLY_PROVIDERS = {"railway"}


def month_starts(first, stop):
    """Every month start from `first` up to but not including `stop`."""
    out, m = [], first.replace(day=1)
    while m < stop:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def pulls_its_bills(provider):
    """A Railway account that names its workspace reads its own bills
    (service_costs_service._sync_railway)."""
    try:
        return bool(json.loads(provider.credentials_json or "{}").get("workspace_id"))
    except (TypeError, ValueError):
        return False


def bill_months(provider, today=None):
    """(missing, waiting) for one provider: month starts with no recorded bill.

    `missing` is every finished month since the vendor first cost anything
    here (its first cost entry or first bill) with no `ProviderInvoice`.
    `waiting` is the month left out of that for an account that pulls its own
    bills: the month just finished, whose bill may not exist yet. Ask about it
    only once a whole further month has passed, which is when a missing one
    means the pull has stopped working. Never the month in progress.
    """
    from models import db, ProviderInvoice, ServiceCostEntry

    this_month = (today or date.today()).replace(day=1)
    first_entry = (db.session.query(db.func.min(ServiceCostEntry.period_start))
                   .filter(ServiceCostEntry.provider_id == provider.id).scalar())
    first_invoice = (db.session.query(db.func.min(ProviderInvoice.period_month))
                     .filter(ProviderInvoice.provider_id == provider.id).scalar())
    starts = [d for d in (first_entry, first_invoice) if d]
    if not starts:
        return [], []
    have = {r.period_month for r in
            ProviderInvoice.query.filter_by(provider_id=provider.id).all()}
    absent = [m for m in month_starts(min(starts), this_month) if m not in have]
    if pulls_its_bills(provider):
        grace = (this_month - timedelta(days=1)).replace(day=1)
        return [m for m in absent if m < grace], [m for m in absent if m >= grace]
    return absent, []


def missing_bills(providers=None, today=None):
    """Every active by-the-month vendor with a bill to record, newest month
    last: [{"provider", "missing", "latest", "count"}].

    THE list: Needs attention draws it (`_bills_to_enter`), the Railway months
    tab counts it and the page under that tab lists it, so the three cannot
    disagree. A second copy of this check (`months_missing_manual_costs`,
    which asked whether last month had any cost entries) said a month was
    missing on a different test from this one and put EntertainHQ's October
    bill on the Expenses page before it existed.
    """
    from models import ServiceProvider
    if providers is None:
        providers = (ServiceProvider.query.filter_by(is_active=True)
                     .order_by(ServiceProvider.display_name).all())
    out = []
    for p in providers:
        if p.name not in MANUAL_MONTHLY_PROVIDERS or not p.is_active:
            continue
        missing, _ = bill_months(p, today=today)
        if missing:
            out.append({"provider": p, "missing": missing,
                        "latest": missing[-1], "count": len(missing)})
    return out
