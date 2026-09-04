"""What has been built before, so it does not get built badly again.

Products are things that run once they are set up. Features are what somebody
uses when they open the app. This is the second list, and it exists for three
reasons in this order of value.

The last one first, because it is the one that pays: Talent Booker's CLAUDE.md
records 53 landmines and Data Dungeon's docs record 34, each written the day it
cost an afternoon, and every one is trapped in the repository that learned it.
Talent Booker's LM-19 says a `|tojson` in a double-quoted HTML attribute breaks
the attribute. That bug shipped from this repository on 2026-09-03, because
nothing here could see what was written over there. A catalogue that crosses
projects is the fix.

Then recall - "what have I built before" is a question a list of repositories
cannot answer, and the answer decides what gets offered on a call. And pricing,
which is what turns a phone conversation into an estimate before it ends.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required

from models import db, Feature

features_bp = Blueprint("features", __name__, url_prefix="/admin/features")


def _parse_money(raw):
    text = (raw or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _index(kind):
    """One page, two kinds: the features that get sold, and the rules that
    never get broken. Same search, same categories, same editor - a rule is
    a feature whose price is that nothing goes wrong.

    Every row of the kind is rendered. The filtering happens on the page as
    the search is typed and the moment a dropdown is picked, with the URL
    kept in step, so the three parameters here only seed that state: a
    link to a filtered view still opens filtered. The search covers the
    guidance and the traps as well as the name, because half the value of a
    landmine is being found by the symptom rather than by the title somebody
    gave it months ago; the template packs that text onto each row.
    """
    category = (request.args.get("category") or "all").strip()
    status = (request.args.get("status") or "all").strip()
    query = (request.args.get("q") or "").strip()
    if category not in Feature.CATEGORY_LABELS:
        category = "all"
    if status not in Feature.STATUS_LABELS:
        status = "all"

    features = (Feature.query.filter_by(is_active=True, kind=kind)
                .order_by(Feature.sort_order, Feature.name).all())

    counts = {}
    for row in features:
        counts[row.category] = counts.get(row.category, 0) + 1

    return render_template("pm/features/index.html",
                           features=features, counts=counts,
                           categories=Feature.CATEGORIES,
                           statuses=Feature.STATUSES,
                           category=category, status=status, q=query,
                           total=len(features),
                           page_kind=kind)


@features_bp.route("/")
@login_required
def features_index():
    return _index("feature")


@features_bp.route("/rules")
@login_required
def rules_index():
    return _index("rule")


def _index_endpoint(kind):
    return "features.rules_index" if kind == "rule" else "features.features_index"


@features_bp.route("/new", methods=["POST"])
@login_required
def feature_create():
    """Catch one named on a call, before the call ends.

    Deliberately the smallest possible form. Something a client asks for that
    does not exist yet is worth five seconds and a name; making it worth two
    minutes and eight fields is how it goes unrecorded instead.
    """
    kind = "rule" if request.form.get("kind") == "rule" else "feature"
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Give it a name.", "warning")
        return redirect(url_for(_index_endpoint(kind)))

    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:80]
    if Feature.query.filter_by(slug=slug).first():
        flash(f"\"{name}\" is already in the catalogue.", "warning")
        return redirect(url_for(_index_endpoint(kind)))

    category = request.form.get("category")
    last = db.session.query(db.func.max(Feature.sort_order)).scalar() or 0
    db.session.add(Feature(
        slug=slug, name=name, kind=kind,
        category=category if category in Feature.CATEGORY_LABELS else "records",
        summary=(request.form.get("summary") or "").strip(),
        # A rule has no price; its worth is nothing going wrong.
        typical_value=(None if kind == "rule"
                       else _parse_money(request.form.get("typical_value"))),
        status="idea", sort_order=last + 10,
    ))
    db.session.commit()
    flash(f"\"{name}\" added as something not built yet.", "success")
    return redirect(url_for(_index_endpoint(kind), category=category or "all"))


@features_bp.route("/<int:id>", methods=["POST"])
@login_required
def feature_edit(id):
    """The parts worth changing from the page: what it is worth, and the
    guidance. Everything else is a migration, because everything else is the
    catalogue's shape rather than its contents."""
    feature = db.session.get(Feature, id) or abort(404)
    if feature.kind != "rule":
        feature.typical_value = _parse_money(request.form.get("typical_value"))
    if "gold_standard_md" in request.form:
        feature.gold_standard_md = (request.form.get("gold_standard_md") or "").strip()
    if "pitfalls_md" in request.form:
        feature.pitfalls_md = (request.form.get("pitfalls_md") or "").strip()
    if request.form.get("status") in Feature.STATUS_LABELS:
        feature.status = request.form["status"]
    db.session.commit()
    flash(f"{feature.name} updated.", "success")
    # Back to the view that was open, filters and all: the form carries the
    # page's live state, and url_for drops whatever is empty.
    back = {}
    for key in ("category", "status"):
        value = (request.form.get(f"return_{key}") or "").strip()
        if value and value != "all":
            back[key] = value
    if (request.form.get("return_q") or "").strip():
        back["q"] = request.form["return_q"].strip()
    return redirect(url_for(_index_endpoint(feature.kind), **back))
