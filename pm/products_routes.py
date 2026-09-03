"""What I sell, priced, and what happens when somebody buys it.

Three things were already here and could not see each other. The add-on
contract knew the wording for texting and card payments but not what they
cost. The playbooks knew how to set a vendor up but not that setting it up was
something anybody paid for. Projects carried the work and neither knew a sale
had happened.

Selling something here does all three in one move: it records the sale, puts
the vendor's runbook on the project, and hands the add-on contract everything
it needs already filled in.

A sale always lands on a project, even when nothing custom was built. Somebody
buying only a signing portal still needs somewhere for the runbook, the
hosting fee and the tickets to live, so a standalone purchase makes a small
project rather than giving those three a second home to be looked for in.
"""
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort)
from flask_login import login_required

from models import (db, Client, Project, Playbook, ProjectPlaybook,
                    Product, ProductSale)
import contract_docs

products_bp = Blueprint("products", __name__, url_prefix="/admin/products")


def _parse_money(raw):
    """A price typed by hand, or None. Accepts $1,000 and 1000 alike."""
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_prompt(sale):
    """The whole job, written out for a fresh Claude session.

    Assembled from the playbook rather than stored on the product, so it is
    whatever the runbook says today. A prompt copied into a text field once
    would be describing a vendor's screens as they were the day it was
    written, which is exactly how a runbook goes quietly wrong.

    Steps that wait on the client are marked, and their message is included,
    because those are the ones that decide how long the whole thing takes and
    the ones no agent can do alone.
    """
    product, project, client = sale.product, sale.project, sale.client
    out = []
    out.append(f"Set up {product.name} for {client.name}, on the project "
               f"\"{project.name}\".")
    out.append("")

    if (product.prompt_intro or "").strip():
        out.append(product.prompt_intro.strip())
        out.append("")

    sold = []
    if sale.price is not None:
        sold.append(f"sold for ${sale.price:,.2f}")
    if sale.monthly_price:
        sold.append(f"plus ${sale.monthly_price:,.2f} a month")
    if sale.delivery_date:
        sold.append(f"delivery agreed for {sale.delivery_date:%d %B %Y}")
    if sold:
        out.append("WHAT WAS AGREED")
        out.append("  " + ", ".join(sold) + ".")
    if (sale.notes or "").strip():
        out.append(f"  What they want it for: {sale.notes.strip()}")
    out.append("")

    playbook = None
    if product.playbook_slug:
        playbook = Playbook.query.filter_by(slug=product.playbook_slug).first()

    if playbook is not None:
        out.append(f"THE RUNBOOK - {playbook.display_name}")
        if playbook.one_liner:
            out.append(f"  {playbook.one_liner}")
        out.append("")
        for label, body in (("Only the client can do these", playbook.client_only_md),
                            ("Access you need from them", playbook.access_grant_md),
                            ("Your steps", playbook.your_steps_md),
                            ("Traps", playbook.traps_md),
                            ("How to know it works", playbook.verify_md)):
            if (body or "").strip():
                out.append(f"{label}:")
                out.extend("  " + line for line in body.strip().splitlines())
                out.append("")

        steps = playbook.steps.all()
        if steps:
            out.append("THE CHECKLIST")
            for i, step in enumerate(steps, 1):
                flag = "  [waits on the client]" if step.waits_on_client else ""
                out.append(f"  {i}. {step.title}{flag}")
                if (step.detail_md or "").strip():
                    out.extend("       " + line
                               for line in step.detail_md.strip().splitlines())
                if step.waits_on_client and (step.client_message_md or "").strip():
                    out.append("       Ask them, roughly:")
                    out.extend("         " + line
                               for line in step.client_message_md.strip().splitlines())
            out.append("")
    else:
        out.append("There is no runbook for this one yet. Work out the steps, "
                   "and tell me what they were so one can be written.")
        out.append("")

    out.append("HOW TO WORK")
    out.append("  Go in order. Stop and tell me the moment a step needs me: "
               "anything in a browser I have to click, any credential only I "
               "can hand over, anything waiting on the client.")
    out.append("  Never invent a credential, a phone number or an account id. "
               "Ask.")
    out.append("  When you stop, say plainly what you did, what is left, and "
               "exactly what you need from me to carry on.")
    return "\n".join(out)


@products_bp.route("/")
@login_required
def products_index():
    products = Product.query.order_by(Product.sort_order, Product.name).all()
    sales = (ProductSale.query
             .order_by(ProductSale.created_at.desc()).all())

    # Everything the sell form needs, built once rather than per product.
    clients = Client.query.order_by(Client.name).all()
    projects = [{"id": str(p.id), "client_id": str(p.client_id), "name": p.name}
                for p in Project.query.order_by(Project.name).all()]

    sold_count = {}
    for sale in sales:
        sold_count[sale.product_id] = sold_count.get(sale.product_id, 0) + 1

    # Built per sale rather than once per product, because the prompt names the
    # client, the project and what they agreed to.
    prompts = {sale.id: build_prompt(sale) for sale in sales}

    return render_template("pm/products/index.html",
                           products=products, sales=sales, prompts=prompts,
                           clients=clients, projects=projects,
                           sold_count=sold_count,
                           today=datetime.now(timezone.utc).date().isoformat())


@products_bp.route("/<int:id>/price", methods=["POST"])
@login_required
def product_price(id):
    """The list price, which is a business decision and not a deploy."""
    product = db.session.get(Product, id) or abort(404)
    product.price = _parse_money(request.form.get("price"))
    product.monthly_price = _parse_money(request.form.get("monthly_price"))
    db.session.commit()
    flash(f"{product.name} price updated.", "success")
    return redirect(url_for("products.products_index"))


@products_bp.route("/sell", methods=["POST"])
@login_required
def product_sell():
    """Record a sale, apply its runbook, and hand the contract the details.

    The project is either one that exists or one made here. A client buying
    only a signing portal has no build to attach it to, and the runbook, the
    hosting fee and the tickets all need one, so this makes it rather than
    leaving three features with nowhere to point.
    """
    product = db.session.get(Product, request.form.get("product_id", type=int) or 0)
    client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
    if not product or not client:
        flash("Pick a client and a product.", "warning")
        return redirect(url_for("products.products_index"))

    project = db.session.get(Project, request.form.get("project_id", type=int) or 0)
    if project is not None and project.client_id != client.id:
        # A stale form can name somebody else's project. Filing the sale, the
        # runbook and the contract against it would put all three on the wrong
        # client at once.
        flash("That project belongs to a different client.", "warning")
        return redirect(url_for("products.products_index"))

    if project is None:
        name = (request.form.get("new_project_name") or "").strip() \
               or f"{product.name} - {client.name}"
        project = Project(client_id=client.id, name=name)
        db.session.add(project)
        db.session.flush()

    sale = ProductSale(
        product_id=product.id, client_id=client.id, project_id=project.id,
        price=_parse_money(request.form.get("price")),
        monthly_price=_parse_money(request.form.get("monthly_price")),
        delivery_date=_parse_date(request.form.get("delivery_date")),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(sale)

    # The runbook for the vendor behind it, if this product has one and the
    # project has not already got it.
    applied = None
    if product.playbook_slug:
        playbook = Playbook.query.filter_by(slug=product.playbook_slug,
                                            is_active=True).first()
        if playbook is not None:
            exists = ProjectPlaybook.query.filter_by(
                project_id=project.id, playbook_id=playbook.id).first()
            if not exists:
                db.session.add(ProjectPlaybook(project_id=project.id,
                                               playbook_id=playbook.id))
                applied = playbook.display_name

    db.session.commit()

    note = f" {applied} checklist added to {project.name}." if applied else ""
    flash(f"{product.name} recorded against {client.name}.{note}", "success")

    # Straight into the add-on contract with everything it needs. Prefilled and
    # unsent: nothing goes to a client without being read first, which is how
    # every other contract on this board already works.
    # The contract layer has its own wording for four of these, keyed by the
    # same slug. Anything it has never heard of goes in as the generic
    # agreement carrying its own name and summary, rather than selecting a
    # product the form cannot fill itself in from.
    key = product.slug if product.slug in contract_docs.PRODUCTS else "other"
    return redirect(url_for("contracts.addon_form",
                            client_id=client.id,
                            product=key,
                            product_name=product.name,
                            summary=product.summary or "",
                            one_time_fee=f"{sale.price:,.0f}" if sale.price else "",
                            monthly_fee=f"{sale.monthly_price:,.0f}" if sale.monthly_price else "",
                            notes=sale.notes or ""))


@products_bp.route("/sales/<int:id>/delete", methods=["POST"])
@login_required
def sale_delete(id):
    sale = db.session.get(ProductSale, id) or abort(404)
    name, who = sale.product.name, sale.client.name
    db.session.delete(sale)
    db.session.commit()
    flash(f"{name} removed from {who}.", "success")
    return redirect(url_for("products.products_index"))
