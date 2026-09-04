"""The catalogue's inbox: what the field has proposed, and the one screen
where Michael agrees or does not.

Every change a session sends through the guidance API lands here as a
CatalogueProposal. The additive ones arrived already applied and sit in
the "live" list with a Revert; the rewrites wait at the top with the words
they would replace beside the words they would put there, and Accept or
Reject is one press. This is where "Claude's best practices that I agree
with" gets its "that I agree with".
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required

from models import db, CatalogueProposal
from pm.guidance_routes import (apply_proposal, revert_proposal, target_label,
                                steps_text)

inbox_bp = Blueprint("inbox", __name__, url_prefix="/admin/features/inbox")


def _back():
    """Where a decision returns to. The attention hub posts here too and
    wants its own page back; anything that is not a same-site path is
    ignored rather than followed."""
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return url_for("inbox.inbox_index")

FIELD_LABELS = {
    "name": "name", "display_name": "name", "summary": "summary",
    "one_liner": "one-liner", "gold_standard_md": "how to build it",
    "pitfalls_md": "what went wrong", "reference_project": "reference project",
    "reference_path": "file worth copying", "typical_value": "worth",
    "vendor_url": "vendor URL", "client_only_md": "what only the client can do",
    "access_grant_md": "the access to ask for", "your_steps_md": "the steps",
    "traps_md": "the traps", "verify_md": "how to verify",
    "prompt_intro": "prompt intro", "playbook_slug": "runbook",
    "price": "price", "monthly_price": "monthly price", "*": "",
    "steps": "the checklist",
}

MODE_VERBS = {"append": "Added to", "replace": "Rewrites", "create": "Created"}


def _decorate(rows):
    for p in rows:
        p.label = target_label(p.kind, p.target_slug)
        p.kind_label = CatalogueProposal.KIND_LABELS.get(p.kind, p.kind)
        p.field_label = FIELD_LABELS.get(p.field, p.field)
        p.verb = MODE_VERBS.get(p.mode, p.mode)
        p.payload = {}
        if p.payload_json:
            try:
                p.payload = {k: v for k, v in json.loads(p.payload_json).items()
                             if v not in (None, "", [])}
            except ValueError:
                p.payload = {}
        # The checklist reads as numbered lines here, and the snapshot kept
        # for revert is not for display.
        p.payload.pop("previous_steps", None)
        if isinstance(p.payload.get("steps"), list):
            p.payload["steps"] = steps_text(p.payload["steps"])
    return rows


@inbox_bp.route("/")
@login_required
def inbox_index():
    base = CatalogueProposal.query.order_by(CatalogueProposal.created_at.desc())
    pending = _decorate(base.filter_by(status="pending").all())
    live = _decorate(base.filter(CatalogueProposal.status.in_(("applied", "accepted")))
                     .limit(40).all())
    closed = _decorate(base.filter(CatalogueProposal.status.in_(("rejected", "reverted")))
                       .limit(20).all())
    return render_template("pm/features/inbox.html",
                           pending=pending, live=live, closed=closed)


def _decide(proposal, status):
    proposal.status = status
    proposal.decided_at = datetime.now(timezone.utc)


@inbox_bp.route("/<int:id>/accept", methods=["POST"])
@login_required
def accept(id):
    proposal = db.session.get(CatalogueProposal, id) or abort(404)
    if proposal.status != "pending":
        flash("That one has already been decided.", "warning")
        return redirect(_back())
    ok, message = apply_proposal(proposal)
    if not ok:
        db.session.rollback()
        flash(f"Could not apply it: {message}.", "warning")
        return redirect(_back())
    _decide(proposal, "accepted")
    db.session.commit()
    flash("Accepted. It is in the catalogue now.", "success")
    return redirect(_back())


@inbox_bp.route("/<int:id>/reject", methods=["POST"])
@login_required
def reject(id):
    proposal = db.session.get(CatalogueProposal, id) or abort(404)
    if proposal.status != "pending":
        flash("That one has already been decided.", "warning")
        return redirect(_back())
    _decide(proposal, "rejected")
    db.session.commit()
    flash("Rejected. Nothing changed.", "success")
    return redirect(_back())


@inbox_bp.route("/<int:id>/revert", methods=["POST"])
@login_required
def revert(id):
    proposal = db.session.get(CatalogueProposal, id) or abort(404)
    if not proposal.is_live:
        flash("That one is not live, so there is nothing to put back.", "warning")
        return redirect(_back())
    ok, message = revert_proposal(proposal)
    if not ok:
        db.session.rollback()
        flash(f"Could not revert it: {message}.", "warning")
        return redirect(_back())
    _decide(proposal, "reverted")
    db.session.commit()
    flash("Reverted. The catalogue reads as it did before.", "success")
    return redirect(_back())
