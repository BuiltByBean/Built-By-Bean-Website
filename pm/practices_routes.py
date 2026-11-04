"""Best Practices: everything a Claude session should know before it builds.

Michael, 2026-11-02: the Catalogue (features, rules, playbooks, Cerebro) "was
a good idea on paper, but it's not functional ... all of this should just be
merged into one, call it best practices repository for everything that I work
on, and just something for any time Claude is working on any of my repos."

So the sidebar carries one link, Best Practices, and every page that used to
be its own entry sits behind one tab strip (`pm/practices/_tabs.html`):

  Everything     this page: one search across every rule, feature and
                 playbook, filtered in place by type.
  Rules          features.rules_index: ways of building that always hold,
                 and every build prompt carries them.
  Features       features.features_index: what has been built before, which
                 is the list the MVP Builder picks from, and the on-a-call
                 quick-add.
  Playbooks      playbooks.playbooks_index: how each vendor gets set up.
  History        inbox.inbox_index: what changed, and who changed it. A
                 session's change applies on arrival and the nightly curator
                 (curate_practices.py) merges, tightens and retires, so
                 nothing waits on a yes; this is where any of it goes back
                 in one press. It was a "Waiting" tab for a day, until
                 Michael said to stop the waiting altogether.

No money lives anywhere in here (Michael, 2026-11-03: "no price shit left
over"). Products carried prices and the sell flow, so that page left the tab
strip on 2026-11-04 for a sidebar link of its own.

The pages keep their own URLs and endpoints, because the MVP Builder, the
tax guide, project pages and the guidance API all link into them. Cerebro's
page is gone (its index redirects here); the nightly scanner still runs.

Nothing here changes what a session reads: get_rules, get_feature_guidance
and get_playbook answer from the same rows through /api/guidance.
"""
from flask import Blueprint, render_template, url_for
from flask_login import login_required

from models import AppBlueprint, Feature, Playbook

practices_bp = Blueprint("practices", __name__, url_prefix="/admin/practices")

# What each kind of entry is called on its badge, and the badge's colour.
TYPE_LABEL = {"rule": "Rule", "howto": "Feature", "playbook": "Playbook", "blueprint": "Blueprint"}
TYPE_TONE = {
    "rule": "bg-violet-500/15 text-violet-300",
    "howto": "bg-sky-500/15 text-sky-300",
    "playbook": "bg-emerald-500/15 text-emerald-300",
    "blueprint": "bg-amber-500/15 text-amber-300",
}


@practices_bp.app_template_global("practices_counts")
def practices_counts():
    """The tab strip's numbers, on every page that draws it."""
    return {
        "rule": Feature.query.filter_by(is_active=True, kind="rule").count(),
        "howto": Feature.query.filter_by(is_active=True, kind="feature").count(),
        "playbook": Playbook.query.filter_by(is_active=True).count(),
        "blueprint": AppBlueprint.query.filter_by(is_active=True).count(),
    }


def _hay(*parts):
    return " ".join(p for p in parts if p).lower()


def entries():
    """Every entry, in one list: rules, then features, then playbooks.

    Each is a plain dict the page renders the same way: a type, a name, a
    line under it, the text the search runs over, and where to go to change
    it. The search covers the guidance and the traps, not just the title,
    because half the worth of a lesson is being found by its symptom.
    """
    out = []
    features = (Feature.query.filter_by(is_active=True)
                .order_by(Feature.kind.desc(), Feature.sort_order, Feature.name).all())
    for f in features:
        kind = "rule" if f.kind == "rule" else "howto"
        edit = url_for("features.rules_index" if kind == "rule" else "features.features_index", q=f.name)
        out.append({
            "key": f"f{f.id}", "type": kind, "name": f.name, "line": f.summary or "",
            "category": f.category_label, "gold": f.gold_standard_md or "", "traps": f.pitfalls_md or "",
            "reference": f.reference_project or "", "path": f.reference_path or "",
            "idea": f.status == "idea",
            "edit": edit,
            "search": _hay(f.name, f.summary, f.gold_standard_md, f.pitfalls_md, f.reference_project,
                           f.category_label),
        })
    for p in Playbook.query.filter_by(is_active=True).order_by(Playbook.sort_order, Playbook.display_name):
        mark = None
        if p.logo_path:
            mark = url_for("static", filename=p.logo_path)
        elif p.icon_file:
            mark = url_for("playbooks.icon", slug=p.slug)
        steps = p.steps.count()
        out.append({
            "key": f"p{p.id}", "type": "playbook", "name": p.display_name, "line": p.one_liner or "",
            "category": p.category_label, "mark": mark, "initials": p.initials, "steps": steps,
            "sections": [s for s in p.sections if s["body"].strip()],
            "open": url_for("playbooks.playbook_detail", slug=p.slug),
            "edit": url_for("playbooks.playbook_edit", slug=p.slug),
            "search": _hay(p.display_name, p.slug, p.one_liner, p.category_label,
                           *[s["body"] for s in p.sections]),
        })
    # Blueprints first in their own tab; here they are found by any word of
    # the app they describe, a part, a connection or a trap.
    for b in AppBlueprint.query.filter_by(is_active=True).order_by(AppBlueprint.sort_order, AppBlueprint.name):
        stages = b.stages.all()
        out.append({
            "key": f"b{b.id}", "type": "blueprint", "name": b.name, "line": b.one_liner or "",
            "category": None, "steps": len(stages),
            "sections": [s for s in b.sections if s["body"].strip()],
            "open": url_for("blueprints.blueprint_detail", slug=b.slug),
            "search": _hay(b.name, b.slug, b.one_liner, b.source_repos,
                           *[s["body"] for s in b.sections], *[st.title for st in stages]),
        })
    return out


@practices_bp.route("/")
@login_required
def index():
    return render_template("pm/practices/index.html", entries=entries(),
                           type_label=TYPE_LABEL, type_tone=TYPE_TONE)
