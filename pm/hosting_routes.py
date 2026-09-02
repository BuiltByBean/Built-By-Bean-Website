"""What hosting earns against what hosting costs.

Every delivered application charges a recurring fee to stay online, and every
one of them runs on infrastructure somebody bills me for. Both halves already
existed and neither could see the other: the fee was typed into a statement of
work and printed into a PDF, and the cost arrived as a service cost entry
allocated to a project. Nothing held them side by side, so the only way to
discover a fee had been overtaken was to notice.

This is the page that notices. One row per project, the fee next to the cost,
sorted so the ones about to go underwater are at the top.

Costs come through ServiceMapping.project_id rather than through the expense's
own project_id. A mapping is the deliberate statement "this Railway project
belongs to that build", made once, and it is what the monthly entry page writes
against. An expense's project is whatever it was filed under.
"""
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from models import db, Client, Project, ServiceMapping, ServiceCostEntry

hosting_bp = Blueprint("hosting", __name__, url_prefix="/admin/hosting")


# How much of the fee the infrastructure is allowed to eat before this page
# starts saying something. Not a policy, a tripwire: the fee also has to cover
# the time spent keeping the thing alive, so cost approaching fee is already
# a loss, and the point of the middle band is to see it coming a month or two
# out rather than the month it happens.
WATCH_AT = 0.60
RAISE_AT = 0.80


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
    """{project_id: {month_start: cost}} over the given months.

    Bucketed on period_end rather than period_start because providers do not
    agree on what a period is: a monthly entry spans the calendar month, a flat
    charge is the single day it landed, and AWS reports whatever window it
    reports. period_end is the one they all place inside the month the money
    belongs to, and it is what the mirrored expense is dated by.
    """
    if not months:
        return {}
    window_start = months[0]
    wanted = set(months)

    rows = (db.session.query(ServiceMapping.project_id,
                             ServiceCostEntry.period_end,
                             ServiceCostEntry.allocated_amount)
            .join(ServiceCostEntry, ServiceCostEntry.mapping_id == ServiceMapping.id)
            .filter(ServiceMapping.project_id.isnot(None))
            .filter(ServiceCostEntry.period_end >= window_start)
            .all())

    out = {}
    for project_id, period_end, amount in rows:
        if period_end is None:
            continue
        month = period_end.replace(day=1)
        if month not in wanted:
            continue
        out.setdefault(project_id, {})[month] = (
            out.setdefault(project_id, {}).get(month, 0.0) + (amount or 0.0))
    return out


def _status(fee, cost):
    """(key, label) for where this project sits.

    Judged on the worse of last month and the average, because those two answer
    different questions and both matter. A single expensive month is the signal
    to look now; a rising average is the signal that it was not a one-off.
    Waiting for the average to confirm what last month already showed costs
    two more months of it.
    """
    if fee is None:
        return ("unpriced", "No fee set")
    if cost <= 0:
        return ("fine", "No cost recorded")
    if fee <= 0:
        return ("loss", "Hosted free")
    ratio = cost / fee
    if ratio >= 1:
        return ("loss", "Costs more than it earns")
    if ratio >= RAISE_AT:
        return ("raise", "Raise it")
    if ratio >= WATCH_AT:
        return ("watch", "Watch")
    return ("fine", "Fine")


# Worst first. A page whose whole job is to surface the two projects that need
# attention should not open on the eleven that do not.
STATUS_ORDER = {"loss": 0, "raise": 1, "watch": 2, "unpriced": 3, "fine": 4}


@hosting_bp.route("/")
@login_required
def hosting_index():
    months = _complete_months(request.args.get("months", 3, type=int) or 3)
    costs = _costs_by_project(months)

    projects = (Project.query.join(Client, Project.client_id == Client.id)
                .order_by(Client.name, Project.name).all())

    rows = []
    for p in projects:
        by_month = costs.get(p.id, {})
        # Averaged over the months that actually recorded something, not over
        # the whole window. A project deployed six weeks ago has one month of
        # history, and dividing it by three would report a third of its cost.
        recorded = [by_month[m] for m in months if m in by_month]
        if not recorded and p.hosting_fee is None:
            # Nothing charged, nothing spent, nothing to say.
            continue
        last = by_month.get(months[-1], 0.0) if months else 0.0
        average = sum(recorded) / len(recorded) if recorded else 0.0
        fee = p.monthly_hosting_fee
        key, label = _status(fee, max(last, average))
        rows.append({
            "project": p,
            "fee": fee,
            "raw_fee": p.hosting_fee,
            "cycle": p.hosting_cycle or "monthly",
            "last": last,
            "average": average,
            "months_recorded": len(recorded),
            "series": [by_month.get(m, 0.0) for m in months],
            "margin": (fee - max(last, average)) if fee is not None else None,
            "status": key,
            "status_label": label,
        })

    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9),
                             -(r["last"] or 0), r["project"].name.lower()))

    priced = [r for r in rows if r["fee"] is not None]
    totals = {
        "fee": sum(r["fee"] for r in priced),
        # Every project's cost, priced or not: infrastructure for something
        # nobody is being charged for is still money going out the door.
        "cost": sum(max(r["last"], r["average"]) for r in rows),
        "needs_attention": sum(1 for r in rows if r["status"] in ("loss", "raise")),
        "unpriced": sum(1 for r in rows if r["status"] == "unpriced"),
    }
    totals["margin"] = totals["fee"] - totals["cost"]

    return render_template("pm/hosting/index.html",
                           rows=rows, months=months, totals=totals,
                           watch_at=int(WATCH_AT * 100), raise_at=int(RAISE_AT * 100))
