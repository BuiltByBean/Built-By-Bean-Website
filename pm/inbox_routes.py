"""Best Practices' History tab: what changed, who changed it, and the way back.

Nothing here waits on anybody. Until 2026-11-02 this was an inbox where a
rewrite sat until Michael pressed Accept; 188 piled up, and he asked for it
to "just adjust properly over time". So every change a session sends now
applies on arrival, the nightly curator (curate_practices.py) merges,
tightens and retires, and this page is the record: the curator's nights at
the top, then every change newest first, each with Revert. The URL stayed
put because sessions and older notes link to it.
"""
import json

import app_blueprints
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required

from models import db, CatalogueProposal, CuratorRun
from pm.guidance_routes import revert_proposal, target_label, steps_text

inbox_bp = Blueprint("inbox", __name__, url_prefix="/admin/features/inbox")

# What the record shows. Candidates are notes for the curator, not changes,
# and a discarded one changed nothing.
SHOWN = ("applied", "accepted", "reverted", "rejected")
PAGE = 80


def _back():
    """Where a press returns to; anything not a same-site path is ignored."""
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return url_for("inbox.inbox_index")


FIELD_LABELS = {
    "name": "name", "display_name": "name", "summary": "summary",
    "one_liner": "one-liner", "gold_standard_md": "how to build it",
    "pitfalls_md": "what went wrong", "reference_project": "reference project",
    "reference_path": "file worth copying", "category": "area",
    "vendor_url": "vendor URL", "client_only_md": "what only the client can do",
    "access_grant_md": "the access to ask for", "your_steps_md": "the steps",
    "traps_md": "the traps", "verify_md": "how to verify",
    "prompt_intro": "prompt intro", "playbook_slug": "playbook",
    "*": "",
    "steps": "the checklist", "check_pattern": "scanner",
    "check_globs": "scanner files", "check_exclude": "scanner exclusions",
    "check_unless": "scanner exceptions", "check_fixture": "scanner fixture",
    "shape_md": "what it is", "parts_md": "the parts", "connections_md": "how they talk",
    "tweaks_md": "what changes per project", "source_repos": "repos",
    "stages": "the build order", "map": "the map",
}

MODE_VERBS = {"append": "Added to", "replace": "Rewrote", "create": "Created",
              "retire": "Retired"}


def _decorate(rows):
    for p in rows:
        p.label = target_label(p.kind, p.target_slug)
        p.kind_label = CatalogueProposal.KIND_LABELS.get(p.kind, p.kind)
        p.field_label = FIELD_LABELS.get(p.field, p.field)
        p.verb = MODE_VERBS.get(p.mode, p.mode)
        p.by_curator = (p.project or "").startswith("curator")
        p.payload = {}
        if p.payload_json:
            try:
                p.payload = {k: v for k, v in json.loads(p.payload_json).items()
                             if v not in (None, "", [])}
            except ValueError:
                p.payload = {}
        p.payload.pop("previous_steps", None)
        p.payload.pop("previous_stages", None)
        p.payload.pop("previous_map", None)
        p.payload.pop("changes", None)
        if isinstance(p.payload.get("steps"), list):
            p.payload["steps"] = steps_text(p.payload["steps"])
        if isinstance(p.payload.get("stages"), list):
            p.payload["stages"] = app_blueprints.stages_text(p.payload["stages"])
    return rows


@inbox_bp.route("/")
@login_required
def inbox_index():
    changes = _decorate(
        CatalogueProposal.query.filter(CatalogueProposal.status.in_(SHOWN))
        .order_by(CatalogueProposal.created_at.desc(), CatalogueProposal.id.desc())
        .limit(PAGE).all())
    runs = (CuratorRun.query.order_by(CuratorRun.started_at.desc(), CuratorRun.id.desc())
            .limit(7).all())
    week = datetime.now(timezone.utc) - timedelta(days=7)
    this_week = (CatalogueProposal.query
                 .filter(CatalogueProposal.status.in_(("applied", "accepted")))
                 .filter(CatalogueProposal.created_at >= week.replace(tzinfo=None))
                 .count())
    queued = CatalogueProposal.query.filter_by(status="candidate").count()
    return render_template("pm/features/inbox.html", changes=changes, runs=runs,
                           last_run=runs[0] if runs else None,
                           this_week=this_week, queued=queued)


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
    proposal.status = "reverted"
    proposal.decided_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Reverted. Best Practices reads as it did before.", "success")
    return redirect(_back())
