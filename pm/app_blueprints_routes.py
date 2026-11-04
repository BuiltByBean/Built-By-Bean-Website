"""Blueprints in Best Practices: the list, and one blueprint end to end.

Read only on purpose, the same as rules and playbooks: a blueprint is written
by the session that read the app's repos, through the door (suggest_update,
kind blueprint), and kept current the same way. One typed in here from memory
would describe the app as somebody remembers it, which is the thing a
blueprint exists to replace. History has a Revert for every change.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

import app_blueprints
from models import AppBlueprint, AppGap, Playbook

app_blueprints_bp = Blueprint("blueprints", __name__, url_prefix="/admin/blueprints")


@app_blueprints_bp.app_template_filter("tidy_md")
def _tidy_md(text):
    return app_blueprints.tidy_md(text)


def _mark(playbook):
    if playbook.logo_path:
        return url_for("static", filename=playbook.logo_path)
    if playbook.icon_file:
        return url_for("playbooks.icon", slug=playbook.slug)
    return None


@app_blueprints_bp.route("/")
@login_required
def blueprints_index():
    rows = (AppBlueprint.query.filter_by(is_active=True)
            .order_by(AppBlueprint.sort_order, AppBlueprint.name).all())
    cards = []
    for b in rows:
        playbooks = (Playbook.query.filter(Playbook.slug.in_(b.playbook_slugs)).all()
                     if b.playbook_slugs else [])
        order = {s: i for i, s in enumerate(b.playbook_slugs)}
        playbooks.sort(key=lambda p: order.get(p.slug, 0))
        cards.append({"b": b, "stages": b.stages.count(),
                      "marks": [(p.display_name, _mark(p), p.initials) for p in playbooks]})
    return render_template("pm/blueprints/index.html", cards=cards)


@app_blueprints_bp.route("/<slug>")
@login_required
def blueprint_detail(slug):
    b = AppBlueprint.query.filter_by(slug=slug).first() or abort(404)
    stages = b.stages.all()
    pnames = {}
    for p in Playbook.query.filter(Playbook.slug.in_(b.playbook_slugs)).all() if b.playbook_slugs else []:
        pnames[p.slug] = {"name": p.display_name, "mark": _mark(p), "initials": p.initials,
                          "on": p.is_active}
    fslugs = [f for s in stages for f in s.feature_list]
    fnames = app_blueprints.names_for(fslugs, "feature")
    gaps = b.gaps.filter_by(status="open").order_by(AppGap.kind, AppGap.id).all()
    return render_template("pm/blueprints/detail.html", b=b, stages=stages,
                           pnames=pnames, fnames=fnames, gaps=gaps)


# ── Gaps ──────────────────────────────────────────────
# What one app should catch up on, from the Tend run (tend_service.file_gaps).
# Michael closes each as done or not wanted; a closed one is never reopened by
# a run, and Reopen here is the only way back.


def _back(default):
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return default


@app_blueprints_bp.route("/gaps")
@login_required
def gaps_index():
    view = "closed" if request.args.get("view") == "closed" else "open"
    q = AppGap.query.join(AppBlueprint, AppGap.blueprint_id == AppBlueprint.id) \
        .filter(AppBlueprint.is_active.is_(True))
    q = q.filter(AppGap.status == "open") if view == "open" else q.filter(AppGap.status != "open")
    rows = q.order_by(AppBlueprint.name, AppGap.kind, AppGap.id).all()
    groups = {}
    for g in rows:
        groups.setdefault(g.blueprint, []).append(g)
    closed = (AppGap.query.join(AppBlueprint, AppGap.blueprint_id == AppBlueprint.id)
              .filter(AppBlueprint.is_active.is_(True), AppGap.status != "open").count())
    return render_template("pm/blueprints/gaps.html", groups=list(groups.items()), view=view,
                           closed=closed)


@app_blueprints_bp.route("/gaps/<int:id>/<status>", methods=["POST"])
@login_required
def gap_decide(id, status):
    from datetime import datetime, timezone
    from models import db
    gap = db.session.get(AppGap, id) or abort(404)
    if status not in dict(AppGap.STATUSES):
        abort(400)
    gap.status = status
    gap.decided_at = None if status == "open" else datetime.now(timezone.utc)
    db.session.commit()
    flash({"done": "Marked done.", "dismissed": "Not wanted. It will not be suggested again.",
           "open": "Reopened."}[status], "success")
    return redirect(_back(url_for("blueprints.gaps_index")))
