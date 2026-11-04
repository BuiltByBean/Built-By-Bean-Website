"""Each app on the support board: its quick links, and for a business's own
desk, the API door the board reads it through.

CEO only, on the route: a desk key answers customers in Michael's name, and
the links are his to point. Everything else about the board lives with the
ticket routes in app.py.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from models import db, Business, SupportApp
from pm.users_routes import ceo_required
import support_service

support_bp = Blueprint("support", __name__, url_prefix="/admin/tickets/apps")

LINK_FIELDS = ("support_url", "admin_url", "site_url", "status_url")


def _url(name):
    """An address off the form, or "" for anything that is not http(s).

    These land in an href on the board, so a `javascript:` typed or pasted
    here would run on the next press. Refused rather than escaped.
    """
    raw = (request.form.get(name) or "").strip()
    if raw.lower().startswith(("https://", "http://")):
        return raw.rstrip("/")[:300]
    return ""


@support_bp.route("/<int:id>", methods=["GET", "POST"])
@ceo_required
def edit(id):
    app = db.session.get(SupportApp, id)
    if app is None:
        flash("No such app.", "warning")
        return redirect(url_for("pm.tickets_list"))
    if request.method == "POST":
        app.name = (request.form.get("name") or app.name or app.origin).strip()[:120]
        for field in LINK_FIELDS:
            setattr(app, field, _url(field))
        if app.is_desk:
            app.desk_url = _url("desk_url")
            app.desk_acting_for = (request.form.get("desk_acting_for") or "").strip()[:200]
            bid = request.form.get("business_id", type=int)
            app.business_id = bid if bid and db.session.get(Business, bid) else None
            key = (request.form.get("desk_key") or "").strip()
            if request.form.get("forget_key"):
                app.desk_key = None
            elif key:
                # Typed once, never shown again: the form only ever says
                # whether one is on file.
                app.desk_key = key
        db.session.commit()
        if app.is_desk and app.desk_ready:
            note = support_service.pull_desk(app)
            flash(f"Saved. Read its desk: {note}.", "success" if " read," in note else "warning")
        else:
            flash("Saved.", "success")
        return redirect(url_for("pm.tickets_list", app=app.origin))
    businesses = Business.query.order_by(Business.name).all()
    return render_template("pm/tickets/app_form.html", app=app, businesses=businesses)
