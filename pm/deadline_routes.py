"""The deadline list, the state's flags, and the presses that clear them.

  /admin/taxes/deadlines                 every date ahead, and what proved each done
  /admin/taxes/deadlines/done            Done on a deadline no record can prove
  /admin/taxes/deadlines/undo            take a Done back
  /admin/taxes/flags/<id>/seen           a change in the state's records, seen
  /admin/businesses/<id>/comptroller     read the state's records for one business now

CEO only, like the returns: these are one company's dealings with the state.
The arithmetic is deadlines.py and comptroller.py; this only reads and writes.
"""
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

import comptroller
import deadlines
from models import db, Business, ComptrollerFlag, DeadlineDone
from pm.users_routes import ceo_required

deadline_bp = Blueprint("taxes_deadlines", __name__)


def _back(default):
    """Back to the page the press came from, on this board only."""
    to = request.form.get("next") or ""
    return redirect(to if to.startswith("/admin/") and not to.startswith("//") else default)


@deadline_bp.route("/admin/taxes/deadlines")
@ceo_required
def index():
    rows = deadlines.build()
    businesses = (Business.query.filter_by(is_active=True, parent_id=None)
                  .order_by(Business.name, Business.id).all())
    return render_template(
        "pm/taxes/deadlines.html", rows=rows, businesses=businesses,
        standing=deadlines.standing_problems(businesses), flags=deadlines.open_flags(),
        lead_days=deadlines.LEAD_DAYS)


@deadline_bp.route("/admin/taxes/deadlines/done", methods=["POST"])
@ceo_required
def done():
    key = (request.form.get("key") or "").strip()[:80]
    if not key or ":" not in key:
        abort(400)
    if DeadlineDone.query.filter_by(key=key).first() is None:
        db.session.add(DeadlineDone(key=key, done_by=getattr(current_user, "username", "") or ""))
        db.session.commit()
    deadlines.forget()
    flash("Marked done.", "success")
    return _back(url_for("taxes_deadlines.index"))


@deadline_bp.route("/admin/taxes/deadlines/undo", methods=["POST"])
@ceo_required
def undo():
    row = DeadlineDone.query.filter_by(key=(request.form.get("key") or "").strip()[:80]).first()
    if row is not None:
        db.session.delete(row)
        db.session.commit()
    deadlines.forget()
    flash("Back on the list.", "success")
    return _back(url_for("taxes_deadlines.index"))


@deadline_bp.route("/admin/taxes/flags/<int:id>/seen", methods=["POST"])
@ceo_required
def flag_seen(id):
    flag = db.session.get(ComptrollerFlag, id) or abort(404)
    flag.seen_at = datetime.now(timezone.utc)
    flag.seen_by = getattr(current_user, "username", "") or ""
    db.session.commit()
    deadlines.forget()
    return _back(url_for("taxes_deadlines.index"))


@deadline_bp.route("/admin/businesses/<int:id>/comptroller", methods=["POST"])
@ceo_required
def read_now(id):
    """The franchise record and the permit list for one business, now. The
    nightly run does the same for every business."""
    business = db.session.get(Business, id) or abort(404)
    if business.is_division:
        abort(404)
    said = []
    try:
        said += comptroller.read_franchise(business)
        said += comptroller.read_permits(business)
        db.session.commit()
    except Exception as err:  # noqa: BLE001 - the state's site being down is a message, not a 500
        db.session.rollback()
        flash(f"The Comptroller did not answer: {str(err)[:160]}", "error")
        return redirect(url_for("businesses.detail", id=business.id))
    deadlines.forget()
    flash("Read from the Comptroller. " + ("; ".join(said) if said else "Nothing changed."), "success")
    return redirect(url_for("businesses.detail", id=business.id))
