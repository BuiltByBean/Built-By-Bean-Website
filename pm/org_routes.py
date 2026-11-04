"""Org: every business's people, and the board's own logins (was Team).

    /admin/org                         the first business's org
    /admin/org/<id>[/<view>]           people, chart, responsibilities, departments
    /admin/org/<id>/people/<pid>       one person
    /admin/org/<id>/save               every change, through org_service.save
    /admin/org/logins/...              the board's logins (pm/users_routes.py)

    POST /api/hub/org                  a business's own app reads its org
    POST /api/hub/org/save             ... and saves one change to it
    POST /api/hub/org/import           ... and sends its rows over, once

The hub routes are signed with the business's hub secret exactly as the tax
and books doors are (`_hub_business`), and the board never calls back into the
app from inside one. CEO only on the board, like Team was, because an org
carries who owns what. org_service.py says what the store is and why.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user

import org_service
from models import Business, OrgPerson, db
from pm.users_routes import ceo_required

org_bp = Blueprint("org", __name__)

VIEWS = (("people", "People"), ("chart", "Org chart"),
         ("responsibilities", "Responsibilities"), ("departments", "Departments"))


def _business(bid):
    business = db.session.get(Business, bid)
    if business is None or business not in org_service.org_businesses():
        abort(404)
    return business


def _dba_moved(bid):
    """A DBA has no org: its people are its company's. Its old addresses
    answer 301 to the company's (Michael, 2026-11-04)."""
    business = db.session.get(Business, bid)
    if business is not None and business.is_division and business.parent is not None:
        return business.parent
    return None


def org_tabs(active):
    """The business row: every business, then the board's own logins."""
    tabs = [(str(b.id), b.label, url_for("org.business", bid=b.id)) for b in org_service.org_businesses()]
    tabs.append(("logins", "Logins", url_for("users.index")))
    return tabs


@org_bp.route("/admin/org/")
@ceo_required
def index():
    businesses = org_service.org_businesses()
    if not businesses:
        return redirect(url_for("users.index"))
    return redirect(url_for("org.business", bid=businesses[0].id))


@org_bp.route("/admin/org/<int:bid>/")
@org_bp.route("/admin/org/<int:bid>/<view>")
@ceo_required
def business(bid, view="people"):
    parent = _dba_moved(bid)
    if parent is not None and view in dict(VIEWS):
        if view == "people":
            return redirect(url_for("org.business", bid=parent.id), 301)
        return redirect(url_for("org.business", bid=parent.id, view=view), 301)
    business = _business(bid)
    if view not in dict(VIEWS):
        abort(404)
    data = org_service.payload(business)
    people = {p["id"]: p for p in data["people"]}
    depts = {d["id"]: d for d in data["departments"]}
    share_total = sum(o["share_percent"] or 0 for o in data["owners"])
    columns = [(None, "Unassigned")] + [(p["id"], p["name"]) for p in data["people"]]
    return render_template(
        "pm/org/page.html", business=business, view=view, views=VIEWS, data=data,
        people=people, depts=depts, share_total=share_total, columns=columns,
        tree=org_service.tree(business) if view == "chart" else [],
        tabs=org_tabs(str(business.id)),
        # No counts on this row: it is kept across a save, so a count there
        # would not follow it. The tiles carry the counts and are live.
        view_tabs=[(k, l, url_for("org.business", bid=business.id, view=k)) for k, l in VIEWS])


@org_bp.route("/admin/org/<int:bid>/people/<int:pid>")
@ceo_required
def person(bid, pid):
    parent = _dba_moved(bid)
    if parent is not None:
        p = db.session.get(OrgPerson, pid)
        if p is not None and p.business_id == parent.id:
            return redirect(url_for("org.person", bid=parent.id, pid=pid), 301)
        return redirect(url_for("org.business", bid=parent.id), 301)
    business = _business(bid)
    p = db.session.get(OrgPerson, pid)
    if p is None or p.business_id != business.id:
        abort(404)
    data = org_service.payload(business)
    me = next(x for x in data["people"] if x["id"] == p.id)
    below = org_service._below(p)
    above = org_service._above(p)
    people = {x["id"]: x for x in data["people"]}
    return render_template(
        "pm/org/person.html", business=business, person=p, me=me, data=data,
        supervisors=[("", "Nobody: the top")] + [(x["id"], x["name"]) for x in data["people"]
                                                if x["id"] != p.id and x["id"] not in below],
        report_choices=[x for x in data["people"] if x["id"] != p.id and x["id"] not in above],
        chain=[people[i] for i in reversed(above) if i in people], tabs=org_tabs(str(business.id)),
        mine=[r for r in data["responsibilities"] if r["owner"] == p.id],
        depts={d["id"]: d for d in data["departments"]})


def _back(business):
    target = request.form.get("next") or ""
    # Only ever back onto this org's own pages.
    if target.startswith("/admin/org/") and "//" not in target and "\\" not in target:
        return redirect(target)
    return redirect(url_for("org.business", bid=business.id))


def _body_from_form(form):
    body = {k: v for k, v in form.items() if k not in ("depts", "reports", "people", "next")}
    for many in ("depts", "reports", "people"):
        if form.get(f"has_{many}"):
            body[many] = [v for v in form.getlist(many) if v]
    for key in list(body):
        if key.startswith("has_"):
            body.pop(key)
    if body.get("supervisor") == "":
        body["supervisor"] = None
    if body.get("owner") == "":
        body["owner"] = None
    return body


@org_bp.route("/admin/org/<int:bid>/save", methods=["POST"])
@ceo_required
def save(bid):
    parent = _dba_moved(bid)
    if parent is not None:
        # A form left open on a DBA's org posts to its company's, method kept.
        return redirect(url_for("org.save", bid=parent.id), 307)
    business = _business(bid)
    body = _body_from_form(request.form)
    try:
        said = org_service.save(business, body, by=current_user.username, allow_share=True)
        flash(said, "success")
    except org_service.Refused as err:
        db.session.rollback()
        flash(str(err), "warning")
        if err.status == 404 and body.get("what") == "person":
            return redirect(url_for("org.business", bid=business.id))
    if body.get("what") == "person" and body.get("op") == "delete":
        return redirect(url_for("org.business", bid=business.id))
    return _back(business)


# ── The hub: a business's own app reads and saves its org ──────


def _hub():
    from pm.business_routes import _hub_business, _hub_json
    business, refused = _hub_business()
    if not refused:
        # A DBA's own app reads and saves its company's org.
        business = org_service.org_home(business)
    return business, refused, (_hub_json() if not refused else {})


@org_bp.route("/api/hub/org", methods=["POST"])
def hub_org():
    """The whole org, with the app's logins recorded if it sent them."""
    business, refused, data = _hub()
    if refused:
        return refused
    if "logins" in data:
        org_service.record_logins(business, data.get("logins"))
        db.session.commit()
    return jsonify({"ok": True, **org_service.payload(business)})


@org_bp.route("/api/hub/org/save", methods=["POST"])
def hub_org_save():
    """One change, the same shape the board's own form sends. Shares are the
    board's and are never taken from here. A stale version answers 409 with the
    org as it now is, so the app can draw what is true."""
    business, refused, data = _hub()
    if refused:
        return refused
    if "logins" in data:
        org_service.record_logins(business, data.get("logins"))
    by = str(data.get("by") or business.hub_slug or "")[:200]
    try:
        said = org_service.save(business, data, by=by, allow_share=False)
    except org_service.Refused as err:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(err), **org_service.payload(business)}), err.status
    return jsonify({"ok": True, "said": said, **org_service.payload(business)})


@org_bp.route("/api/hub/org/import", methods=["POST"])
def hub_org_import():
    """The app's org as its own page holds it, once. Refused (409) once the
    board's copy has been edited, because from then on the board's rows are
    the org."""
    business, refused, data = _hub()
    if refused:
        return refused
    try:
        counts = org_service.import_org(business, data, business.hub_slug or "app")
    except org_service.Refused as err:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(err), **org_service.payload(business)}), err.status
    return jsonify({"ok": True, "imported": counts, **org_service.payload(business)})


# ── The old address ─────────────────────────────────────────
# Team > Users lived at /admin/users until 2026-11-04. A bookmark lands on the
# Logins tab, and a page left open across the deploy still posts its forms to
# the old write addresses, so those answer 307 (method and form kept), limited
# to the shapes that route ever took. Both ask the same CEO gate as the pages.

old_users_bp = Blueprint("old_users", __name__, url_prefix="/admin/users")


@old_users_bp.route("/")
@old_users_bp.route("/new")
@old_users_bp.route("/<int:id>/edit")
@ceo_required
def moved(id=None):
    if request.path.rstrip("/").endswith("/new"):
        return redirect(url_for("users.create"), 301)
    if id is not None:
        return redirect(url_for("users.edit", id=id), 301)
    return redirect(url_for("users.index"), 301)


@old_users_bp.route("/new", methods=["POST"], endpoint="moved_create")
@old_users_bp.route("/<int:id>/<any(edit, reset, switch):verb>", methods=["POST"], endpoint="moved_write")
@ceo_required
def moved_write(id=None, verb=None):
    if id is None:
        return redirect(url_for("users.create"), 307)
    return redirect(url_for(f"users.{verb}", id=id), 307)
