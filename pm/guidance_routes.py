"""The god door: what every other Claude asks before it builds.

Every repo on this machine gets built by its own session, and every one of
them used to relearn this board's lessons the hard way. These endpoints
hand the catalogue out live - the rules that hold on every build, the
guidance behind any feature, the vendor runbooks - and take lessons BACK,
which is the half that keeps the thing alive: a landmine hit in any
project lands here once and briefs every build that follows.

Bearer token on every route, compared in constant time - string equality
returns at the first differing byte, and how long that took is a
measurement. No token configured means the door is closed, not open. The
gate is a blueprint-wide before_request, so a route added later is
protected by default rather than by memory.
"""
import hmac
import re
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, request

from models import db, Feature, Playbook

guidance_bp = Blueprint("guidance", __name__, url_prefix="/api/guidance")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(value):
    return _SLUG_STRIP.sub("-", (value or "").strip().lower()).strip("-")[:80]


# Everything but tab, newline and carriage return. Postgres refuses a NUL
# in a text column outright, so one stray byte in a reported lesson was a
# 500 instead of a record - found when the lesson ABOUT stray control
# bytes failed to file because it contained some.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _cap(value, bound):
    """Public-facing write discipline: scrub control characters and truncate
    to a bound, never trusting the wire to be reasonable about either."""
    return _CONTROL.sub("", (value or "")).strip()[:bound]


def _authorised():
    expect = current_app.config.get("GUIDANCE_API_KEY", "")
    if not expect:
        return False
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    return bool(token) and hmac.compare_digest(token, expect)


@guidance_bp.before_request
def _gate():
    if not _authorised():
        return jsonify({"error": "unauthorised"}), 401


def _entry(feature):
    return {
        "slug": feature.slug,
        "name": feature.name,
        "kind": feature.kind,
        "category": feature.category_label,
        "summary": feature.summary or "",
        "how_to_build": feature.gold_standard_md or "",
        "what_went_wrong": feature.pitfalls_md or "",
        "worth_copying": (
            feature.reference_project
            + (f" - {feature.reference_path}" if feature.reference_path else "")
        ) if feature.reference_project else "",
    }


@guidance_bp.route("/rules")
def rules():
    rows = (Feature.query.filter_by(is_active=True, kind="rule")
            .order_by(Feature.sort_order, Feature.name).all())
    return jsonify({"rules": [_entry(r) for r in rows]})


@guidance_bp.route("/brief")
def brief():
    """Every rule as one piece of text, for a session that wants the whole
    briefing in one call. Assembled by the same code that writes the MVP
    build prompts, so the two can never say different things."""
    from pm.mvp_routes import _house_rules
    lines = _house_rules()
    if not lines:
        lines = ["No rules recorded yet."]
    return Response("\n".join(lines), mimetype="text/plain")


@guidance_bp.route("/search")
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "give q"}), 400
    like = f"%{query}%"
    rows = (Feature.query.filter_by(is_active=True)
            .filter(db.or_(Feature.name.ilike(like),
                           Feature.summary.ilike(like),
                           Feature.gold_standard_md.ilike(like),
                           Feature.pitfalls_md.ilike(like),
                           Feature.reference_project.ilike(like)))
            .order_by(Feature.kind.desc(), Feature.sort_order)
            .limit(20).all())
    return jsonify({"query": query, "matches": [_entry(r) for r in rows]})


@guidance_bp.route("/features/<slug>")
def feature_detail(slug):
    feature = Feature.query.filter_by(slug=slug, is_active=True).first()
    if feature is None:
        return jsonify({"error": "no such entry"}), 404
    return jsonify(_entry(feature))


@guidance_bp.route("/playbooks")
def playbooks():
    rows = (Playbook.query.filter_by(is_active=True)
            .order_by(Playbook.sort_order, Playbook.display_name).all())
    return jsonify({"playbooks": [
        {"slug": p.slug, "name": p.display_name, "one_liner": p.one_liner or ""}
        for p in rows]})


@guidance_bp.route("/playbooks/<slug>")
def playbook_detail(slug):
    playbook = Playbook.query.filter_by(slug=slug, is_active=True).first()
    if playbook is None:
        return jsonify({"error": "no such playbook"}), 404
    from pm.products_routes import playbook_lines
    return jsonify({"slug": playbook.slug, "name": playbook.display_name,
                    "runbook": "\n".join(playbook_lines(playbook))})


@guidance_bp.route("/lessons", methods=["POST"])
def report_lesson():
    """A lesson learned somewhere else lands in the catalogue.

    Append when the entry exists, create when it does not, and never write
    the same words twice - the reporting session retries like every other
    client of an API, so a duplicate delivery is the normal case. What
    arrives is stamped with who learned it, because a pitfall with no
    provenance ages into a superstition.
    """
    body = request.get_json(silent=True) or {}
    wrong = _cap(body.get("what_went_wrong"), 4000)
    gold = _cap(body.get("how_to_build"), 4000)
    project = _cap(body.get("project"), 120)
    if not wrong or not project:
        return jsonify({"error": "what_went_wrong and project are both "
                                 "required - a lesson is what happened and "
                                 "who it happened to"}), 400

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    attributed = f"({project}, {stamp}) {wrong}"

    slug = _slugify(body.get("slug") or "")
    name = _cap(body.get("name"), 160)
    feature = None
    if slug:
        feature = Feature.query.filter_by(slug=slug).first()
    if feature is None and name:
        feature = Feature.query.filter(Feature.name.ilike(name)).first()

    if feature is not None:
        if wrong in (feature.pitfalls_md or ""):
            return jsonify({"action": "unchanged", "slug": feature.slug,
                            "reason": "that lesson is already recorded"})
        feature.pitfalls_md = ((feature.pitfalls_md or "").rstrip()
                               + ("\n\n" if feature.pitfalls_md else "")
                               + attributed)
        if gold and gold not in (feature.gold_standard_md or ""):
            feature.gold_standard_md = ((feature.gold_standard_md or "").rstrip()
                                        + ("\n\n" if feature.gold_standard_md else "")
                                        + gold)
        db.session.commit()
        return jsonify({"action": "appended", "slug": feature.slug})

    if not name:
        return jsonify({"error": "no matching entry - give a name to create "
                                 "one"}), 400
    kind = "feature" if body.get("kind") == "feature" else "rule"
    category = body.get("category")
    if category not in Feature.CATEGORY_LABELS:
        category = "platform"
    last = db.session.query(db.func.max(Feature.sort_order)).scalar() or 0
    feature = Feature(
        slug=_slugify(name), name=name, kind=kind, category=category,
        summary=_cap(body.get("summary"), 1000),
        gold_standard_md=gold, pitfalls_md=attributed,
        reference_project=project,
        reference_path=_cap(body.get("path"), 300),
        status="built", sort_order=last + 10,
    )
    db.session.add(feature)
    db.session.commit()
    return jsonify({"action": "created", "slug": feature.slug,
                    "kind": feature.kind})
