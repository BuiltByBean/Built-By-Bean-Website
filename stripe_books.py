"""A company's own Stripe account, read into its books.

Michael, 2026-11-03, on where EntertainHQ's income should come from:
"Wouldn't we be getting our number from Stripe ... what if there's a bunch
of money sitting in Stripe that we haven't transferred over to our Mercury
account?" Exactly. A sale happens in Stripe: the customer's card is charged
the full price on a day, Stripe keeps its fee, and what is left reaches the
bank a couple of days later as a payout. So for a company that takes cards
through its own Stripe account:

  income    every charge, gross, dated the day it was paid, less refunds,
            whether or not Stripe has paid it out yet. This is also the
            figure on the 1099-K Stripe files for the year.
  expense   Stripe's fees, one Expense per month in that company's books.
  transfer  the payout landing in Mercury: the company's own money moving
            from its Stripe balance to its bank, never income a second time
            (bank_feed classifies a deposit from Stripe that way).

Read through a RESTRICTED key the owner makes in Stripe with read access to
the balance, typed on the company's page and never shown again. Built by
Bean's own Stripe is read elsewhere (its invoices are the income, its fees
are a vendor sync), so this is for every other company.
"""
import sys
from datetime import date, datetime, timedelta, timezone

BOOKS_START = date(2026, 4, 1)
OVERLAP_DAYS = 7
SALE_CATEGORIES = {"charge", "payment", "refund", "payment_refund", "dispute", "dispute_reversal"}
FEE_LABEL = "Stripe fees"


class StripeKeyError(Exception):
    pass


def _client(key):
    import stripe
    return stripe, {"api_key": key}


def check_key(key):
    """Raise StripeKeyError unless the key can read the balance."""
    import stripe
    try:
        stripe.Balance.retrieve(api_key=key)
    except stripe.error.AuthenticationError as err:
        raise StripeKeyError("Stripe refused that key.") from err
    except stripe.error.PermissionError as err:
        raise StripeKeyError("That key cannot read the balance. Give it Balance: Read.") from err
    except stripe.error.StripeError as err:
        raise StripeKeyError(f"Stripe answered: {str(err)[:120]}") from err


def fetch(key, since):
    """Every balance transaction created on or after `since`, as dicts."""
    import stripe
    start = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
    try:
        for t in stripe.BalanceTransaction.list(api_key=key, limit=100,
                                                created={"gte": start}).auto_paging_iter():
            yield {"id": t.id, "created": t.created, "amount": t.amount, "fee": t.fee,
                   "net": t.net, "currency": t.currency,
                   "category": getattr(t, "reporting_category", None) or t.type,
                   "type": t.type, "description": t.description or ""}
    except stripe.error.AuthenticationError as err:
        raise StripeKeyError("Stripe refused the key. Make a new restricted key.") from err
    except stripe.error.StripeError as err:
        raise StripeKeyError(f"Stripe answered: {str(err)[:120]}") from err


def sync(business, fetcher=None):
    """Read one company's Stripe into StripeActivity and its monthly fee
    expenses. Returns counts, or {"error": ...}."""
    from models import db, StripeActivity
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = BOOKS_START
    if business.stripe_synced_at and business.stripe_ok:
        since = max(since, (business.stripe_synced_at - timedelta(days=OVERLAP_DAYS)).date())
    counts = {"read": 0, "new": 0}
    touched = set()
    try:
        for row in (fetcher or fetch)(business.stripe_key, since):
            counts["read"] += 1
            act = StripeActivity.query.filter_by(business_id=business.id, external_id=row["id"]).first()
            if act is None:
                act = StripeActivity(business_id=business.id, external_id=row["id"])
                db.session.add(act)
                counts["new"] += 1
            act.created_on = datetime.fromtimestamp(row["created"], timezone.utc).date()
            act.category = (row.get("category") or "")[:40]
            act.kind = (row.get("type") or "")[:40]
            act.amount = round((row.get("amount") or 0) / 100.0, 2)
            act.fee = round((row.get("fee") or 0) / 100.0, 2)
            act.net = round((row.get("net") or 0) / 100.0, 2)
            act.currency = (row.get("currency") or "usd")[:8]
            act.description = (row.get("description") or "")[:300]
            touched.add(date(act.created_on.year, act.created_on.month, 1))
        db.session.flush()
    except StripeKeyError as err:
        db.session.rollback()
        business.stripe_ok = False
        business.stripe_note = str(err)[:300]
        business.stripe_synced_at = now
        db.session.commit()
        return {"error": str(err)}
    for month in sorted(touched):
        book_fees(business, month)
    business.stripe_ok = True
    business.stripe_synced_at = now
    business.stripe_note = f"{counts['read']:,} Stripe lines read, {counts['new']:,} new"
    db.session.commit()
    return counts


def book_fees(business, month):
    """The month's Stripe fees as ONE expense in the company's books, written
    or corrected in place, removed if the month has none."""
    from models import db, Expense, StripeActivity
    end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    total = round(sum(a.fee for a in StripeActivity.query.filter(
        StripeActivity.business_id == business.id, StripeActivity.created_on >= month,
        StripeActivity.created_on < end).all()), 2)
    label = f"{FEE_LABEL}, {month:%b %Y}"
    expense = Expense.query.filter_by(business_id=business.id, description=label,
                                      category="bank_fees").first()
    if total <= 0:
        if expense is not None:
            db.session.delete(expense)
        return None
    if expense is None:
        expense = Expense(business_id=business.id, description=label, category="bank_fees",
                          amount=total, date=min(end - timedelta(days=1), date.today()))
        db.session.add(expense)
    expense.amount = total
    expense.date = min(end - timedelta(days=1), date.today())
    return expense


def income_between(business, start, end):
    """[(date, amount, description)]: gross sales less refunds, per day paid."""
    from models import StripeActivity
    out = []
    for a in (StripeActivity.query.filter(StripeActivity.business_id == business.id,
                                          StripeActivity.created_on >= start,
                                          StripeActivity.created_on < end,
                                          StripeActivity.category.in_(SALE_CATEGORIES))
              .order_by(StripeActivity.created_on, StripeActivity.id).all()):
        out.append((a.created_on, a.amount, a.description or a.category.replace("_", " ").capitalize()))
    return out


def sync_all(app):
    from models import Business
    with app.app_context():
        for b in Business.query.filter(Business.stripe_key.isnot(None), Business.stripe_key != "").all():
            result = sync(b)
            print(f"  stripe {b.name:30} {result.get('error') or b.stripe_note}", flush=True)


def main():
    from app import create_app
    sync_all(create_app())
    return 0


if __name__ == "__main__":
    sys.exit(main())
