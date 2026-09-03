"""What hosting earns against what hosting costs.

Every delivered application charges a recurring fee to stay online, and every
one of them runs on infrastructure somebody bills me for. Both halves already
existed and neither could see the other: the fee was typed into a statement of
work and printed into a PDF, and the cost arrived as a service cost entry
allocated to a project. Nothing held them side by side, so the only way to
discover a fee had been overtaken was to notice.

This is the page that notices. One row per project, the fee next to the cost,
sorted so the ones about to go underwater are at the top.

A project's cost is two things added together. Vendor charges arrive through
ServiceMapping.project_id - a mapping being the deliberate statement "this
Railway project belongs to that build", made once, and what the monthly entry
page writes against. Anything filed by hand straight onto a project counts too:
a Twilio number bought for one build, or an agent billed to it, is as much the
cost of running that build as its Railway bill is. Reading only the mapped half
meant a cost could be entered against a project and never reach the page that
asks what that project costs.

Expenses mirrored from a cost entry are counted once, on the mapped side. They
carry a project_id as well, so summing both without excluding them would double
every vendor charge on the page.

Client-level costs are deliberately out. Stripe's fee is attributed to a client
but to no project, and it tracks whatever that client was invoiced for - mostly
development work, at 2.9% of four-figure invoices. Counted as the cost of
running an application it would swamp a $50 hosting fee with the cost of
collecting money that has nothing to do with hosting.
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from models import (db, Client, Project, ServiceMapping, ServiceCostEntry,
                    ServiceProvider, Expense)

hosting_bp = Blueprint("hosting", __name__, url_prefix="/admin/hosting")


# What every hosted application has to clear, in dollars, after the
# infrastructure is paid for. A share of the fee was the wrong shape: 80% of
# $50 leaves $10 and 80% of $500 leaves $100, and those are not the same
# situation. The fee also has to cover the time spent keeping the thing
# alive, so the floor is a floor on the money left over, not on the ratio.
MIN_MARGIN = 25.0

# Charges that buy a year in one payment. A domain registration is the case:
# it arrives as a single invoice in the month it renews, and bucketing the
# whole thing into that month compares a year of cost against a month of fee.
# kuperplumbing.com renewed at $10.46 in August against a $50 monthly fee and
# read as $11.39 of cost; datadungeon.io renews at $50.00, which against a $50
# fee would have read as losing money for one month and recovering by itself
# the next. That spike-and-recover is the exact false alarm this page exists
# not to raise, so an annual charge is spread across the twelve months it
# actually buys.
#
# Only this comparison is annualised. The ledger keeps the real charge in the
# real month, so the books still agree with the card statement.
ANNUAL_PREFIXES = ("cloudflare-domain:",)
ANNUAL_MONTHS = 12


def _is_annual(resource_identifier):
    return (resource_identifier or "").startswith(ANNUAL_PREFIXES)


def _add_months(when, count):
    month = when.month - 1 + count
    return date(when.year + month // 12, month % 12 + 1, 1)


def _complete_months(count):
    """The last `count` complete calendar months, oldest first.

    The month in progress is left out. Three days into September, September has
    almost no cost recorded against it, and including it would make every
    project look comfortable for the first week of every month and alarming by
    the last.
    """
    cursor = date.today().replace(day=1)
    months = []
    for _ in range(count):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        months.append(cursor)
    return list(reversed(months))


def _costs_by_project(months):
    """Cost per project per month, as (total, the annualised part of it).

    Both are {project_id: {month_start: amount}}. The second is a subset of the
    first, kept apart only so a row can say how much of its cost is a yearly
    charge being spread rather than money that actually moved that month.

    Bucketed on period_end rather than period_start because providers do not
    agree on what a period is: a monthly entry spans the calendar month, a flat
    charge is the single day it landed, and AWS reports whatever window it
    reports. period_end is the one they all place inside the month the money
    belongs to, and it is what the mirrored expense is dated by.
    """
    if not months:
        return {}, {}
    window_start = months[0]
    wanted = set(months)

    # A year bought eleven months before the window is still paying for months
    # inside it, so annual charges have to be fetched from further back than
    # the window itself. Monthly entries from those extra months are filtered
    # out below by `wanted`.
    fetch_start = _add_months(window_start, -(ANNUAL_MONTHS - 1))

    rows = (db.session.query(ServiceMapping.project_id,
                             ServiceCostEntry.resource_identifier,
                             ServiceCostEntry.period_end,
                             ServiceCostEntry.allocated_amount)
            .join(ServiceCostEntry, ServiceCostEntry.mapping_id == ServiceMapping.id)
            .filter(ServiceMapping.project_id.isnot(None))
            .filter(ServiceCostEntry.period_end >= fetch_start)
            .all())

    out = {}
    annual = {}
    for project_id, resource_id, period_end, amount in rows:
        if period_end is None:
            continue
        month = period_end.replace(day=1)
        amount = amount or 0.0

        if _is_annual(resource_id):
            share = amount / ANNUAL_MONTHS
            covered = [_add_months(month, i) for i in range(ANNUAL_MONTHS)]
            spread = [(m, share) for m in covered if m in wanted]
            target = annual
        else:
            spread = [(month, amount)] if month in wanted else []
            target = None

        for m, value in spread:
            bucket = out.setdefault(project_id, {})
            bucket[m] = bucket.get(m, 0.0) + value
            if target is not None:
                bucket = target.setdefault(project_id, {})
                bucket[m] = bucket.get(m, 0.0) + value

    # The other half: costs filed straight onto a project, which never had a
    # mapping to arrive through. Dated by the expense rather than by a billing
    # period, because that is all a hand-entered cost has.
    #
    # Mirrored expenses are excluded by id. Every mapped cost entry writes one
    # and stamps it with the project, so counting both sides would double each
    # vendor charge the loop above just recorded.
    mirrored = (db.session.query(ServiceCostEntry.expense_id)
                .filter(ServiceCostEntry.expense_id.isnot(None)))
    direct = (db.session.query(Expense.project_id, Expense.date, Expense.amount)
              .filter(Expense.project_id.isnot(None))
              .filter(Expense.date >= window_start)
              .filter(Expense.id.notin_(mirrored))
              .all())
    for project_id, when, amount in direct:
        if when is None:
            continue
        first = when.replace(day=1)
        if first not in wanted:
            continue
        bucket = out.setdefault(project_id, {})
        bucket[first] = bucket.get(first, 0.0) + (amount or 0.0)

    return out, annual


def _status(fee, cost):
    """(key, label) for where this project sits, on last month's cost.

    One line, not a set of bands: either the fee clears the floor after the
    infrastructure is paid for, or it does not and is a fee to raise. The
    middle band that used to sit here was a second guess at the same question
    and said "Watch" about a project nobody was going to act on.

    An unpriced project cannot reach here - the page lists only what a contract
    has priced. A fee of nothing is still guarded, and reads as free hosting,
    because whether it is unset or agreed at zero the money recovered is the
    same and the page should say so rather than crash.
    """
    if not fee:
        return ("loss", "Hosted free")
    if cost <= 0:
        return ("fine", "No cost recorded")
    if cost >= fee:
        return ("loss", "Costs more than it earns")
    if fee - cost < MIN_MARGIN:
        return ("raise", "Raise it")
    return ("fine", "Fine")


def _bar(fee, cost):
    """Where the fill ends and where the floor sits, as percentages of the fee.

    The bar's full width is one month of fee, so the fill is what the
    infrastructure took out of it and the line is the point past which less
    than MIN_MARGIN is left. Fill is capped: a project costing more than it
    earns fills the bar and says so in red rather than running off the end.

    Both are None without a fee, because there is no width to measure against.
    A fee at or under the floor puts the line at zero, which is honest - every
    dollar of cost on that project is already below the floor.
    """
    if fee is None or fee <= 0:
        return None, None
    fill = min(max(cost, 0.0) / fee * 100.0, 100.0)
    line = max((fee - MIN_MARGIN) / fee * 100.0, 0.0)
    return round(fill, 2), round(line, 2)


def _railway_lifetime_by_project():
    """Railway cost per project, and the first month any of it was attributed.

    Returns ({project_id: total}, earliest month or None). The month is not
    decoration. Per-project Railway figures start in August 2026; every month
    before that was one flat charge with no project on it, so a per-client
    total here covers less history than the lifetime figure at the top of the
    page and would otherwise read as though a client had cost almost nothing
    since the beginning.
    """
    rows = (db.session.query(ServiceMapping.project_id,
                             ServiceCostEntry.period_start,
                             ServiceCostEntry.allocated_amount)
            .join(ServiceCostEntry, ServiceCostEntry.mapping_id == ServiceMapping.id)
            .join(ServiceProvider, ServiceProvider.id == ServiceCostEntry.provider_id)
            .filter(ServiceProvider.name == "railway")
            .filter(ServiceMapping.project_id.isnot(None))
            .all())
    totals, earliest = {}, None
    for project_id, period_start, amount in rows:
        totals[project_id] = totals.get(project_id, 0.0) + (amount or 0.0)
        if period_start and (earliest is None or period_start < earliest):
            earliest = period_start
    return totals, earliest


def _railway_all_time():
    """Every dollar Railway has cost, across every month on record.

    Matched on the description prefix rather than by joining the cost entries,
    because half of this money has no cost entry to join to. Per-project
    figures only start in August 2026; before that Railway was a single flat
    expense a month, and a lifetime total that skipped those would be missing
    two thirds of the months. Every Railway expense carries the provider's
    display name as its prefix, and nothing else does.
    """
    provider = ServiceProvider.query.filter_by(name="railway").first()
    if provider is None:
        return 0.0
    total = (db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0.0))
             .filter(Expense.description.ilike(f"{provider.display_name} -%"))
             .scalar())
    return float(total or 0.0)


# Worst first. A page whose whole job is to surface the two projects that need
# attention should not open on the eleven that do not.
STATUS_ORDER = {"loss": 0, "raise": 1, "fine": 2}


@hosting_bp.route("/")
@login_required
def hosting_index():
    # One month, the last complete one. The average that used to sit beside it
    # was answering a different question - whether an expensive month was a
    # one-off - and a bar can only draw one number. Annual charges are spread
    # across the months they cover, so the spikes the average existed to
    # absorb are already gone by the time the cost gets here.
    months = _complete_months(1)
    month = months[-1]
    costs, annualised = _costs_by_project(months)

    projects = (Project.query.join(Client, Project.client_id == Client.id)
                .order_by(Client.name, Project.name).all())

    # Read before the loop, so each row can carry its own running total beside
    # the month's bar.
    from stripe_service import get_hosting_revenue
    hosting = get_hosting_revenue()
    paid_by_customer = hosting["by_customer"]
    railway_lifetime, railway_since = _railway_lifetime_by_project()

    # Hosting money belongs to a client, not to a project. A client running two
    # builds would otherwise show their whole hosting history against each of
    # them, and the two rows would look like twice the revenue.
    projects_per_client = {}
    for p in projects:
        projects_per_client[p.client_id] = projects_per_client.get(p.client_id, 0) + 1

    rows = []
    for p in projects:
        # Priced by a contract, or it does not belong here. A statement of
        # work and a hosting agreement both write the fee onto the project,
        # so appearing on this page is what having agreed one looks like.
        # A project hosted without an agreement is a contract to write, not a
        # fee to type into this screen, and offering to type it here was an
        # invitation to have the number in two places and a document for
        # neither.
        if p.hosting_fee is None:
            continue
        by_month = costs.get(p.id, {})
        cost = by_month.get(month, 0.0)
        fee = p.monthly_hosting_fee
        key, label = _status(fee, cost)
        fill_pct, line_pct = _bar(fee, cost)

        paid = paid_by_customer.get(
            (p.client.stripe_customer_id if p.client else None) or "", {})
        collected = paid.get("collected", 0.0)
        railway = railway_lifetime.get(p.id, 0.0)

        rows.append({
            "project": p,
            "fee": fee,
            "raw_fee": p.hosting_fee,
            "cycle": p.hosting_cycle or "monthly",
            "cost": cost,
            "annual_share": annualised.get(p.id, {}).get(month, 0.0),
            "margin": (fee - cost) if fee is not None else None,
            "fill_pct": fill_pct,
            "line_pct": line_pct,
            "status": key,
            "status_label": label,
            # The same question the tiles ask, asked about one client.
            "life": {
                "collected": collected,
                "outstanding": paid.get("outstanding", 0.0),
                "railway": railway,
                "margin": collected - railway,
                "shared": projects_per_client.get(p.client_id, 1) > 1,
            },
        })

    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9),
                             -(r["cost"] or 0), r["project"].name.lower()))

    totals = {
        "needs_attention": sum(1 for r in rows if r["status"] in ("loss", "raise")),
    }

    # The lifetime question, which is a different one from the month's. The
    # bars ask whether each fee still covers its own infrastructure; this asks
    # whether hosting has been worth doing at all. Revenue comes from Stripe
    # rather than from the fees on the projects, because a fee is what was
    # agreed and a paid invoice is what arrived - Kuper's subscription is past
    # due as this is written, and a total built from the agreed fees would show
    # that money as earned.
    lifetime = {
        "collected": hosting["collected"],
        "outstanding": hosting["outstanding"],
        "paid_invoices": hosting["paid_invoices"],
        "railway": _railway_all_time(),
    }
    lifetime["margin"] = lifetime["collected"] - lifetime["railway"]

    return render_template("pm/hosting/index.html",
                           rows=rows, month=month, totals=totals,
                           lifetime=lifetime, min_margin=MIN_MARGIN,
                           railway_since=railway_since)
