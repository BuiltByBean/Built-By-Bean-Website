"""Blueprints in Best Practices: the list, and one blueprint end to end.

Read only on purpose, the same as rules and playbooks: a blueprint is written
by the session that read the app's repos, through the door (suggest_update,
kind blueprint), and kept current the same way. One typed in here from memory
would describe the app as somebody remembers it, which is the thing a
blueprint exists to replace. History has a Revert for every change.
"""
from flask import Blueprint, abort, render_template, url_for
from flask_login import login_required

import app_blueprints
from models import AppBlueprint, Playbook

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
    return render_template("pm/blueprints/detail.html", b=b, stages=stages,
                           pnames=pnames, fnames=fnames)
