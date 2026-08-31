"""A tax estimate over what Stripe actually paid out.

Arithmetic, not advice. Every rate is one the user typed, and the page shows
two answers side by side rather than one, because the two questions people
mean by "what do I owe" have materially different answers:

  set aside      a share of each payment as it lands. Sits on gross receipts,
                 ignores every deduction, and therefore over-collects. Its
                 virtue is that it needs no bookkeeping to be useful.

  estimated      a share of profit, being what Stripe paid out less the
                 expenses already tracked here. Closer to a real liability and
                 only as good as the expense ledger behind it.

Income comes from Stripe balance transactions rather than invoices, so refunds
subtract and fees are already netted off. That makes these figures agree with
the bank rather than with what was billed.
"""
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from models import db, Client, Expense, TaxSetting
from stripe_service import get_stripe_income_transactions

tax_bp = Blueprint("taxes", __name__, url_prefix="/admin/pm/taxes")

# US estimated payments are due the month after each quarter closes, and Q4's
# lands in the following January. Shown so a quarter's number arrives with the
# date it matters by.
_QUARTER_DUE = {1: (4, 15), 2: (6, 15), 3: (9, 15), 4: (1, 15)}


def _quarter(when):
    return (when.month - 1) // 3 + 1


def _due_date(year, quarter):
    month, day = _QUARTER_DUE[quarter]
    return date(year + 1 if quarter == 4 else year, month, day)


def _rate(field, current, minimum=0.0, maximum=100.0):
    """Read a percentage off the form, keeping the old value if it is unusable."""
    raw = (request.form.get(field) or "").strip()
    if not raw:
        return current
    try:
        return min(maximum, max(minimum, float(raw)))
    except ValueError:
        return current


@tax_bp.route("/", methods=["GET", "POST"])
@login_required
def taxes_index():
    settings = TaxSetting.get()

    if request.method == "POST":
        settings.set_aside_rate = _rate("set_aside_rate", settings.set_aside_rate)
        settings.self_employment_rate = _rate("self_employment_rate", settings.self_employment_rate)
        settings.income_tax_rate = _rate("income_tax_rate", settings.income_tax_rate)
        settings.state_tax_rate = _rate("state_tax_rate", settings.state_tax_rate)
        db.session.commit()
        flash("Tax rates saved.", "success")
        return redirect(url_for("taxes.taxes_index", year=request.args.get("year", "")))

    transactions = get_stripe_income_transactions()
    years = sorted({t["date"].year for t in transactions if t["date"]}, reverse=True)
    year = request.args.get("year", type=int) or (years[0] if years else date.today().year)

    client_names = {
        c.stripe_customer_id: c.name
        for c in Client.query.filter(Client.stripe_customer_id.isnot(None)).all()
    }

    set_aside_rate = (settings.set_aside_rate or 0) / 100.0
    profit_rate = (settings.profit_rate or 0) / 100.0

    rows = []
    for t in transactions:
        if not t["date"] or t["date"].year != year:
            continue
        row = dict(t)
        row["client_name"] = client_names.get(t["customer_id"]) or t["customer_id"] or "-"
        # A refund is negative, so its set aside is negative too and gives back
        # what the original payment put away.
        row["set_aside"] = round(t["net"] * set_aside_rate, 2)
        row["quarter"] = _quarter(t["date"])
        rows.append(row)
    rows.reverse()  # newest first for reading; the source list is oldest first

    # Expenses are the app's own, not Stripe's, and only material ones: a
    # billable-time expense is the mirror of revenue, not a cost of trading.
    expenses_by_quarter = {}
    for e in Expense.query.filter(Expense.time_entry_id.is_(None)).all():
        if e.date and e.date.year == year:
            q = _quarter(e.date)
            expenses_by_quarter[q] = expenses_by_quarter.get(q, 0.0) + (e.amount or 0)

    quarters = []
    for q in (1, 2, 3, 4):
        in_q = [r for r in rows if r["quarter"] == q]
        gross = sum(r["gross"] for r in in_q)
        fees = sum(r["fee"] for r in in_q)
        net = sum(r["net"] for r in in_q)
        spend = expenses_by_quarter.get(q, 0.0)
        profit = net - spend
        if not in_q and not spend:
            continue
        quarters.append({
            "quarter": q,
            "label": f"Q{q}",
            "due": _due_date(year, q),
            "count": len(in_q),
            "gross": gross,
            "fees": fees,
            "net": net,
            "expenses": spend,
            "profit": profit,
            "set_aside": sum(r["set_aside"] for r in in_q),
            # Profit can be negative in a quarter that spent more than it took.
            # Tax on a loss is zero, not a refund this page is entitled to imply.
            "estimated": round(max(0.0, profit) * profit_rate, 2),
        })

    totals = {
        "count": len(rows),
        "gross": sum(r["gross"] for r in rows),
        "fees": sum(r["fee"] for r in rows),
        "net": sum(r["net"] for r in rows),
        "expenses": sum(expenses_by_quarter.values()),
        "set_aside": sum(r["set_aside"] for r in rows),
        "estimated": sum(q["estimated"] for q in quarters),
    }
    totals["profit"] = totals["net"] - totals["expenses"]
    totals["effective_on_gross"] = (
        (totals["estimated"] / totals["gross"] * 100) if totals["gross"] else 0.0
    )

    return render_template("pm/taxes/index.html",
        settings=settings,
        transactions=rows,
        quarters=quarters,
        totals=totals,
        year=year,
        years=years or [year],
        today=date.today(),
    )
