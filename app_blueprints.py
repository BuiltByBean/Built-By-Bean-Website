"""Blueprints: a whole app, end to end, as something to start the next one from.

The pieces every caller shares, so the page, the door (/api/guidance) and the
MVP Builder's prompt cannot describe one blueprint three ways:

  normalise_stages   the build order a session sent, checked, with each
                     playbook and feature it names resolved to a slug that
                     exists. A name that matches nothing is reported back and
                     left out, never stored as a guess: a stage that links a
                     playbook nobody wrote reads as covered when it is not.
  blueprint_lines    the blueprint as text, the way a fresh session reads it.
  match_links        which My Apps tile and which business a new blueprint
                     belongs to, by name, so its page can link the running
                     app and the business map.

Kept in this module rather than models.py because it reads three other
tables, and named app_blueprints because "blueprint" alone is Flask's word in
every route file.
"""
import json
import re

MAX_STAGES = 30
STAGE_FIELD = "stages"


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _cap(value, bound):
    return str(value or "").strip()[:bound]


def resolve_playbooks(names):
    """[slug], [unmatched] for the playbook names or slugs given."""
    from models import Playbook
    rows = Playbook.query.filter_by(is_active=True).all()
    index = {}
    for p in rows:
        for key in (p.slug, p.display_name):
            index.setdefault(_norm(key), p.slug)
    return _resolve(names, index)


def resolve_features(names):
    """[slug], [unmatched] for the feature or rule names or slugs given."""
    from models import Feature
    rows = Feature.query.filter_by(is_active=True).all()
    index = {}
    for f in rows:
        for key in (f.slug, f.name):
            index.setdefault(_norm(key), f.slug)
    return _resolve(names, index)


def _resolve(names, index):
    found, missing = [], []
    for name in names or []:
        if not isinstance(name, str) or not name.strip():
            continue
        slug = index.get(_norm(name))
        if slug is None:
            missing.append(name.strip())
        elif slug not in found:
            found.append(slug)
    return found, missing


def normalise_stages(raw):
    """The build order a session sent. Returns (stages, error, unmatched)."""
    if not isinstance(raw, list) or not raw:
        return None, "stages must be a non-empty list", []
    if len(raw) > MAX_STAGES:
        return None, f"at most {MAX_STAGES} stages", []
    out, unmatched = [], []
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            return None, f"stage {i} must be an object with a title", []
        title = _cap(item.get("title"), 200)
        if not title:
            return None, f"stage {i} needs a title", []
        playbooks, missing_p = resolve_playbooks(item.get("playbooks") or [])
        features, missing_f = resolve_features(item.get("features") or [])
        unmatched += [f"playbook {n}" for n in missing_p] + [f"feature {n}" for n in missing_f]
        out.append({"title": title, "detail_md": _cap(item.get("detail_md"), 6000),
                    "playbooks": playbooks, "features": features})
    return out, None, unmatched


def stages_snapshot(blueprint):
    return [{"title": s.title, "detail_md": s.detail_md or "",
             "playbooks": s.playbook_list, "features": s.feature_list}
            for s in blueprint.stages.all()]


def stages_text(stages):
    """The build order as History reads it: one numbered line per stage."""
    return "\n".join(f"{i}. {s.get('title', '')}" for i, s in enumerate(stages or [], 1))


def write_stages(blueprint, stages, start=1):
    from models import db, AppBlueprintStage
    for offset, s in enumerate(stages):
        db.session.add(AppBlueprintStage(
            blueprint_id=blueprint.id, position=start + offset, title=s["title"],
            detail_md=s.get("detail_md") or "",
            playbooks_json=json.dumps(s.get("playbooks") or []),
            features_json=json.dumps(s.get("features") or [])))


def clear_stages(blueprint):
    from models import db
    for s in blueprint.stages.all():
        db.session.delete(s)
    db.session.flush()


def match_links(name):
    """(app_id, business_id) for a blueprint called `name`, by name."""
    from models import AppLink, Business
    want = _norm(name)
    if not want:
        return None, None
    app = next((a for a in AppLink.query.order_by(AppLink.id).all() if _norm(a.name) == want), None)
    business = next((b for b in Business.query.order_by(Business.id).all()
                     if want in (_norm(b.short_name), _norm(b.name),
                                 _norm(re.sub(r"\b(llc|inc|ltd)\b\.?", "", b.name or "", flags=re.I)))),
                    None)
    return (app.id if app else None), (business.id if business else None)


def names_for(slugs, kind):
    """{slug: display name} for linked entries that still exist and are on."""
    from models import Feature, Playbook
    if not slugs:
        return {}
    if kind == "playbook":
        rows = Playbook.query.filter(Playbook.slug.in_(slugs), Playbook.is_active.is_(True)).all()
        return {p.slug: p.display_name for p in rows}
    rows = Feature.query.filter(Feature.slug.in_(slugs), Feature.is_active.is_(True)).all()
    return {f.slug: f.name for f in rows}


_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def tidy_md(text):
    """A list straight under a line of prose, with no blank line between, is
    one paragraph to the markdown renderer: "Who uses it. - Tenants ... -
    Talent ..." in a single run. Sessions write it that way more often than
    not, so the page puts the blank line in rather than asking every writer
    to remember it."""
    out, prev = [], ""
    for line in (text or "").splitlines():
        if _LIST_ITEM.match(line) and prev.strip() and not _LIST_ITEM.match(prev) \
                and not prev.startswith((" ", "\t")):
            out.append("")
        out.append(line)
        prev = line
    return "\n".join(out)


def blueprint_lines(blueprint, indent=""):
    """The blueprint as a fresh session reads it, through the door and at the
    top of a build prompt. Playbooks and features are named with their slugs,
    so the session can fetch each one whole when it reaches that stage."""
    out = [f"{indent}BLUEPRINT: {blueprint.name}"]
    if (blueprint.one_liner or "").strip():
        out.append(f"{indent}  {blueprint.one_liner.strip()}")
    if (blueprint.source_repos or "").strip():
        out.append(f"{indent}  Read from: {blueprint.source_repos.strip()} (gh repo clone to look "
                   "at how any part was really done).")
    out.append("")
    for section in blueprint.sections:
        body = section["body"].strip()
        if not body:
            continue
        out.append(f"{indent}{section['heading'].upper()}")
        out.extend(f"{indent}  {line}" for line in body.splitlines())
        out.append("")
    stages = blueprint.stages.all()
    if stages:
        pnames = names_for(blueprint.playbook_slugs, "playbook")
        fslugs = [f for s in stages for f in s.feature_list]
        fnames = names_for(fslugs, "feature")
        out.append(f"{indent}THE BUILD ORDER")
        for i, stage in enumerate(stages, 1):
            out.append(f"{indent}  {i}. {stage.title}")
            if (stage.detail_md or "").strip():
                out.extend(f"{indent}     {line}" for line in stage.detail_md.strip().splitlines())
            pb = [f"{pnames[s]} ({s})" for s in stage.playbook_list if s in pnames]
            ft = [f"{fnames[s]} ({s})" for s in stage.feature_list if s in fnames]
            if pb:
                out.append(f"{indent}     Playbooks: " + ", ".join(pb) + ". get_playbook each before you start it.")
            if ft:
                out.append(f"{indent}     Features and rules: " + ", ".join(ft) + ".")
        out.append("")
    return out
