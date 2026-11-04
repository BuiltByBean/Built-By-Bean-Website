"""Build the MVP while the client is still on the phone.

Features get tapped in from Best Practices as the client names them, and the
products that run underneath go in beside them. A package needs no contract to
exist - "still deciding" is most of them, and having the list saved is what
makes the follow-up call cheap.

No money lives here (Michael, 2026-11-04). What a build costs is typed on the
SOW form, so nothing on this page can drift from what was agreed.

A package hands off three ways: "What they see" for the client, the statement
of work with the scope written in, and the build prompt, which stitches
together what Best Practices knows about what was chosen - how each feature
should be built, what went wrong last time, which file is worth copying - so
the session that builds it starts off knowing what every project before it had
to learn the hard way.

**The prompt has to fit.** It printed every rule in full until 2026-11-04, and
a package with two items on it came out at 1,077,939 characters. Nobody can
hand that to a session. Now it carries the chosen features whole, the rules for
the areas this build touches up to FULL_RULES_BUDGET, every other rule as one
line, and for a vendor what the client must do and the checklist, with the
whole runbook one get_playbook away. tools/test_mvp_prompt.py holds it to size.
"""
from datetime import date

from flask import (Blueprint, Response, render_template, redirect, url_for,
                   flash, request, abort)
from flask_login import login_required

from models import (db, Client, Feature, Product, Playbook,
                    MvpPackage, MvpPackageItem)
from pm.products_routes import playbook_lines

mvp_bp = Blueprint("mvp", __name__, url_prefix="/admin/mvp")

# What the rules may take of a prompt. In full for the areas the chosen features
# touch, one line each for the rest. The nightly curator is taking the list
# towards 120 rules, at which point every line fits with its summary.
FULL_RULES_BUDGET = 30000
RULE_LINES_BUDGET = 30000

# Where each project a feature names as the one worth copying lives on GitHub,
# first match wins: "Flipping (with Kuper Plumbing...)" is Flipping's.
REFERENCE_REPOS = (
    ("flipping", "Flipping"), ("kuper", "KuperPlumbing"),
    ("talent booker", "Talent-Booker"), ("robinson", "Robinson-Co."),
    ("gym ecosystem", "gym-ecosystem"), ("built by bean", "Built-By-Bean-Website"),
    ("bible study", "Built-By-Bean-Website"), ("signadoc", "Signadoc"),
    ("chopbuilder", "ChopBuilder"), ("4th anniversary", "4thanniversary"),
    ("vault of ash", "Vault-of-Ash"), ("christ community", "Christ-Community-Church"),
    ("crucible", "Jakob-s-Crucible"), ("piped", "piped"),
    ("entertainhq", "EntertainHQ"), ("lets cook", "Lets-Cook"),
    ("data dungeon", "Data-Dungeon"),
)


def reference_repo(project):
    """The GitHub repo behind a feature's reference project, or None."""
    name = (project or "").lower()
    for key, repo in REFERENCE_REPOS:
        if key in name:
            return f"BuiltByBean/{repo}"
    return None


# ── The prompt ──────────────────────────────────────────────


def _runbook_brief(playbook):
    """What a build has to know about a vendor from day one: what waits on the
    client, the access to ask for, and the checklist. The traps and the rest of
    a runbook are read when the vendor is reached, and they are long: Twilio's
    alone is 46,000 characters."""
    out = [f"  Before touching {playbook.display_name}: get_playbook {playbook.slug}, "
           "the whole runbook with its traps."]
    if (playbook.one_liner or "").strip():
        out.append(f"  {playbook.one_liner.strip()}")
    for label, body in (("Only the client can do these", playbook.client_only_md),
                        ("Access you need from them", playbook.access_grant_md)):
        if (body or "").strip():
            out.append(f"  {label}:")
            out.extend("    " + line for line in body.strip().splitlines())
    steps = playbook.steps.all()
    if steps:
        out.append("  The checklist:")
        for i, step in enumerate(steps, 1):
            flag = "  [waits on the client]" if step.waits_on_client else ""
            out.append(f"    {i}. {step.title}{flag}")
    out.append("")
    return out


def _product_block(item):
    out = [f"== {item.name}"]

    product = item.product
    if product is not None and (product.summary or "").strip():
        out.append(f"  {product.summary.strip()}")
    if (item.notes or "").strip():
        out.append(f"  For this client: {item.notes.strip()}")

    playbook = None
    if product is not None and product.playbook_slug:
        playbook = Playbook.query.filter_by(slug=product.playbook_slug,
                                            is_active=True).first()
    if playbook is not None:
        out.extend(_runbook_brief(playbook))
    else:
        out.append("  There is no runbook for this one yet. Work out the "
                   "steps, and tell me what they were so one can be written.")
        out.append("")
    return out


def _feature_block(item):
    feature = item.feature
    out = [f"== {item.name}"]

    if feature is None:
        # The catalogue row is gone; the choice still happened. Say so
        # rather than rendering an empty heading that looks like an error.
        if (item.notes or "").strip():
            out.append(f"  For this client: {item.notes.strip()}")
        out.append("  No longer in Best Practices. Scope this one fresh.")
        out.append("")
        return out

    if (feature.summary or "").strip():
        out.append(f"  {feature.summary.strip()}")
    if feature.status == "idea":
        out.append("  Never built before - this one is new ground. Design it "
                   "properly, and when it works, write what you learned back "
                   "into its Best Practices entry.")
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
        repo = reference_repo(feature.reference_project)
        if repo:
            ref += f" ({repo})"
        if (feature.reference_path or "").strip():
            ref += f" - {feature.reference_path}"
        out.append(ref)
    out.append("")
    return out


def _rule_block(feature):
    out = [f"- {feature.name}  [{feature.slug}]"]
    if (feature.gold_standard_md or "").strip():
        out.extend("    " + line
                   for line in feature.gold_standard_md.strip().splitlines())
    if (feature.pitfalls_md or "").strip():
        out.append("    Traps:")
        out.extend("      " + line
                   for line in feature.pitfalls_md.strip().splitlines())
    return out


def _rules_with_guidance():
    rows = (Feature.query.filter_by(is_active=True, kind="rule")
            .order_by(Feature.sort_order, Feature.name).all())
    return [r for r in rows if r.has_guidance]


def _house_rules():
    """Every rule, in full, regardless of what was picked: `?full=1` on the
    guidance brief. Far too long to hand a session as a prompt (a megabyte at
    500 rules), which is what _rules_for_build is for."""
    rows = _rules_with_guidance()
    if not rows:
        return []
    out = ["THE HOUSE RULES"]
    out.append("  Learned across every build so far. They apply here whether "
               "or not the feature they were learned on is in this package.")
    # The slug, because until 2026-09-05 this printed only the name and
    # `suggest_update` takes a slug. Nothing published the mapping, and it is
    # not derivable - "Migrations beside create_all" is `migrations-with-
    # create-all` and "Sends that survive the request" is `queue-first-
    # sending`. So every precise append 404'd, sessions fell back to
    # `report_lesson`'s forgiving name match, and the same lesson got filed
    # three and four times over. Auditing Robinson & Co. found exactly that.
    out.append("  Each rule's slug is in brackets. That is what suggest_update "
               "takes when you want to change one field of an existing rule, "
               "or propose its scanner. report_lesson matches on the NAME and "
               "appends prose; use it when you have a lesson rather than an "
               "edit, and it will tell you the slug it appended to.")
    out.append("")
    for feature in rows:
        out.extend(_rule_block(feature))
    out.append("")
    return out


def _rules_for_build(areas):
    """The rules a build carries in its prompt.

    Rules are the layer under the features - ways of building that hold
    whether or not the feature they were learned on was picked - so a build
    that did not pick "timezones" still has timezones, and every rule is at
    least named. The ones for the areas this build's features are in come in
    full, up to FULL_RULES_BUDGET, and the rest are one line each.
    """
    from pm.guidance_routes import rules_index
    rows = _rules_with_guidance()
    if not rows:
        return []
    full, spent, blocks = set(), 0, []
    for rule in rows:
        if rule.category not in areas:
            continue
        block = _rule_block(rule)
        size = sum(len(line) + 1 for line in block)
        if spent + size > FULL_RULES_BUDGET:
            continue
        full.add(rule.id)
        spent += size
        blocks.extend(block)
    out = []
    if blocks:
        out.append("THE RULES FOR WHAT THIS BUILD DOES")
        out.append("  In full, because they touch the features above. Each "
                   "rule's slug is in brackets: suggest_update takes it to "
                   "change one field, and report_lesson matches on the name "
                   "when you have a lesson rather than an edit.")
        out.append("")
        out.extend(blocks)
        out.append("")
    rest = [r for r in rows if r.id not in full]
    if rest:
        out.append(rules_index(RULE_LINES_BUDGET, rows=rest,
                               title="THE OTHER HOUSE RULES"))
        out.append("")
    return out


def build_package_prompt(package):
    """The whole build, written out for a fresh Claude session.

    Assembled from Best Practices at the moment it is asked for, not stored,
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

    out.append("THE STACK")
    out.append("  Build it the way the reference projects are built, unless "
               "this document says otherwise: Flask, SQLAlchemy with Alembic "
               "migrations, server-rendered Jinja with Tailwind and Alpine, "
               "Postgres on Railway in production and SQLite locally, "
               "uploads on a mounted volume rather than a bucket.")
    out.append("  When a feature names a reference project, read the named "
               "file before building that feature. They are on GitHub under "
               "BuiltByBean; gh repo clone the one named if it is not already "
               "in ~/Code.")
    out.append("")

    products = package.product_items
    if products:
        out.append("WHAT RUNS UNDERNEATH - THE PRODUCTS")
        out.append("")
        for item in products:
            out.extend(_product_block(item))

    features = package.feature_items
    areas = {i.feature.category for i in features if i.feature}
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

    out.extend(_rules_for_build(areas))

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
    # The loop, written into the prompt itself so it travels with the
    # project rather than depending on which machine the session is on.
    # On 2026-09-04 a laptop turned out to have neither the bridge nor the
    # standing order, and nothing in the prompt said so; a session there
    # would have built from this snapshot and filed nothing back.
    out.append("  This prompt is a snapshot of the board. The board is live: "
               "call get_rules before building, get_feature_guidance for "
               "each feature as you reach it, and get_playbook before "
               "touching a vendor. If the pm-guidance tools are not in this "
               "session, stop and say so before anything else - the fix is "
               "tools/bootstrap_guidance.sh (or .ps1 on Windows) in the "
               "Built-By-Bean-Website repo, then a fresh session. Do not build "
               "from the snapshot alone.")
    out.append("  What this build teaches goes back the moment it is learned, "
               "not at the end: report_lesson for a bug that cost time, "
               "suggest_update for a runbook step that moved, a better file "
               "to copy, a rule that reads badly, or a product that now "
               "exists. Every change applies at once, and a nightly curator "
               "merges and prunes, so write for any project, not this one.")
    out.append("  File the work as it happens: upsert_project once, log_time "
               "and log_expense as they occur, register_hosting_resource "
               "for anything stood up.")
    out.append("  Where the guidance above disagrees with what you find, say "
               "so plainly instead of quietly deviating - Best Practices gets "
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
    # A new client is usually who this page is open for, so the name can be
    # typed right here. Finding a row of that name first keeps a second press
    # from making them twice.
    new_client = " ".join((request.form.get("new_client") or "").split())[:200]
    if new_client:
        client = Client.query.filter(Client.name.ilike(new_client)).first()
        if client is None:
            client = Client(name=new_client)
            db.session.add(client)
            db.session.flush()
    else:
        client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
    if not client:
        flash("Pick a client or type a new one. The package is theirs.", "warning")
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

    # The picker offers what a client could ask for. Rules are not on the menu
    # - they apply to every build regardless, through the prompt. Grouped by
    # area, and by name inside one, because a client names things in no order
    # and the eye has to land on the word.
    features = (Feature.query.filter_by(is_active=True, kind="feature")
                .order_by(Feature.name).all())
    products = (Product.query.filter_by(is_active=True)
                .order_by(Product.sort_order, Product.name).all())

    # What is on it, by what it came from: a tick that a press takes back off
    # needs to know which item it is.
    chosen_features = {i.feature_id: i.id for i in package.items if i.feature_id}
    chosen_products = {i.product_id: i.id for i in package.items if i.product_id}

    by_area = {}
    for feature in features:
        by_area.setdefault(feature.category, []).append(feature)
    feature_groups = [(key, label, by_area[key]) for key, label in Feature.CATEGORIES
                      if by_area.get(key)]

    return render_template("pm/mvp/detail.html",
                           package=package,
                           feature_groups=feature_groups, products=products,
                           chosen_features=chosen_features,
                           chosen_products=chosen_products,
                           categories=Feature.CATEGORIES,
                           statuses=MvpPackage.STATUSES)


@mvp_bp.route("/<int:id>", methods=["POST"])
@login_required
def package_update(id):
    package = db.session.get(MvpPackage, id) or abort(404)
    name = (request.form.get("name") or "").strip()
    if name:
        package.name = name
    package.summary = (request.form.get("summary") or "").strip()
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
            name=feature.name, sort_order=last + 10))
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
            name=product.name, sort_order=last + 10))
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
                status="idea", sort_order=last_feature + 10)
            db.session.add(feature)
            db.session.flush()
        if any(i.feature_id == feature.id for i in package.items):
            flash(f"{feature.name} is already on it.", "warning")
            return back
        db.session.add(MvpPackageItem(
            package_id=package.id, kind="feature", feature_id=feature.id,
            name=feature.name, sort_order=last + 10))
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
    # No toast: the tick going is the answer, and on a phone a toast lands on
    # the search box somebody is about to use.
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("mvp.package_detail", id=package.id))


@mvp_bp.route("/<int:id>/prompt")
@login_required
def package_prompt(id):
    package = db.session.get(MvpPackage, id) or abort(404)
    return render_template("pm/mvp/prompt.html", package=package,
                           prompt=build_package_prompt(package))


@mvp_bp.route("/<int:id>/prompt.txt")
@login_required
def package_prompt_text(id):
    """The prompt on its own, for the Copy button on the package."""
    package = db.session.get(MvpPackage, id) or abort(404)
    return Response(build_package_prompt(package), mimetype="text/plain")


@mvp_bp.route("/<int:id>/summary")
@login_required
def package_summary(id):
    """The package as the client reads it.

    The builder is a working surface: what is built and what is only an idea.
    A statement of work is the other end, and it is a contract - you do not
    open a call with one. This is the thing in between: what they would get,
    on one page, in the words a person uses. What it costs is on the SOW.

    Grouped by what each part is FOR rather than by whether it came from the
    products table or the features table, because that distinction is an
    accident of how this board stores things and means nothing to the person
    reading.

    Deliberately not shown: which parts have been built before and which are
    new. That is a fact about my risk, not about their quote, and a client
    reading "not built yet" beside a line they are paying for asks a question
    the line does not deserve.
    """
    package = db.session.get(MvpPackage, id) or abort(404)

    labels = dict(Feature.CATEGORIES)
    order = {key: i for i, (key, _) in enumerate(Feature.CATEGORIES)}

    groups = {}
    for item in package.items:
        if item.kind == "product":
            # A product is a named thing somebody asked for by name, so it
            # keeps its own heading rather than being filed under an area.
            key, label = "_products", "What it will do"
        else:
            key = item.feature.category if item.feature else "_extra"
            label = labels.get(key, "Also included")
        groups.setdefault(key, {"label": label, "items": []})["items"].append({
            "name": item.name,
            # The note was written for this client, so it wins over the
            # catalogue's general line about what the thing does.
            "blurb": (item.notes
                      or (item.feature.summary if item.feature else "")
                      or (item.product.summary if item.product else "")),
        })

    sections = [groups[k] for k in sorted(
        groups, key=lambda k: -1 if k == "_products" else order.get(k, len(order)))]

    return render_template("pm/mvp/summary.html", package=package,
                           sections=sections, today=date.today())


@mvp_bp.route("/<int:id>/sow")
@login_required
def package_sow(id):
    """Open the statement of work with this package already written in.

    Nothing is generated or sent from here - the SOW form stays the one
    place a contract comes from, and it opens with the scope filled in. The
    price is typed there.
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
    return redirect(url_for("pm.sow_form", **args))
