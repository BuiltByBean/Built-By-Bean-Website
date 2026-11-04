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
