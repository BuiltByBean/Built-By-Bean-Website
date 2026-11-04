"""What each company's profit costs Michael in income tax, for one year.

docs/finances_plan.md item 4 (Michael, 2026-11-04). The Taxes page and the
Overview both read `estimate(business, year)`, so the two can never show
different taxes for the same company and year.

The profit is the Books page's: `books_service.summarize(company, Jan 1,
next Jan 1)["net"]`, to the cent. It was Stripe's payouts once, which counted
sales tax as income, took Stripe's fee off twice and covered one company only.

Two kinds of company:

  * schedule_c: a company with one owner at most (Built by Bean LLC and its
    DBAs, one set of books). Its profit lands on Michael's own Schedule C and
    pays self employment tax there.
  * partnership: a company with more than one `BusinessOwner` (EntertainHQ
    LLC, three members). It files a 1065 and pays no income or self
    employment tax itself; each member's share of the net passes through to
    that member's own return on a K-1. Only Michael's share is his tax, and
    an active member's share pays self employment tax on HIS return, so it
    goes through the same engine as a Schedule C profit.

Every company Michael's return sees is stacked in one order (Schedule C
companies first, then his partnership shares) on top of the wages and other
income typed on the Taxes page, and each one's tax is the difference it makes
to the return: tax with it, less tax without it. That is `tax_engine`'s own
rule ("the difference the business makes") applied once per company, so the
companies' taxes add up to the business part of the return, and a share that
pushes him into the next bracket is charged to the share that did it.

Set aside is the same rate on the same profit, counted through `today`: what
should already be in the tax pot. For a finished year it is the tax.

No network of its own. The board company's income is its Stripe invoices,
read through `stripe_service`'s five minute cache exactly as the Books page
reads them; every other figure is the database. Summaries are kept on
`flask.g` for the request, so a page that asks for two companies reads each
company's books once.
"""
from datetime import date

import books_service
import deadlines
from tax_engine import compute

SCHEDULE_C = "schedule_c"
PARTNERSHIP = "partnership"


def kind_of(business):
    root = business.parent or business
    return PARTNERSHIP if len(list(root.owners or [])) > 1 else SCHEDULE_C


def tax_companies():
    """The companies that file: no DBA, which is its parent's money. The
    board company first, because it is the one most visits are about."""
    from models import Business
    rows = (Business.query.filter_by(is_active=True, parent_id=None)
            .order_by(Business.name, Business.id).all())
    board = books_service.board_business()
    return sorted(rows, key=lambda b: (0 if board is not None and b.id == board.id else 1,
                                       b.name.lower(), b.id))


def _michael_names():
    """First names and full names of every active CEO login, lower case."""
    from models import User
    names = set()
    for u in User.query.filter(User.is_active.is_(True),
                               User.role.in_(("ceo",) + User.LEGACY_CEO_ROLES)).all():
        first = (u.first_name or "").strip().lower()
        full = f"{first} {(u.last_name or '').strip().lower()}".strip()
        if first:
            names.add(first)
        if full:
            names.add(full)
    return names


def is_michael(owner_name, names=None):
    """Whether a member named on a company's paperwork is Michael: his CEO
    login's full name, or a first word that is his first name (or plainly
    Michael when no login says). "Hannah Bean" shares his surname and is
    never him, so a surname alone never matches."""
    text = " ".join((owner_name or "").lower().split())
    if not text:
        return False
    names = _michael_names() if names is None else names
    first = text.split(" ")[0]
    return text in names or first in names or first == "michael"


def michael_member(business, names=None):
    """(owner row, share as a fraction) for Michael in a partnership, or
    (None, 0.0) when he is not a member or his share is not on file."""
    root = business.parent or business
    names = _michael_names() if names is None else names
    for owner in root.owners or []:
        if is_michael(owner.name, names):
            return owner, max(0.0, (owner.share_percent or 0.0)) / 100.0
    return None, 0.0


def _summary(business, year):
    """books_service.summarize for the calendar year, once per request."""
    key = (business.id, year)
    try:
        from flask import g
        memo = g.setdefault("_income_tax_books", {})
    except RuntimeError:  # outside a request: no memo, still right
        memo = {}
    if key not in memo:
        memo[key] = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    return memo[key]


def _through(summary, today):
    """The year's net counting only what is dated on or before `today`."""
    income = sum(a for when, a, _ in summary["income"] if when <= today)
    spent = sum(e.amount for e in summary["expenses"] if e.date <= today)
    return round(income - spent, 2)


def _by_quarter(summary):
    out = {q: 0.0 for q in (1, 2, 3, 4)}
    for when, amount, _ in summary["income"]:
        out[(when.month - 1) // 3 + 1] += amount
    for e in summary["expenses"]:
        out[(e.date.month - 1) // 3 + 1] -= e.amount
    return {q: round(v, 2) for q, v in out.items()}


def _settings_kwargs(settings, year):
    return dict(filing_status=settings.filing_status, your_wages=settings.your_wages or 0.0,
                spouse_wages=settings.spouse_wages or 0.0, other_income=settings.other_income or 0.0,
                federal_withheld=settings.federal_withheld or 0.0,
                state_rate=settings.state_tax_rate or 0.0, year=year)


def estimate(business, year, today=None, *, settings=None, summary=None):
    """What `business`'s profit for `year` costs in income tax.

    `settings` (a TaxSetting) and `summary` (that company's summarize for the
    calendar year) may be handed in by a caller that already has them.

    Keys:
      business, year, kind   the company (a DBA asks for its parent), the year,
                             "schedule_c" or "partnership"
      income, expenses, net  the company's year off its books (summarize)
      michael_share          the fraction of `net` that is Michael's: 1 for a
                             Schedule C, his share for a partnership, 0 when
                             he is not a member
      profit                 his part of `net`: what this company puts on his
                             return
      tax                    the year's estimated income tax that profit costs
                             him (self employment, federal and state), on top
                             of his wages and of every company before it in
                             the stack; 0 when he is not a member or it lost
      effective              tax as a share of profit, 0..1
      set_aside              the same rate on the same profit dated through
                             `today`: what should be put away by now
      members                partnership only: [{name, share_percent, amount,
                             is_michael}], amount None when no share is on file
      quarters               [{quarter, label, due, profit, amount}] for the
                             four estimated payments: due from
                             deadlines.estimate_due, profit his part of that
                             quarter's net, amount the year's rate on it
      calc                   tax_engine.compute for the return with this
                             company in it (the working the page draws)
      base_profit            what the companies before it in the stack add
      personal               the whole return: {profit, tax, balance_due}
                             over every company Michael's return sees
    """
    from models import TaxSetting
    today = today or date.today()
    business = business.parent or business
    settings = settings or TaxSetting.get()
    kwargs = _settings_kwargs(settings, year)
    names = _michael_names()

    def books(company):
        if company.id == business.id and summary is not None:
            return summary
        return _summary(company, year)

    def share_of(company, kind):
        return 1.0 if kind == SCHEDULE_C else michael_member(company, names)[1]

    # Michael's part of every company his return sees: Schedule C companies
    # first, then partnership shares (a stable sort keeps the board first).
    stack = [(c, kind_of(c)) for c in tax_companies()]
    if not any(c.id == business.id for c, _ in stack):  # an inactive company, asked directly
        stack.append((business, kind_of(business)))
    stack = [(c, k, share_of(c, k)) for c, k in stack]
    stack = [row for row in stack if row[2] > 0 or row[0].id == business.id]
    stack.sort(key=lambda row: 0 if row[1] == SCHEDULE_C else 1)
    parts = [round(books(c)["net"] * share, 2) for c, _, share in stack]
    at = next(i for i, row in enumerate(stack) if row[0].id == business.id)
    _company, kind, share = stack[at]
    base, mine, total = round(sum(parts[:at]), 2), parts[at], round(sum(parts), 2)

    before = compute(base, **kwargs)
    with_it = compute(base + mine, **kwargs)
    whole = compute(total, **kwargs)
    tax = round(max(0.0, with_it["business_tax"] - before["business_tax"]), 2)
    effective = (tax / mine) if mine > 0 else 0.0

    year_books = books(business)
    quarters = []
    by_q = _by_quarter(year_books)
    for q in (1, 2, 3, 4):
        profit = round(by_q[q] * share, 2)
        quarters.append({"quarter": q, "label": f"Q{q}", "due": deadlines.estimate_due(year, q),
                         "profit": profit, "amount": round(max(0.0, profit) * effective, 2)})

    members = []
    if kind == PARTNERSHIP:
        for owner in business.owners or []:
            pct = owner.share_percent
            members.append({
                "name": owner.name,
                "share_percent": pct,
                "amount": None if pct is None else round(year_books["net"] * pct / 100.0, 2),
                "is_michael": is_michael(owner.name, names),
            })

    return {
        "business": business,
        "year": year,
        "kind": kind,
        "income": year_books["income_total"],
        "expenses": year_books["expense_total"],
        "net": year_books["net"],
        "michael_share": share,
        "profit": mine,
        "tax": tax,
        "effective": effective,
        "set_aside": round(max(0.0, _through(year_books, today) * share) * effective, 2),
        "members": members,
        "quarters": quarters,
        "calc": with_it,
        "base_profit": base,
        "personal": {"profit": total, "tax": round(whole["business_tax"], 2),
                     "balance_due": round(whole["balance_due"], 2)},
    }


def years_for(business, today=None):
    """The years worth offering for a company, newest first: from its first
    expense or its first date on file, to this year."""
    from models import Expense, db
    today = today or date.today()
    root = business.parent or business
    first = (db.session.query(db.func.min(Expense.date))
             .filter(Expense.business_id.in_(books_service.family_ids(root))).scalar())
    starts = [d for d in (first, root.conceived_on, root.formed_on, root.launched_on) if d]
    start = min(starts).year if starts else today.year
    start = max(start, today.year - 6)
    return list(range(today.year, start - 1, -1))
