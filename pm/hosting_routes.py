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
Railway project belongs to that build", made once, and what a vendor's report
(pulled, or typed on the Railway months tab) is recorded against. Anything
filed by hand straight onto a project counts too: a Twilio number bought for
one build, or an agent billed to it, is as much the cost of running that build
as its Railway bill is. Reading only the mapped half meant a cost could be
entered against a project and never reach the page that asks what that project
costs.

Only the bank line is an expense (docs/finances_plan.md item 5). A vendor's
report records what each project cost and splits the bank's charge across them
(bank_feed.split), so each share carries a project_id AND the cost entry it
came from (Expense.cost_entry_id). Those are counted once, on the mapped side,
as are the expenses the old sync wrote before the bank took over
(ServiceCostEntry.expense_id); summing both sides would double every vendor
charge on the page.

These pages are the Hosting section of Finances: Fees (this page), Mappings,
Railway months and Vendors (pm/service_costs_routes.py), one tab row over all
of them (templates/pm/hosting/_tabs.html). CEO only, like every money page.

Client-level costs are deliberately out. Stripe's fee is attributed to a client
but to no project, and it tracks whatever that client was invoiced for - mostly
development work, at 2.9% of four-figure invoices. Counted as the cost of
running an application it would swamp a $50 hosting fee with the cost of
collecting money that has nothing to do with hosting.
"""
import time
from datetime import date, timedelta

from flask import Blueprint, render_template, request, url_for, redirect, flash, abort, current_app, has_app_context
import hosting_billing
from pm.users_routes import ceo_required

import contract_docs
from models import (db, Client, Project, ServiceMapping, ServiceCostEntry, ProviderInvoice,
                    ServiceProvider, Expense)

hosting_bp = Blueprint("hosting", __name__, url_prefix="/admin/hosting")


# What every hosted application has to clear, in dollars, after the
# infrastructure is paid for. A share of the fee was the wrong shape: 80% of
# $50 leaves $10 and 80% of $500 leaves $100, and those are not the same
# situation. The fee also has to cover the time spent keeping the thing
# alive, so the floor is a floor on the money left over, not on the ratio.
MIN_MARGIN = 25.0

# What a fee goes up by, per month, when it stops clearing the floor. A flat
# step rather than a recalculation: the client reads "twenty-five dollars
# more", which is a sentence, where a recomputed figure is an argument. If
# one step is not enough the page says so again next month.
RAISE_STEP = 25.0


def _next_month_start():
    return _add_months(date.today().replace(day=1), 1)


def _increase_for(project, raw_fee, cycle):
    """The fee update this project is due, and the link that drafts it.

    The draft opens the hosting agreement form filled in - client, project,
    the new fee, the fee it cancels, the first of next month as the day it
    starts, and the reason - so that what is left to do is read it and send
    it. Nothing here writes to the project: the fee lands on it the day the
    agreement goes out, through the same route every hosting agreement uses.
    """
    months = Project.HOSTING_CYCLE_MONTHS.get(cycle or "monthly", 1)
    new_fee = (raw_fee or 0.0) + RAISE_STEP * months
    effective = _next_month_start()
    # The link's ingredients rather than the link: this also feeds a cached
    # list read from the sidebar's context processor, and url_for needs a
    # request to build against. increase_url() turns them into the link
    # wherever there is one.
    return {
        "new_fee": new_fee,
        "new_monthly": new_fee / months,
        "effective": effective,
        "args": dict(
            client_id=project.client_id, project_id=project.id,
            application=project.name, fee=f"{new_fee:g}",
            cycle=cycle or "monthly", previous_fee=f"{(raw_fee or 0.0):g}",
            effective=effective.isoformat(), start_date=effective.isoformat(),
            reason=contract_docs.HOSTING_RAISE_REASON),
    }


def increase_url(increase):
    return url_for("contracts.hosting_form", **increase["args"])


# The sidebar asks on every page how many fees need raising, and the answer
# only changes when a month closes or a cost lands, so it is held for ten
# minutes rather than recomputed on every click. Plain dicts, not rows: an
# ORM object cached across requests is detached from every later session.
_DUE_CACHE = {"at": 0.0, "rows": []}
DUE_TTL_SECONDS = 600


def _mapped_projects():
    """Projects some vendor's costs arrive through: an active ServiceMapping."""
    return {pid for (pid,) in db.session.query(ServiceMapping.project_id)
            .filter(ServiceMapping.project_id.isnot(None), ServiceMapping.is_active.is_(True)).all()}


def _billing_snapshot():
    """Stripe's hosting subscriptions as last read, never waiting on Stripe:
    the badge is built on every page (hosting_billing.snapshot)."""
    app = current_app._get_current_object() if has_app_context() else None
    return hosting_billing.snapshot(app)


# The bands the tile and the badge count, besides a client's billing.
COUNTED = ("loss", "raise", "unmapped")


# A project nobody has signed for has no hosting agreement, whatever fee it
# carries: Robinson & Co. sat on the page as "Hosted free" (Michael,
# 2026-11-05: "should not even show up").
UNDER_CONTRACT = db.or_(Project.phase.is_(None), Project.phase != "not_contracted")


def _priced_projects():
    return (Project.query.join(Client, Project.client_id == Client.id)
            .filter(Project.hosting_fee.isnot(None), UNDER_CONTRACT)
            .order_by(Client.name, Project.name, Project.id).all())


def hosting_rows(billing_data, months=None):
    """THE reading of the Hosting page: one row per priced project, with its
    band, its billing (said once per client, on its first row) and how many
    things on it ask to be looked at. The page draws these and the sidebar
    badge counts them, so the two cannot disagree (rule "Badges that match
    their page": a reading shown in two places is one function both call).

    `billing_data` is Stripe's answer (hosting_billing): the page passes a
    fresh read, the badge the last one, and the page leaves its count in the
    badge's cache so the two agree on the same answer."""
    months = months or _complete_months(1)
    month = months[-1]
    costs, annualised = _costs_by_project(months)
    mapped = _mapped_projects()
    priced = _priced_projects()
    billing = hosting_billing.by_client(priced, billing_data)
    billed_once = set()
    rows = []
    for p in priced:
        cost = costs.get(p.id, {}).get(month, 0.0)
        fee = p.monthly_hosting_fee
        key, label = _status(fee, cost, p.id in mapped)
        bill = billing.get(p.client_id)
        if bill is not None and p.client_id in billed_once:
            bill = None
        elif bill is not None:
            billed_once.add(p.client_id)
        increase = (_increase_for(p, p.hosting_fee, p.hosting_cycle)
                    if key in ("loss", "raise") else None)
        rows.append({
            "project": p, "fee": fee, "raw_fee": p.hosting_fee,
            "cycle": p.hosting_cycle or "monthly", "cost": cost,
            "annual_share": annualised.get(p.id, {}).get(month, 0.0),
            "margin": (fee - cost) if fee is not None else None,
            "status": key, "status_label": label, "bill": bill, "increase": increase,
            "counted": (1 if key in COUNTED else 0)
            + (1 if bill and bill["state"] != "ok" else 0),
        })
    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9),
                             -(r["cost"] or 0), r["project"].name.lower()))
    return rows, month


def _due(rows):
    """What the badge keeps: one plain dict per thing counted. Plain dicts,
    not rows: an ORM object cached across requests is detached from every
    later session."""
    out = []
    for r in rows:
        p = r["project"]
        base = {"project_id": p.id, "project_name": p.name,
                "client_name": p.client.name if p.client else "",
                "fee": r["fee"] or 0.0, "cost": r["cost"], "margin": (r["fee"] or 0.0) - r["cost"]}
        if r["bill"] and r["bill"]["state"] != "ok":
            out.append(dict(base, status="billing", label=r["bill"]["state"], args=None))
        if r["status"] in COUNTED:
            inc = r["increase"] or {}
            out.append(dict(base, status=r["status"], label=r["status_label"],
                            new_monthly=inc.get("new_monthly"), args=inc.get("args")))
    return out


def increases_due():
    """Everything the badge counts, from hosting_rows on Stripe's last answer
    (never waiting on Stripe: this runs on every page). Cached ten minutes,
    and replaced by the page whenever the page is drawn."""
    now = time.monotonic()
    if now - _DUE_CACHE["at"] < DUE_TTL_SECONDS:
        return _DUE_CACHE["rows"]
    rows, _ = hosting_rows(_billing_snapshot())
    _DUE_CACHE.update(at=now, rows=_due(rows))
    return _DUE_CACHE["rows"]


def increases_due_count():
    return len(increases_due())


def tab_counts():
    """The counts on the Hosting tab row, each the same reading its tab's page
    draws: Fees is the badge's count (hosting_rows), Railway months the months
    with no bill (provider_bills.missing_bills, which Needs attention lists
    too), Vendors the vendors whose sync is in trouble. Asked by every page
    in the section, because the row is carried across a tab press and takes
    its counts from the page that arrived."""
    import provider_bills
    from pm.service_costs_routes import sync_trouble
    try:
        bills = sum(b["count"] for b in provider_bills.missing_bills())
        vendors = len(sync_trouble(ServiceProvider.query.all()))
    except Exception:
        db.session.rollback()
        bills = vendors = 0
    return {"fees": increases_due_count(), "bills": bills, "vendors": vendors}


@hosting_bp.context_processor
def _hosting_tabs():
    return {"hosting_counts": tab_counts}


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
    belongs to.
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
    # Expenses that stand for a cost entry are excluded: one the old sync
    # wrote (by id) and a bank line's share of a vendor row (by cost_entry_id).
    # Both carry the project, so counting them here would double each vendor
    # charge the loop above just recorded.
    mirrored = (db.session.query(ServiceCostEntry.expense_id)
                .filter(ServiceCostEntry.expense_id.isnot(None)))
    direct = (db.session.query(Expense.project_id, Expense.date, Expense.amount)
              .filter(Expense.project_id.isnot(None))
              .filter(Expense.date >= window_start)
              .filter(Expense.id.notin_(mirrored))
              # A bank line's share of a vendor row (bank_feed.split) is that
              # row's cost, counted above through its mapping.
              .filter(Expense.cost_entry_id.is_(None))
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


def _status(fee, cost, mapped=True):
    """(key, label) for where this project sits, on last month's cost.

    One line, not a set of bands: either the fee clears the floor after the
    infrastructure is paid for, or it does not and is a fee to raise. The
    middle band that used to sit here was a second guess at the same question
    and said "Watch" about a project nobody was going to act on.

    An unpriced project cannot reach here - the page lists only what a contract
    has priced. A fee of nothing is still guarded, and reads as free hosting,
    because whether it is unset or agreed at zero the money recovered is the
    same and the page should say so rather than crash.

    Free hosting is its OWN band and not a loss. It was a loss once, so a
    project deliberately hosted for nothing and costing nothing to run was
    counted on the Needs a look tile and in the sidebar badge, while its row
    said "Hosted free" and offered no press: the page asked to be looked at
    and then had nothing to show. Nothing is owed on nothing. It becomes a
    loss the moment it actually costs something, because free to the client
    was never meant to mean paid for out of pocket.
    """
    if not fee:
        return ("loss", "Free, and it costs") if cost > 0 else ("free", "Hosted free")
    if cost <= 0:
        # Nothing recorded and nothing to record it through. This read "Fine"
        # until 2026-11-04 (audit item 7), so a priced build with no mapping
        # sat out of the badge showing a full margin. Not mapped is its own
        # band, counted, and offers the press that maps it.
        return ("fine", "No cost recorded") if mapped else ("unmapped", "Not mapped")
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
    """{project_id: every dollar of Railway attributed to it}.

    Covers less history than the lifetime total at the top of the page, and
    knowingly. Per-project Railway figures start in August 2026; every month
    before that was one flat charge with no project on it, counted in the
    total above but impossible to split between clients.
    """
    rows = (db.session.query(ServiceMapping.project_id,
                             ServiceCostEntry.allocated_amount)
            .join(ServiceCostEntry, ServiceCostEntry.mapping_id == ServiceMapping.id)
            .join(ServiceProvider, ServiceProvider.id == ServiceCostEntry.provider_id)
            .filter(ServiceProvider.name == "railway")
            .filter(ServiceMapping.project_id.isnot(None))
            .all())
    totals = {}
    for project_id, amount in rows:
        totals[project_id] = totals.get(project_id, 0.0) + (amount or 0.0)
    return totals


def _railway_all_time():
    """Every dollar Railway has cost, and where that number came from.

    Returns {"amount", "source", "months"}.

    It used to sum every expense whose description began with the provider's
    display name. TWO different things wrote those: the flat monthly charge
    from before per-project figures existed, and the old sync, which wrote one
    expense per project per month before only the bank line made expenses.
    Both match the prefix, so a month holding both was counted twice and the
    page read $231.65 against $136.90 of real invoices. The docstring even said the two populations existed; the fix it
    chose added them together.

    A derived total was the wrong SHAPE of answer, not a wrong sum. The
    invoice is the one number the vendor actually charged, there is exactly
    one per month, and it is recorded on the Railway months tab (or pulled). The old sum
    stays only as a fallback for a board with nothing entered yet, and the
    tile says which of the two it is showing rather than presenting a guess
    as a fact.
    """
    # Built by Bean's own Railway account. EntertainHQ's workspace is a second
    # Railway provider since 2026-11-01, and its bill is EntertainHQ LLC's.
    provider = (ServiceProvider.query
                .filter_by(name="railway", account_client_id=None, account_business_id=None)
                .order_by(ServiceProvider.id).first())
    if provider is None:
        return {"amount": 0.0, "source": "none", "months": 0}
    recorded = (db.session.query(db.func.coalesce(db.func.sum(ProviderInvoice.amount), 0.0),
                                 db.func.count(ProviderInvoice.id))
                .filter(ProviderInvoice.provider_id == provider.id).first())
    total, months = float(recorded[0] or 0.0), int(recorded[1] or 0)
    if months:
        return {"amount": total, "source": "invoices", "months": months}
    derived = (db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0.0))
               .filter(Expense.description.ilike(f"{provider.display_name} -%"))
               .scalar())
    return {"amount": float(derived or 0.0), "source": "derived", "months": 0}


# Worst first. A page whose whole job is to surface the two projects that need
# attention should not open on the eleven that do not.
# Sorted by how much it wants doing about it. Free hosting sits below Fine:
# a fee that covers its costs is at least earning, and one nobody is being
# charged is the row least likely to need anybody today.
STATUS_ORDER = {"loss": 0, "raise": 1, "unmapped": 2, "fine": 3, "free": 4}


@hosting_bp.route("/")
@ceo_required
def hosting_index():
    # One month, the last complete one. The average that used to sit beside it
    # was answering a different question - whether an expensive month was a
    # one-off - and a bar can only draw one number. Annual charges are spread
    # across the months they cover, so the spikes the average existed to
    # absorb are already gone by the time the cost gets here.
    # What Stripe bills against what was agreed, read now: this is the page,
    # so it may wait on Stripe where the badge may not.
    rows, month = hosting_rows(hosting_billing.current())
    # The badge reads the same answer the page just drew.
    _DUE_CACHE.update(at=time.monotonic(), rows=_due(rows))

    # Read before the loop, so each row can carry its own running total beside
    # the month's bar.
    from stripe_service import get_hosting_revenue
    hosting = get_hosting_revenue()
    paid_by_customer = hosting["by_customer"]
    railway_lifetime = _railway_lifetime_by_project()

    # Hosting money belongs to a client, not to a project. A client running two
    # builds would otherwise show their whole hosting history against each of
    # them, and the two rows would look like twice the revenue.
    projects_per_client = {}
    for r in rows:
        cid = r["project"].client_id
        projects_per_client[cid] = projects_per_client.get(cid, 0) + 1

    for r in rows:
        # Only priced projects reach here: a statement of work and a hosting
        # agreement both write the fee onto the project, so appearing on this
        # page is what having agreed one looks like.
        p = r["project"]
        r["fill_pct"], r["line_pct"] = _bar(r["fee"], r["cost"])
        r["map_url"] = (url_for("service_costs.mapping_create", project_id=p.id)
                        if r["status"] == "unmapped" else None)
        # Under the floor, so a fee update is due: what it becomes, and the
        # link that drafts the agreement saying so.
        if r["increase"]:
            r["increase"] = dict(r["increase"], url=increase_url(r["increase"]))
        paid = paid_by_customer.get((p.client.stripe_customer_id if p.client else None) or "", {})
        collected = paid.get("collected", 0.0)
        railway = railway_lifetime.get(p.id, 0.0)
        # The same question the tiles ask, asked about one client.
        r["life"] = {
            "collected": collected,
            "outstanding": paid.get("outstanding", 0.0),
            "railway": railway,
            "margin": collected - railway,
            "shared": projects_per_client.get(p.client_id, 1) > 1,
        }

    totals = {"needs_attention": sum(r["counted"] for r in rows)}

    # The lifetime question, which is a different one from the month's. The
    # bars ask whether each fee still covers its own infrastructure; this asks
    # whether hosting has been worth doing at all. Revenue comes from Stripe
    # rather than from the fees on the projects, because a fee is what was
    # agreed and a paid invoice is what arrived - Kuper's subscription is past
    # due as this is written, and a total built from the agreed fees would show
    # that money as earned.
    railway_lifetime_total = _railway_all_time()
    lifetime = {
        "collected": hosting["collected"],
        "outstanding": hosting["outstanding"],
        "paid_invoices": hosting["paid_invoices"],
        "railway": railway_lifetime_total["amount"],
        "railway_source": railway_lifetime_total["source"],
        "railway_months": railway_lifetime_total["months"],
    }
    lifetime["margin"] = lifetime["collected"] - lifetime["railway"]

    return render_template("pm/hosting/index.html",
                           rows=rows, month=month, totals=totals,
                           lifetime=lifetime, min_margin=MIN_MARGIN)


@hosting_bp.route("/billing/<int:client_id>", methods=["POST"])
@ceo_required
def billing_change(client_id):
    """Move the client's one hosting subscription item to the agreed fee,
    from the next cycle. The page asked first; this is the doing."""
    client = db.session.get(Client, client_id) or abort(404)
    projects = Project.query.filter(Project.client_id == client.id,
                                    Project.hosting_fee.isnot(None), UNDER_CONTRACT).all()
    bill = hosting_billing.by_client(projects, hosting_billing.current(ttl=0)).get(client.id)
    if not bill or not bill["changeable"]:
        flash(f"Nothing to change for {client.name}: Stripe already bills what was agreed, "
              f"or there is more than one hosting item to choose between.", "warning")
        return redirect(url_for("hosting.hosting_index"))
    error = hosting_billing.change(bill["items"][0], bill["agreed"])
    if error:
        flash(f"Stripe did not take it: {error}", "danger")
    else:
        _DUE_CACHE.update(at=0.0)
        flash(f"{client.name} is billed ${bill['agreed']:,.2f} a month from the next cycle.", "success")
    return redirect(url_for("hosting.hosting_index"))
