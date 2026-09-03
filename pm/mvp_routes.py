"""Build the MVP while the client is still on the phone.

The products page sells one thing at a time, after the decision. This page is
for before the decision: the first call, where somebody lists what they want
and the answer should be a number before the call ends. Features get tapped
in as the client names them, the products that run underneath go in beside
them, and the estimate keeps up. A package needs no contract to exist -
"still deciding" is most of them, and having the list saved is what makes
the follow-up call cheap.

A finished package hands off twice. The statement of work opens prefilled
with the scope and the price. And the build prompt stitches together
everything the catalogue knows about what was chosen - how each feature
should be built, what went wrong last time, which file is worth copying -
so the session that builds it starts off knowing what every project before
it had to learn the hard way.
"""
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort)
from flask_login import login_required

from models import (db, Client, Feature, Product, Playbook,
                    MvpPackage, MvpPackageItem)
from pm.products_routes import playbook_lines

mvp_bp = Blueprint("mvp", __name__, url_prefix="/admin/mvp")


def _parse_money(raw):
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ── The prompt ──────────────────────────────────────────────


def _product_block(item):
    head = f"== {item.name}"
    priced = []
    if item.price:
        priced.append(f"${item.price:,.0f}")
    if item.monthly_price:
        priced.append(f"${item.monthly_price:,.0f}/mo")
    if priced:
        head += f" ({' + '.join(priced)})"
    out = [head]

    product = item.product
    if product is not None and (product.summary or "").strip():
        out.append(f"  {product.summary.strip()}")
    if (item.notes or "").strip():
        out.append(f"  For this client: {item.notes.strip()}")
    out.append("")

    playbook = None
    if product is not None and product.playbook_slug:
        playbook = Playbook.query.filter_by(slug=product.playbook_slug,
                                            is_active=True).first()
    if playbook is not None:
        out.extend(playbook_lines(playbook))
    else:
        out.append("  There is no runbook for this one yet. Work out the "
                   "steps, and tell me what they were so one can be written.")
        out.append("")
    return out


def _feature_block(item):
    feature = item.feature
    head = f"== {item.name}"
    if item.price:
        head += f" (${item.price:,.0f})"
    out = [head]

    if feature is None:
        # The catalogue row is gone; the choice still happened. Say so
        # rather than rendering an empty heading that looks like an error.
        if (item.notes or "").strip():
            out.append(f"  For this client: {item.notes.strip()}")
        out.append("  No longer in the catalogue. Scope this one fresh.")
        out.append("")
        return out

    if (feature.summary or "").strip():
        out.append(f"  {feature.summary.strip()}")
    if feature.status == "idea":
        out.append("  Never built before - this one is new ground. Design it "
                   "properly, and when it works, write what you learned back "
                   "into the catalogue entry.")
    if (item.notes or "").strip():
        out.append(f"  For this client: {item.notes.strip()}")
    if (feature.gold_standard_md or "").strip():
        out.append("  How it should be built:")
        out.extend("    " + line
                   for line in feature.gold_standard_md.strip().splitlines())
    if (feature.pitfalls_md or "").strip():
        out.append("  What went wrong last time:")
        out.extend("    " + line
                   for line in feature.pitfalls_md.strip().splitlines())
    if (feature.reference_project or "").strip():
        ref = f"  The one worth copying: {feature.reference_project}"
        if (feature.reference_path or "").strip():
            ref += f" - {feature.reference_path}"
        out.append(ref)
    out.append("")
    return out


def _house_rules():
    """Every rule in the catalogue, regardless of what was picked. Rules
    are the layer under the features - ways of building that hold whether
    or not the feature they were learned on was bought - and a build that
    did not select "timezones" still has timezones."""
    rows = (Feature.query.filter_by(is_active=True, kind="rule")
            .order_by(Feature.sort_order, Feature.name).all())
    rows = [r for r in rows if r.has_guidance]
    if not rows:
        return []
    out = ["THE HOUSE RULES"]
    out.append("  Learned across every build so far. They apply here whether "
               "or not the feature they were learned on is in this package.")
    out.append("")
    for feature in rows:
        out.append(f"- {feature.name}")
        if (feature.gold_standard_md or "").strip():
            out.extend("    " + line
                       for line in feature.gold_standard_md.strip().splitlines())
        if (feature.pitfalls_md or "").strip():
            out.append("    Traps:")
            out.extend("      " + line
                       for line in feature.pitfalls_md.strip().splitlines())
    out.append("")
    return out


def build_package_prompt(package):
    """The whole build, written out for a fresh Claude session.

    Assembled from the catalogue at the moment it is asked for, not stored,
    so a feature whose pitfalls were updated yesterday briefs today's build
    with yesterday's lesson in it.
    """
    client = package.client
    out = [f'Build "{package.name}" for {client.name}.', ""]

    who = f"  {client.name}"
    if (client.company or "").strip() and client.company.strip() != client.name:
        who += f" - {client.company.strip()}"
    contact = ", ".join(v for v in ((client.email or "").strip(),
                                    (client.phone or "").strip()) if v)
    out.append("WHO IT IS FOR")
    out.append(who + (f" ({contact})" if contact else ""))
    out.append("")

    if (package.summary or "").strip():
        out.append("THE JOB")
        out.extend("  " + line
                   for line in package.summary.strip().splitlines())
        out.append("")

    numbers = []
    if package.estimate:
        numbers.append(f"${package.estimate:,.0f} one-time")
    if package.monthly_estimate:
        numbers.append(f"${package.monthly_estimate:,.0f} a month ongoing")
    if numbers:
        out.append("THE NUMBERS")
        out.append(f"  Quoted at {', plus '.join(numbers)}.")
        if package.price_override is not None and package.items_total \
                and package.price_override != package.items_total:
            out.append(f"  The parts add to ${package.items_total:,.0f}; "
                       "the quote is the number that was agreed.")
        out.append("")

    out.append("THE STACK")
    out.append("  Build it the way the reference projects are built, unless "
               "this document says otherwise: Flask, SQLAlchemy with Alembic "
               "migrations, server-rendered Jinja with Tailwind and Alpine, "
               "Postgres on Railway in production and SQLite locally, "
               "uploads on a mounted volume rather than a bucket.")
    out.append("  The reference projects live side by side in "
               r"C:\Users\Micha\Documents\Apps. When a feature names one, "
               "read the named file before building that feature.")
    out.append("")

    products = package.product_items
    if products:
        out.append("WHAT RUNS UNDERNEATH - THE PRODUCTS")
        out.append("")
        for item in products:
            out.extend(_product_block(item))

    features = package.feature_items
    if features:
        out.append("WHAT THEY USE - THE FEATURES")
        out.append("")
        # In the catalogue's own order: what brings work in, what happens to
        # it, what gets paid, the machinery underneath.
        order = {key: i for i, (key, _) in enumerate(Feature.CATEGORIES)}
        labels = dict(Feature.CATEGORIES)
        groups = {}
        for item in features:
            key = item.feature.category if item.feature else "_gone"
            groups.setdefault(key, []).append(item)
        for key in sorted(groups, key=lambda k: order.get(k, len(order))):
            out.append(f"[{labels.get(key, 'Also included')}]")
            for item in groups[key]:
                out.extend(_feature_block(item))

    out.extend(_house_rules())

    out.append("HOW TO WORK")
    out.append("  Start with the data model, and get a migration in from the "
               "first table.")
    out.append("  Work feature by feature. Finish one, prove it works, then "
               "start the next.")
    out.append("  Stop and tell me the moment a step needs me: anything in a "
               "browser I have to click, any credential only I can hand "
               "over, anything waiting on the client.")
    out.append("  Never invent a credential, a phone number or an account "
               "id. Ask.")
    out.append("  Where the guidance above disagrees with what you find, say "
               "so plainly instead of quietly deviating - the catalogue gets "
               "corrected, not ignored.")
    return "\n".join(out)


# ── Views ───────────────────────────────────────────────────


@mvp_bp.route("/")
@login_required
def mvp_index():
    packages = (MvpPackage.query
                .order_by(MvpPackage.updated_at.desc()).all())
    clients = Client.query.order_by(Client.name).all()
    return render_template("pm/mvp/index.html",
                           packages=packages,
                           client_options=[(c.id, c.name) for c in clients],
                           statuses=MvpPackage.STATUSES)


@mvp_bp.route("/new", methods=["POST"])
@login_required
def package_create():
    client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
    if not client:
        flash("Pick a client first. The package is theirs.", "warning")
        return redirect(url_for("mvp.mvp_index"))
    name = (request.form.get("name") or "").strip() or f"{client.name} MVP"
    package = MvpPackage(client_id=client.id, name=name)
    db.session.add(package)
    db.session.commit()
    return redirect(url_for("mvp.package_detail", id=package.id))


@mvp_bp.route("/<int:id>")
@login_required
def package_detail(id):
    package = db.session.get(MvpPackage, id) or abort(404)

    # The picker offers what can be sold. Rules are not on the menu - they
    # apply to every build regardless, through the prompt's house rules.
    features = (Feature.query.filter_by(is_active=True, kind="feature")
                .order_by(Feature.sort_order, Feature.name).all())
    products = (Product.query.filter_by(is_active=True)
                .order_by(Product.sort_order, Product.name).all())

    chosen_features = {i.feature_id for i in package.items if i.feature_id}
    chosen_products = {i.product_id for i in package.items if i.product_id}

    counts = {}
    for feature in features:
        counts[feature.category] = counts.get(feature.category, 0) + 1

    return render_template("pm/mvp/detail.html",
                           package=package,
                           features=features, products=products,
                           chosen_features=chosen_features,
                           chosen_products=chosen_products,
                           categories=Feature.CATEGORIES, counts=counts,
                           statuses=MvpPackage.STATUSES)


@mvp_bp.route("/<int:id>", methods=["POST"])
@login_required
def package_update(id):
    package = db.session.get(MvpPackage, id) or abort(404)
    name = (request.form.get("name") or "").strip()
    if name:
        package.name = name
    package.summary = (request.form.get("summary") or "").strip()
    package.price_override = _parse_money(request.form.get("price_override"))
    if request.form.get("status") in MvpPackage.STATUS_LABELS:
        package.status = request.form["status"]
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("mvp.package_detail", id=package.id))


@mvp_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def package_delete(id):
    package = db.session.get(MvpPackage, id) or abort(404)
    name = package.name
    db.session.delete(package)
    db.session.commit()
    flash(f"{name} deleted.", "success")
    return redirect(url_for("mvp.mvp_index"))


@mvp_bp.route("/<int:id>/items", methods=["POST"])
@login_required
def item_add(id):
    """Put one thing on the package: a feature, a product, or something the
    client just named that the catalogue has never heard of.

    The last one writes a Feature first - status "idea" - and then adds it,
    so a thing invented on a call exists in exactly one place and the next
    call can pick it from the list.
    """
    package = db.session.get(MvpPackage, id) or abort(404)
    back = redirect(url_for("mvp.package_detail", id=package.id) + "#pick")
    last = max([i.sort_order or 0 for i in package.items] or [0])

    feature_id = request.form.get("feature_id", type=int)
    product_id = request.form.get("product_id", type=int)
    new_name = (request.form.get("new_name") or "").strip()

    if feature_id:
        feature = db.session.get(Feature, feature_id)
        if feature is None:
            abort(404)
        if any(i.feature_id == feature.id for i in package.items):
            flash(f"{feature.name} is already on it.", "warning")
            return back
        db.session.add(MvpPackageItem(
            package_id=package.id, kind="feature", feature_id=feature.id,
            name=feature.name, price=feature.typical_value,
            sort_order=last + 10))
        db.session.commit()
        return back

    if product_id:
        product = db.session.get(Product, product_id)
        if product is None:
            abort(404)
        if any(i.product_id == product.id for i in package.items):
            flash(f"{product.name} is already on it.", "warning")
            return back
        db.session.add(MvpPackageItem(
            package_id=package.id, kind="product", product_id=product.id,
            name=product.name, price=product.price,
            monthly_price=product.monthly_price, sort_order=last + 10))
        db.session.commit()
        return back

    if new_name:
        slug = "".join(c if c.isalnum() else "-"
                       for c in new_name.lower()).strip("-")[:80]
        feature = Feature.query.filter_by(slug=slug).first()
        if feature is None:
            category = request.form.get("new_category")
            last_feature = db.session.query(
                db.func.max(Feature.sort_order)).scalar() or 0
            feature = Feature(
                slug=slug, name=new_name,
                category=(category if category in Feature.CATEGORY_LABELS
                          else "records"),
                typical_value=_parse_money(request.form.get("new_value")),
                status="idea", sort_order=last_feature + 10)
            db.session.add(feature)
            db.session.flush()
        if any(i.feature_id == feature.id for i in package.items):
            flash(f"{feature.name} is already on it.", "warning")
            return back
        db.session.add(MvpPackageItem(
            package_id=package.id, kind="feature", feature_id=feature.id,
            name=feature.name, price=feature.typical_value,
            sort_order=last + 10))
        db.session.commit()
        return back

    flash("Nothing to add.", "warning")
    return back


@mvp_bp.route("/<int:id>/items/<int:item_id>", methods=["POST"])
@login_required
def item_update(id, item_id):
    package = db.session.get(MvpPackage, id) or abort(404)
    item = db.session.get(MvpPackageItem, item_id)
    if item is None or item.package_id != package.id:
        abort(404)
    item.price = _parse_money(request.form.get("price"))
    if item.kind == "product":
        item.monthly_price = _parse_money(request.form.get("monthly_price"))
    item.notes = (request.form.get("notes") or "").strip()
    db.session.commit()
    flash(f"{item.name} updated.", "success")
    return redirect(url_for("mvp.package_detail", id=package.id))


@mvp_bp.route("/<int:id>/items/<int:item_id>/remove", methods=["POST"])
@login_required
def item_remove(id, item_id):
    package = db.session.get(MvpPackage, id) or abort(404)
    item = db.session.get(MvpPackageItem, item_id)
    if item is None or item.package_id != package.id:
        abort(404)
    name = item.name
    db.session.delete(item)
    db.session.commit()
    flash(f"{name} taken off.", "success")
    return redirect(url_for("mvp.package_detail", id=package.id))


@mvp_bp.route("/<int:id>/prompt")
@login_required
def package_prompt(id):
    package = db.session.get(MvpPackage, id) or abort(404)
    return render_template("pm/mvp/prompt.html", package=package,
                           prompt=build_package_prompt(package))


@mvp_bp.route("/<int:id>/sow")
@login_required
def package_sow(id):
    """Open the statement of work with this package already written in.

    Nothing is generated or sent from here - the SOW form stays the one
    place a contract comes from, and it opens filled in rather than blank.
    """
    package = db.session.get(MvpPackage, id) or abort(404)

    lines = [i.name for i in package.product_items]
    features = package.feature_items
    if len(features) <= 10:
        lines += [i.name for i in features]
    else:
        # A contract that lists forty rows reads like an inventory. Past
        # ten, the features collapse to one line per catalogue area, and
        # the full list stays on the package for anyone who asks.
        order = {key: i for i, (key, _) in enumerate(Feature.CATEGORIES)}
        labels = dict(Feature.CATEGORIES)
        groups = {}
        for item in features:
            key = item.feature.category if item.feature else "_extra"
            groups.setdefault(key, []).append(item.name)
        for key in sorted(groups, key=lambda k: order.get(k, len(order))):
            label = labels.get(key, "Also included")
            lines.append(f"{label}: {', '.join(groups[key])}")

    args = {
        "client_id": package.client_id,
        "project_name": package.name,
        "project_description": package.summary or "",
        "features": lines,
    }
    if package.estimate:
        args["mvp_price"] = f"{package.estimate:,.0f}"
    return redirect(url_for("pm.sow_form", **args))
