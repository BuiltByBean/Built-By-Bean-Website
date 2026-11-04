"""The Taxes pages' own routes: income tax per company, and Texas sales tax.

Income tax (docs/finances_plan.md item 4): one company at a time, picked by
the switch, and one year. The arithmetic is `income_tax.estimate`, which the
Overview reads too, and its profit is the Books page's net for that company
and year. Facts in, working out: filing status, wages and withholding are
typed here and `tax_engine` does brackets, the standard deduction, QBI and
self employment tax, and the page shows its own working so the number can be
checked rather than taken on faith.

Every route here is CEO only, like the Books and the returns.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)

import income_tax
from models import db, Business, Client, InvoiceLineItem, TaxSetting
from pm.users_routes import ceo_required
from tax_engine import FILING_STATUSES, table_for

tax_bp = Blueprint("taxes", __name__, url_prefix="/admin/taxes")


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


def _company(companies):
    """The company asked for (a DBA's id answers its parent), else the first."""
    wanted = request.values.get("company", type=int)
    if wanted:
        chosen = db.session.get(Business, wanted)
        if chosen is not None:
            root = chosen.parent or chosen
            for c in companies:
                if c.id == root.id:
                    return c
    return companies[0] if companies else None


@tax_bp.route("/", methods=["GET", "POST"])
@ceo_required
def taxes_index():
    settings = TaxSetting.get()
    companies = income_tax.tax_companies()
    company = _company(companies)

    if request.method == "POST":
        status = request.form.get("filing_status", "")
        if status in dict(FILING_STATUSES):
            settings.filing_status = status
        settings.your_wages = _money("your_wages", settings.your_wages)
        settings.spouse_wages = _money("spouse_wages", settings.spouse_wages)
        settings.other_income = _money("other_income", settings.other_income)
        settings.federal_withheld = _money("federal_withheld", settings.federal_withheld)
        settings.state_tax_rate = _percent("state_tax_rate", settings.state_tax_rate)
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("taxes.taxes_index", company=company.id if company else None,
                                year=request.values.get("year", type=int)))

    # One list of years for every company, so the year switch, which the
    # company switch does not redraw, never offers a year another company
    # lacks.
    today = date.today()
    years = {today.year}
    for c in companies:
        years.update(income_tax.years_for(c, today))
    year = request.args.get("year", type=int) or today.year
    if not 2000 <= year <= today.year + 1:
        year = today.year
    years = sorted(years | {year}, reverse=True)

    est = income_tax.estimate(company, year, today, settings=settings) if company else None
    return render_template(
        "pm/taxes/index.html",
        settings=settings,
        filing_statuses=FILING_STATUSES,
        companies=companies,
        company=company,
        company_options=[(str(c.id), c.short_name or c.name) for c in companies],
        year_options=[(str(y), str(y)) for y in years],
        est=est,
        calc=est["calc"] if est else None,
        table=table_for(year)[1],
        year=year,
        years=years,
        today=today,
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
@ceo_required
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
@ceo_required
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
@ceo_required
def sales_tax_client_exempt(id):
    client = db.session.get(Client, id) or abort(404)
    client.sales_tax_exempt = not client.sales_tax_exempt
    client.sales_tax_exempt_reason = ((request.form.get("reason") or "").strip()[:200]
                                      if client.sales_tax_exempt else "")
    db.session.commit()
    flash(f"{client.name} is {'exempt' if client.sales_tax_exempt else 'taxable'}.", "success")
    return _back(client.id)


@tax_bp.route("/sales/invoices/<int:id>/project", methods=["POST"])
@ceo_required
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
@ceo_required
def sales_tax_invoice_taxable(id):
    inv = db.session.get(Invoice, id) or abort(404)
    inv.sales_tax_exempt = not inv.sales_tax_exempt
    db.session.commit()
    return _back(inv.client_id)


@tax_bp.route("/sales/invoices/<int:id>/back-tax", methods=["POST"])
@ceo_required
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
@ceo_required
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
@ceo_required
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
@ceo_required
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
