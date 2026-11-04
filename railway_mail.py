"""A Railway bill read off the receipt mailbox, for an account with no token.

docs/automation_gaps.md, smaller ones. A Railway account that names its
workspace pulls its own bills (service_costs_service._sync_railway). One with
no token, a partner's or a client's own workspace, was typed off the bill by
hand, and Needs attention asked for it every month. Railway mails a receipt
for every bill, and the receipt sweep already keeps it (receipts_service, a
Receipt row with the sender, the date and the amount charged), so the month
is recorded from there.

Which account a receipt belongs to is the business whose mailbox it arrived
in: the tokenless Railway provider that business pays for (account_business_id,
or neither column set for the company the board bills from). Two such
providers for one business is a guess, and nothing is written.

The month is the one the bill's period starts in, the convention every other
row uses: a receipt on Sep 1 pays Aug 1 to Sep 1, which is August; one on
Nov 16 pays Oct 16 to Nov 16, which is October. So it is the receipt's date
less a month. A row typed by hand, or pulled from the API, is never touched:
only rows whose note starts MAIL_NOTE are this module's to correct.
"""
from datetime import date

MAIL_NOTE = "From mail"


def period_month(received):
    """The month a Railway bill received on `received` is for."""
    year, month = (received.year, received.month - 1) if received.month > 1 else (received.year - 1, 12)
    return date(year, month, 1)


def is_railway(receipt):
    return "railway" in (receipt.sender or "").lower() or (receipt.vendor or "").lower().startswith("railway")


def tokenless_providers():
    """{business_id: provider} for Railway accounts with no token, one each."""
    from models import ServiceProvider
    import books_service
    import service_costs_service
    board = books_service.board_business()
    found = {}
    for p in ServiceProvider.query.filter_by(name="railway", is_active=True).all():
        if p.account_client_id is not None:
            continue  # a client's account: not in any mailbox of ours
        if service_costs_service.railway_token(service_costs_service._get_credentials(p)):
            continue
        owner = p.account_business_id or (board.id if board else None)
        if owner is None:
            continue
        found.setdefault(owner, []).append(p)
    return {b: ps[0] for b, ps in found.items() if len(ps) == 1}


def run():
    from models import db, ProviderInvoice, Receipt, ReceiptMailbox
    providers = tokenless_providers()
    if not providers:
        return "no Railway account without a token"
    months = {}
    for r in Receipt.query.filter(Receipt.amount.isnot(None), Receipt.received_on.isnot(None)).all():
        if not is_railway(r) or r.amount <= 0:
            continue
        box = db.session.get(ReceiptMailbox, r.mailbox_id)
        provider = providers.get(box.business_id) if box else None
        if provider is None:
            continue
        key = (provider.id, period_month(r.received_on))
        months.setdefault(key, []).append(r)
    written = 0
    for (provider_id, month), receipts in sorted(months.items()):
        amount = round(sum(r.amount for r in receipts), 2)
        row = ProviderInvoice.query.filter_by(provider_id=provider_id, period_month=month).first()
        if row is None:
            row = ProviderInvoice(provider_id=provider_id, period_month=month)
            db.session.add(row)
        elif not (row.note or "").startswith(MAIL_NOTE):
            continue
        dates = ", ".join(f"{r.received_on:%b} {r.received_on.day}" for r in receipts)
        note = f"{MAIL_NOTE}: {len(receipts)} receipt{'s' if len(receipts) != 1 else ''}, {dates}"
        if row.amount != amount or row.note != note:
            row.amount, row.note = amount, note[:300]
            written += 1
    db.session.commit()
    return f"{written} Railway months recorded from mail"
