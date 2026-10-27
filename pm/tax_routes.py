"""A tax estimate over what Stripe actually paid out.

Facts in, working out. The user supplies filing status, wages and withholding;
`tax_engine` does brackets, the standard deduction, QBI and self employment
tax, and the page shows its own arithmetic so the number can be checked rather
than taken on faith.

Income comes from Stripe balance transactions rather than invoices, so refunds
subtract and fees are already netted off. These figures agree with the bank
rather than with what was billed, which is the right basis for tax.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import login_required

from models import db, Client, Expense, InvoiceLineItem, TaxSetting
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


# ── Sales tax ────────────────────────────────────────────────
#
# Texas sales tax on what this business sells, per client and per project,
# with what each client was never charged and the presses that bill it back.
# The arithmetic is sales_tax.build; this file only fetches, refreshes and
# writes. Stripe is touched in four places, each on a press: making the tax
# rate, putting it on drafts, putting it on a subscription, and drafting a
# catch-up invoice. Nothing here SENDS anything: a catch-up invoice is a draft
# for Michael to read and send from its own page.

from models import Invoice, Project, SalesTaxSetting  # noqa: E402
import sales_tax  # noqa: E402
from stripe_service import (  # noqa: E402
    SALES_TAX_META, add_tax_rate_to_draft, add_tax_rate_to_subscription,
    create_stripe_customer, create_stripe_invoice, ensure_sales_tax_rate,
    forget_sales_tax_caches, get_subscriptions_for_tax,
    import_invoices_from_stripe, mark_invoice_catchup, sync_invoice_from_stripe,
)


def _ledger(settings):
    return sales_tax.build(
        settings,
        Client.query.order_by(Client.name, Client.id).all(),
        Invoice.query.all(),
        Project.query.all(),
        get_subscriptions_for_tax(),
        settings.stripe_tax_rate_id,
    )


def _entry_for(client):
    settings = SalesTaxSetting.get()
    for entry in _ledger(settings)["clients"]:
        if entry["client"].id == client.id:
            return settings, entry
    return settings, None


def _back(client_id=None):
    return redirect(url_for("taxes.sales_tax_index", open=client_id) if client_id
                    else url_for("taxes.sales_tax_index"))


@tax_bp.route("/sales")
@login_required
def sales_tax_index():
    # Every Stripe invoice is made a local row first, because the project it
    # belongs to, the not-taxable mark and the catch-up flag all live on the
    # row. The Stripe list is cached for five minutes, so a reload is cheap.
    orphans = []
    try:
        _made, _updated, orphans = import_invoices_from_stripe(ttl=300)
    except Exception as e:  # a slightly stale ledger beats a broken page
        db.session.rollback()
        current_app.logger.error(f"Sales tax import error: {e}")
    settings = SalesTaxSetting.get()
    ledger = _ledger(settings)
    return render_template(
        "pm/taxes/sales.html",
        settings=settings,
        ledger=ledger,
        totals=ledger["totals"],
        orphans=orphans or [],
        open_id=request.args.get("open", type=int),
    )


@tax_bp.route("/sales/settings", methods=["POST"])
@login_required
def sales_tax_settings():
    settings = SalesTaxSetting.get()
    settings.rate_percent = _percent("rate_percent", settings.rate_percent)
    settings.taxable_share = _percent("taxable_share", settings.taxable_share)
    raw = (request.form.get("count_from") or "").strip()
    if not raw:
        settings.count_from = None
    else:
        try:
            settings.count_from = date.fromisoformat(raw)
        except ValueError:
            pass  # keep what was there rather than silently counting everything
    db.session.commit()
    flash(f"Saved. {settings.effective_percent:g}% of every dollar.", "success")
    return _back()


@tax_bp.route("/sales/clients/<int:id>/exempt", methods=["POST"])
@login_required
def sales_tax_client_exempt(id):
    client = db.session.get(Client, id) or abort(404)
    client.sales_tax_exempt = not client.sales_tax_exempt
    client.sales_tax_exempt_reason = ((request.form.get("reason") or "").strip()[:200]
                                      if client.sales_tax_exempt else "")
    db.session.commit()
    flash(f"{client.name} is {'exempt' if client.sales_tax_exempt else 'taxable'}.", "success")
    return _back(client.id)


@tax_bp.route("/sales/invoices/<int:id>/project", methods=["POST"])
@login_required
def sales_tax_invoice_project(id):
    inv = db.session.get(Invoice, id) or abort(404)
    project_id = request.form.get("project_id", type=int)
    project = db.session.get(Project, project_id) if project_id else None
    # Only one of the client's own projects: an invoice filed against
    # somebody else's build would move tax between two clients.
    if project is not None and project.client_id != inv.client_id:
        abort(400)
    inv.project_id = project.id if project else None
    db.session.commit()
    return _back(inv.client_id)


@tax_bp.route("/sales/invoices/<int:id>/taxable", methods=["POST"])
@login_required
def sales_tax_invoice_taxable(id):
    inv = db.session.get(Invoice, id) or abort(404)
    inv.sales_tax_exempt = not inv.sales_tax_exempt
    db.session.commit()
    return _back(inv.client_id)


@tax_bp.route("/sales/invoices/<int:id>/back-tax", methods=["POST"])
@login_required
def sales_tax_invoice_back_tax(id):
    """Say that an invoice bills back missed tax, or take that back.

    For a catch-up written by hand in the Stripe dashboard: without the mark
    it reads as a sale, owes 6.6% of itself and clears nothing. The mark goes
    into Stripe's metadata as well as onto the row, because the importer
    takes the flag from Stripe and a mark kept only here would be the board's
    word against Stripe's. Stripe first: if it refuses, nothing changes here.
    """
    inv = db.session.get(Invoice, id) or abort(404)
    on = not inv.sales_tax_catchup
    if inv.stripe_invoice_id:
        err = mark_invoice_catchup(inv.stripe_invoice_id, on)
        if err:
            flash(f"Stripe error: {err}", "error")
            return _back(inv.client_id)
    inv.sales_tax_catchup = on
    db.session.commit()
    forget_sales_tax_caches()
    label = inv.invoice_number or f"#{inv.id}"
    flash(f"{label} is {'back tax' if on else 'an ordinary sale'}.", "success")
    return _back(inv.client_id)


@tax_bp.route("/sales/clients/<int:id>/catchup", methods=["POST"])
@login_required
def sales_tax_catchup(id):
    """Draft the invoice that bills back the tax this client was never charged.

    A DRAFT, in Stripe and here. It is read and sent from its own page like
    every other invoice; this press only saves writing it.
    """
    client = db.session.get(Client, id) or abort(404)
    _settings, entry = _entry_for(client)
    lines = sales_tax.catchup_lines(entry) if entry else []
    if not lines:
        flash(f"{client.name} has nothing left to bill.", "info")
        return _back(client.id)

    if not client.stripe_customer_id:
        if not create_stripe_customer(client):
            flash("Could not make a Stripe customer for them.", "error")
            return _back(client.id)
        db.session.commit()

    stripe_invoice, err = create_stripe_invoice(
        client, lines, due_days=30,
        memo="Texas sales tax that should have been charged on earlier invoices.",
        metadata={SALES_TAX_META: "catchup"},
    )
    if not stripe_invoice:
        flash(f"Stripe error: {err}", "error")
        return _back(client.id)

    amount = round(sum(line["unit_amount"] for line in lines), 2)
    local = Invoice(
        client_id=client.id,
        stripe_invoice_id=stripe_invoice.id,
        status="draft",
        subtotal=amount, tax=0.0, total=amount, amount_due=amount,
        due_date=date.today() + timedelta(days=30),
        issued_on=date.today(),
        sales_tax_catchup=True,
        notes="Sales tax catch-up",
    )
    db.session.add(local)
    db.session.flush()
    for line in lines:
        db.session.add(InvoiceLineItem(
            invoice_id=local.id, description=line["description"], quantity=1,
            unit_amount=line["unit_amount"], total=line["unit_amount"], item_type="tax"))
    db.session.commit()
    sync_invoice_from_stripe(local)
    db.session.commit()
    forget_sales_tax_caches()
    flash(f"Drafted a ${amount:,.2f} sales tax invoice for {client.name}. Read it, then send it.",
          "success")
    return redirect(url_for("stripe.invoice_detail", id=local.id))


@tax_bp.route("/sales/clients/<int:id>/drafts", methods=["POST"])
@login_required
def sales_tax_drafts(id):
    """Put the tax on every draft this client has waiting to go out."""
    client = db.session.get(Client, id) or abort(404)
    settings, entry = _entry_for(client)
    drafts = entry["drafts_missing_tax"] if entry else []
    if not drafts:
        return _back(client.id)
    rate_id, err = ensure_sales_tax_rate(settings)
    if not rate_id:
        flash(f"Stripe error: {err}", "error")
        return _back(client.id)
    db.session.commit()

    done, failed = 0, []
    for inv in drafts:
        err = (add_tax_rate_to_draft(inv.stripe_invoice_id, rate_id)
               if inv.stripe_invoice_id else "not in Stripe")
        if err:
            failed.append(inv.invoice_number or f"#{inv.id}")
            continue
        sync_invoice_from_stripe(inv)
        done += 1
    db.session.commit()
    forget_sales_tax_caches()
    if done:
        flash(f"Sales tax added to {done} draft{'' if done == 1 else 's'} for {client.name}.",
              "success")
    if failed:
        flash("Could not change " + ", ".join(failed) + ".", "error")
    return _back(client.id)


@tax_bp.route("/sales/clients/<int:id>/subscriptions", methods=["POST"])
@login_required
def sales_tax_subscriptions(id):
    """Charge the tax on this client's subscriptions from the next bill on."""
    client = db.session.get(Client, id) or abort(404)
    settings, entry = _entry_for(client)
    subs = entry["subs_missing_tax"] if entry else []
    if not subs:
        return _back(client.id)
    rate_id, err = ensure_sales_tax_rate(settings)
    if not rate_id:
        flash(f"Stripe error: {err}", "error")
        return _back(client.id)
    db.session.commit()

    done = 0
    for sub in subs:
        err = add_tax_rate_to_subscription(sub["id"], rate_id)
        if err:
            flash(f"Stripe error on {sub['id']}: {err}", "error")
        else:
            done += 1
    forget_sales_tax_caches()
    if done:
        flash(f"Sales tax is on {client.name}'s subscription from the next bill.", "success")
    return _back(client.id)
