"""A tax estimate over what Stripe actually paid out.

Facts in, working out. The user supplies filing status, wages and withholding;
`tax_engine` does brackets, the standard deduction, QBI and self employment
tax, and the page shows its own arithmetic so the number can be checked rather
than taken on faith.

Income comes from Stripe balance transactions rather than invoices, so refunds
subtract and fees are already netted off. These figures agree with the bank
rather than with what was billed, which is the right basis for tax.
"""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from models import db, Client, Expense, TaxSetting
from stripe_service import get_stripe_income_transactions
from tax_engine import FILING_STATUSES, compute, table_for

tax_bp = Blueprint("taxes", __name__, url_prefix="/admin/taxes")

# US estimated payments fall due the month after each quarter closes, and Q4's
# lands in the following January.
_QUARTER_DUE = {1: (4, 15), 2: (6, 15), 3: (9, 15), 4: (1, 15)}


def _quarter(when):
    return (when.month - 1) // 3 + 1


def _due_date(year, quarter):
    month, day = _QUARTER_DUE[quarter]
    return date(year + 1 if quarter == 4 else year, month, day)


def _money(field, current):
    """A dollar amount off the form, keeping the old value if it is unusable.

    Blank means zero, because clearing a field is a real intention. Garbage
    keeps what was there, because silently becoming zero would change the
    answer without saying so.
    """
    raw = (request.form.get(field) or "").strip().replace(",", "").replace("$", "")
    if raw == "":
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return current


def _percent(field, current):
    raw = (request.form.get(field) or "").strip().replace("%", "")
    if raw == "":
        return current
    try:
        return min(100.0, max(0.0, float(raw)))
    except ValueError:
        return current


@tax_bp.route("/", methods=["GET", "POST"])
@login_required
def taxes_index():
    settings = TaxSetting.get()

    if request.method == "POST":
        status = request.form.get("filing_status", "")
        if status in dict(FILING_STATUSES):
            settings.filing_status = status
        settings.your_wages = _money("your_wages", settings.your_wages)
        settings.spouse_wages = _money("spouse_wages", settings.spouse_wages)
        settings.other_income = _money("other_income", settings.other_income)
        settings.federal_withheld = _money("federal_withheld", settings.federal_withheld)
        settings.state_tax_rate = _percent("state_tax_rate", settings.state_tax_rate)
        settings.set_aside_rate = _percent("set_aside_rate", settings.set_aside_rate)
        db.session.commit()
        flash("Saved. The estimate below has been recalculated.", "success")
        return redirect(url_for("taxes.taxes_index", year=request.args.get("year", "")))

    transactions = get_stripe_income_transactions()
    years = sorted({t["date"].year for t in transactions if t["date"]}, reverse=True)
    year = request.args.get("year", type=int) or (years[0] if years else date.today().year)

    client_names = {
        c.stripe_customer_id: c.name
        for c in Client.query.filter(Client.stripe_customer_id.isnot(None)).all()
    }
    set_aside_rate = (settings.set_aside_rate or 0) / 100.0

    rows = []
    for t in transactions:
        if not t["date"] or t["date"].year != year:
            continue
        row = dict(t)
        row["client_name"] = client_names.get(t["customer_id"]) or t["customer_id"] or "-"
        # A refund is negative, so its set aside is negative too and hands back
        # what the original payment put away.
        row["set_aside"] = round(t["net"] * set_aside_rate, 2)
        row["quarter"] = _quarter(t["date"])
        rows.append(row)
    rows.reverse()

    # Material expenses only: a billable-time expense mirrors revenue rather
    # than being a cost of trading.
    expenses_by_quarter = {}
    for e in Expense.query.filter(Expense.time_entry_id.is_(None)).all():
        if e.date and e.date.year == year:
            q = _quarter(e.date)
            expenses_by_quarter[q] = expenses_by_quarter.get(q, 0.0) + (e.amount or 0)

    net_total = sum(r["net"] for r in rows)
    expense_total = sum(expenses_by_quarter.values())
    profit = net_total - expense_total

    calc = compute(
        profit,
        filing_status=settings.filing_status,
        your_wages=settings.your_wages,
        spouse_wages=settings.spouse_wages,
        other_income=settings.other_income,
        federal_withheld=settings.federal_withheld,
        state_rate=settings.state_tax_rate,
        year=year,
    )
    _year_used, table = table_for(year)

    # Quarters share the year's effective rate rather than each being run
    # through the brackets on its own. A quarter is not a tax year, and
    # pretending otherwise would put every quarter in the lowest band.
    effective = (calc["business_tax"] / profit) if profit > 0 else 0.0

    quarters = []
    for q in (1, 2, 3, 4):
        in_q = [r for r in rows if r["quarter"] == q]
        spend = expenses_by_quarter.get(q, 0.0)
        if not in_q and not spend:
            continue
        q_net = sum(r["net"] for r in in_q)
        q_profit = q_net - spend
        quarters.append({
            "quarter": q,
            "label": f"Q{q}",
            "due": _due_date(year, q),
            "count": len(in_q),
            "gross": sum(r["gross"] for r in in_q),
            "fees": sum(r["fee"] for r in in_q),
            "net": q_net,
            "expenses": spend,
            "profit": q_profit,
            "set_aside": sum(r["set_aside"] for r in in_q),
            "estimated": round(max(0.0, q_profit) * effective, 2),
        })

    totals = {
        "count": len(rows),
        "gross": sum(r["gross"] for r in rows),
        "fees": sum(r["fee"] for r in rows),
        "net": net_total,
        "expenses": expense_total,
        "profit": profit,
        "set_aside": sum(r["set_aside"] for r in rows),
    }

    return render_template("pm/taxes/index.html",
        settings=settings,
        filing_statuses=FILING_STATUSES,
        calc=calc,
        table=table,
        transactions=rows,
        quarters=quarters,
        totals=totals,
        year=year,
        years=years or [year],
        today=date.today(),
    )
