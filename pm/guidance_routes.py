"""The god door: what every other Claude asks before it builds, and how the
catalogue learns from what they find.

Every repo on this machine gets built by its own session, and every one of
them used to relearn this board's lessons the hard way. These endpoints
hand the catalogue out live - the rules that hold on every build, the
guidance behind any feature, the vendor runbooks - and take knowledge BACK.

The write side is the half that keeps the thing alive, and it is shaped by
what a wrong write could do. A rule rides into every future build prompt,
so the door does not let a session rewrite one on its own authority.
Everything a session sends becomes a CatalogueProposal: ADDITIVE changes
(a lesson appended, a new entry created) apply on arrival, because they
cannot damage what was already there and can be reverted from the inbox
in one press; anything that REPLACES existing words waits there as
pending until Michael accepts it. That policy is by shape, not by trust.

Below the catalogue sit the operational writes a session is allowed:
logging an expense or time against a project, filing a project, and
registering the infrastructure it just stood up so the hosting page can
see the cost. Nothing here talks to a client, resolves a ticket, or sends
a contract - those are Michael's, on purpose.

Bearer token on every route, compared in constant time - string equality
returns at the first differing byte, and how long that took is a
measurement. No token configured means the door is closed, not open. The
gate is a blueprint-wide before_request, so a route added later is
protected by default rather than by memory.
"""
import hmac
import json
import re
from datetime import date, datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, request

from models import (db, Feature, Playbook, PlaybookStep, Product,
                    CatalogueProposal, Client, Project, Expense, TimeEntry,
                    ServiceProvider, ServiceMapping)

guidance_bp = Blueprint("guidance", __name__, url_prefix="/api/guidance")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Everything but tab, newline and carriage return. Postgres refuses a NUL
# in a text column outright, so one stray byte in a reported lesson was a
# 500 instead of a record - found when the lesson ABOUT stray control
# bytes failed to file because it contained some.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _slugify(value):
    return _SLUG_STRIP.sub("-", (value or "").strip().lower()).strip("-")[:80]


def _cap(value, bound):
    """Public-facing write discipline: scrub control characters and truncate
    to a bound, never trusting the wire to be reasonable about either."""
    return _CONTROL.sub("", str(value or "")).strip()[:bound]


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


# ── Reading ──────────────────────────────────────────────


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


@guidance_bp.route("/products")
def products():
    rows = (Product.query.filter_by(is_active=True)
            .order_by(Product.sort_order, Product.name).all())
    return jsonify({"products": [
        {"slug": p.slug, "name": p.name, "summary": p.summary or "",
         "category": p.category, "price": p.price,
         "monthly_price": p.monthly_price, "playbook": p.playbook_slug or ""}
        for p in rows]})


@guidance_bp.route("/clients")
def clients():
    """Who the work is for, so a session can name a client and a project the
    way this board knows them rather than guessing at an id."""
    rows = Client.query.order_by(Client.name).all()
    return jsonify({"clients": [
        {"id": c.id, "name": c.name,
         "projects": [{"id": p.id, "name": p.name, "status": p.status}
                      for p in c.projects]}
        for c in rows]})


# ── The inbox: how the catalogue changes ─────────────────

# What a session may touch, per kind. Anything else is refused by name,
# because a whitelist that grows by accident is not a whitelist. `steps` on
# a playbook is the one structured field: the checklist under the runbook,
# carried as a list in the payload rather than as text.
TEXT_FIELDS = {
    "feature": ("name", "summary", "gold_standard_md", "pitfalls_md",
                "reference_project", "reference_path"),
    "rule": ("name", "summary", "gold_standard_md", "pitfalls_md",
             "reference_project", "reference_path",
             # A scanner for the rule: a session that learns a lesson can
             # also say how to catch it mechanically.
             "check_pattern", "check_globs", "check_exclude", "check_unless",
             "check_fixture"),
    "playbook": ("display_name", "one_liner", "vendor_url", "client_only_md",
                 "access_grant_md", "your_steps_md", "traps_md", "verify_md",
                 "steps"),
    "product": ("name", "summary", "prompt_intro", "playbook_slug"),
}
NUMBER_FIELDS = {
    "feature": ("typical_value",),
    "product": ("price", "monthly_price"),
}
# Only prose takes an append, and the checklist, which grows at the end. A
# name, a path or a price is replaced whole.
APPENDABLE = {"summary", "gold_standard_md", "pitfalls_md", "client_only_md",
              "access_grant_md", "your_steps_md", "traps_md", "verify_md",
              "prompt_intro", "steps"}

# Which prose field a bare lesson lands in when the entry already exists.
LESSON_FIELD = {"feature": "pitfalls_md", "rule": "pitfalls_md",
                "playbook": "traps_md", "product": "summary"}


def _fields_for(kind):
    return TEXT_FIELDS.get(kind, ()) + NUMBER_FIELDS.get(kind, ())


def _target(kind, slug):
    if kind in ("feature", "rule"):
        return Feature.query.filter_by(slug=slug).first()
    if kind == "playbook":
        return Playbook.query.filter_by(slug=slug).first()
    if kind == "product":
        return Product.query.filter_by(slug=slug).first()
    return None


def target_label(kind, slug):
    row = _target(kind, slug) if slug else None
    if row is None:
        return slug or "(new)"
    return getattr(row, "display_name", None) or getattr(row, "name", slug)


def _stamp(project, text):
    return f"({project}, {_today()}) {text}"


def _auto_applies(mode):
    """The policy. Additive on arrival; a rewrite waits for a person."""
    return mode in ("append", "create")


# ── The checklist ────────────────────────────────────────
# A playbook's steps are rows, not prose, so they travel as a list in
# payload["steps"]: {title, detail_md, client_channel (email or text),
# client_message_subject, client_message_md}. A step with a client message
# waits on the client. Append adds to the end and applies on arrival;
# replace rewrites the list and waits in the inbox; a create may carry
# them. The inbox reads the checklist as numbered lines, and revert puts
# back the exact list that was there.
STEP_FIELD = "steps"
MAX_STEPS = 40


def normalise_steps(raw):
    """The steps a session sent, checked and trimmed. Returns (list, error)."""
    if not isinstance(raw, list) or not raw:
        return None, "steps must be a non-empty list"
    if len(raw) > MAX_STEPS:
        return None, f"at most {MAX_STEPS} steps at a time"
    out = []
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            return None, f"step {i} must be an object with a title"
        title = _cap(item.get("title"), 200)
        if not title:
            return None, f"step {i} needs a title"
        channel = (item.get("client_channel") or "").strip().lower()
        if channel not in ("", "email", "text"):
            return None, f"step {i}: client_channel must be email or text"
        message = _cap(item.get("client_message_md"), 4000)
        if message and not channel:
            channel = "email"
        out.append({
            "title": title,
            "detail_md": _cap(item.get("detail_md"), 4000),
            "client_channel": channel or None,
            "client_message_subject": _cap(item.get("client_message_subject"), 200),
            "client_message_md": message,
        })
    return out, None


def steps_snapshot(playbook):
    return [{"title": s.title, "detail_md": s.detail_md or "",
             "client_channel": s.client_channel,
             "client_message_subject": s.client_message_subject or "",
             "client_message_md": s.client_message_md or ""}
            for s in playbook.steps.all()]


def steps_text(steps):
    """The checklist as the inbox reads it: one numbered line per step."""
    lines = []
    for i, s in enumerate(steps or [], 1):
        flag = "  [waits on the client]" if s.get("client_message_md") else ""
        lines.append(f"{i}. {s.get('title', '')}{flag}")
    return "\n".join(lines)


def _write_steps(playbook, steps, start):
    for offset, s in enumerate(steps):
        db.session.add(PlaybookStep(
            playbook_id=playbook.id, position=start + offset,
            title=s["title"], detail_md=s["detail_md"],
            client_channel=s["client_channel"],
            client_message_subject=s["client_message_subject"],
            client_message_md=s["client_message_md"]))


def _clear_steps(playbook):
    for s in playbook.steps.all():
        db.session.delete(s)
    db.session.flush()


def _apply_steps(proposal, playbook):
    """Append to or rewrite the checklist, snapshotting what was there."""
    payload = json.loads(proposal.payload_json or "{}")
    steps, err = normalise_steps(payload.get("steps"))
    if err:
        return False, err
    current = steps_snapshot(playbook)
    if proposal.mode == "append":
        have = {s["title"].strip().lower() for s in current}
        fresh = [s for s in steps if s["title"].strip().lower() not in have]
        if not fresh:
            return False, "already there"
        last = max([s.position for s in playbook.steps.all()] or [0])
        _write_steps(playbook, fresh, last + 1)
    else:
        _clear_steps(playbook)
        _write_steps(playbook, steps, 1)
    proposal.previous = steps_text(current)
    payload["previous_steps"] = current
    proposal.payload_json = json.dumps(payload)
    return True, ""


def _revert_steps(proposal, playbook):
    payload = json.loads(proposal.payload_json or "{}")
    previous = payload.get("previous_steps")
    if previous is None:
        return False, "nothing recorded to put back"
    _clear_steps(playbook)
    if previous:
        steps, err = normalise_steps(previous)
        if err:
            return False, err
        _write_steps(playbook, steps, 1)
    return True, ""


def _create_from(kind, payload, project):
    """Build the row a `create` proposal describes. Returns (row, error)."""
    name = _cap(payload.get("name") or payload.get("display_name"), 160)
    if not name:
        return None, "a create needs a name"
    slug = _slugify(payload.get("slug") or name)
    if not slug:
        return None, "could not make a slug from that name"
    if _target(kind, slug) is not None:
        return None, "exists"

    if kind in ("feature", "rule"):
        category = payload.get("category")
        if category not in Feature.CATEGORY_LABELS:
            category = "platform"
        last = db.session.query(db.func.max(Feature.sort_order)).scalar() or 0
        pitfalls = _cap(payload.get("what_went_wrong") or payload.get("pitfalls_md"), 4000)
        row = Feature(
            slug=slug, name=name, kind=kind, category=category,
            summary=_cap(payload.get("summary"), 1000),
            gold_standard_md=_cap(payload.get("how_to_build") or payload.get("gold_standard_md"), 4000),
            pitfalls_md=_stamp(project, pitfalls) if pitfalls else "",
            reference_project=_cap(payload.get("reference_project") or project, 120),
            reference_path=_cap(payload.get("path") or payload.get("reference_path"), 300),
            typical_value=_number(payload.get("typical_value")) if kind == "feature" else None,
            status="built", sort_order=last + 10,
        )
    elif kind == "playbook":
        category = payload.get("category")
        if category not in {c[0] for c in Playbook.CATEGORIES}:
            category = "service"
        last = db.session.query(db.func.max(Playbook.sort_order)).scalar() or 0
        row = Playbook(
            slug=slug, display_name=name, category=category,
            one_liner=_cap(payload.get("one_liner"), 300),
            vendor_url=_cap(payload.get("vendor_url"), 300),
            client_only_md=_cap(payload.get("client_only_md"), 6000),
            access_grant_md=_cap(payload.get("access_grant_md"), 6000),
            your_steps_md=_cap(payload.get("your_steps_md"), 6000),
            traps_md=_cap(payload.get("traps_md"), 6000),
            verify_md=_cap(payload.get("verify_md"), 6000),
            sort_order=last + 10,
        )
    elif kind == "product":
        category = payload.get("category")
        if category not in Product.CATEGORY_LABELS:
            category = "operations"
        last = db.session.query(db.func.max(Product.sort_order)).scalar() or 0
        row = Product(
            slug=slug, name=name, category=category,
            summary=_cap(payload.get("summary"), 2000),
            price=_number(payload.get("price")),
            monthly_price=_number(payload.get("monthly_price")),
            playbook_slug=_cap(payload.get("playbook_slug"), 60) or None,
            prompt_intro=_cap(payload.get("prompt_intro"), 4000),
            sort_order=last + 10,
        )
    else:
        return None, "unknown kind"
    db.session.add(row)
    db.session.flush()
    if kind == "playbook" and payload.get("steps"):
        steps, err = normalise_steps(payload.get("steps"))
        if err:
            return None, err
        _write_steps(row, steps, 1)
    return row, None


def apply_proposal(proposal):
    """Put the change into the catalogue. Returns (ok, message).

    Snapshots `previous` on the way, so what this did can be undone exactly,
    including when it is accepted long after it was proposed and the field
    has moved in between.
    """
    if proposal.mode == "create":
        payload = json.loads(proposal.payload_json or "{}")
        row, err = _create_from(proposal.kind, payload, proposal.project or "")
        if err:
            return False, err
        proposal.target_slug = row.slug
        proposal.previous = None
        return True, ""

    row = _target(proposal.kind, proposal.target_slug)
    if row is None:
        return False, "no such entry"
    field = proposal.field
    if field not in _fields_for(proposal.kind):
        return False, f"{field} is not a field a session may change"
    if field == STEP_FIELD:
        return _apply_steps(proposal, row)
    old = getattr(row, field)

    if proposal.mode == "append":
        old_text = old or ""
        if proposal.proposed in old_text:
            return False, "already there"
        new = ((old_text.rstrip() + "\n\n") if old_text.strip() else "") \
            + _stamp(proposal.project or "a session", proposal.proposed)
    elif field in NUMBER_FIELDS.get(proposal.kind, ()):
        new = _number(proposal.proposed)
        if new is None and proposal.proposed.strip():
            return False, f"{field} takes a number"
    else:
        new = proposal.proposed

    proposal.previous = "" if old is None else str(old)
    setattr(row, field, new)
    return True, ""


def revert_proposal(proposal):
    """Put back what apply_proposal changed. Returns (ok, message)."""
    if proposal.mode == "create":
        row = _target(proposal.kind, proposal.target_slug)
        if row is None:
            return False, "already gone"
        # Retired rather than deleted: a created rule may already be sitting
        # inside a build prompt somebody generated, and a row that vanishes
        # under a foreign key is a worse outcome than one that goes quiet.
        row.is_active = False
        return True, ""
    row = _target(proposal.kind, proposal.target_slug)
    if row is None:
        return False, "no such entry"
    field = proposal.field
    if field == STEP_FIELD:
        return _revert_steps(proposal, row)
    if field in NUMBER_FIELDS.get(proposal.kind, ()):
        setattr(row, field, _number(proposal.previous))
    else:
        setattr(row, field, proposal.previous or "")
    return True, ""


def _propose(*, kind, slug, field, mode, text, reason, project, payload=None,
             hold=False):
    """Validate, record, and either apply or park. Returns (dict, status).

    `hold` parks a change that would otherwise apply on arrival. The repo
    sweeper uses it: text mined from a CLAUDE.md was written for that
    repo, and a create would otherwise ride into every build prompt
    verbatim. Accepting it is one press on the attention page.
    """
    if kind not in CatalogueProposal.KIND_LABELS:
        return {"error": "kind must be feature, rule, playbook or product"}, 400
    if mode not in ("append", "replace", "create"):
        return {"error": "mode must be append, replace or create"}, 400
    if not project:
        return {"error": "project is required - a change with no provenance "
                         "is a change nobody can weigh"}, 400

    if mode == "create":
        payload = payload or {}
        if not (payload.get("name") or payload.get("display_name")):
            return {"error": "a create needs a name"}, 400
    else:
        if not slug:
            return {"error": "slug is required unless creating"}, 400
        if _target(kind, slug) is None:
            return {"error": f"no {kind} with slug {slug!r}"}, 404
        if field not in _fields_for(kind):
            return {"error": f"{field!r} is not a field a session may change "
                             f"on a {kind}; choose from "
                             + ", ".join(_fields_for(kind))}, 400
        if mode == "append" and field not in APPENDABLE:
            return {"error": f"{field} is replaced whole, not appended to"}, 400
        if field == STEP_FIELD:
            steps, err = normalise_steps((payload or {}).get("steps"))
            if err:
                return {"error": err}, 400
            payload = {"steps": steps}
            text = text or steps_text(steps)
        if not text:
            return {"error": "text is required"}, 400

    keeps_payload = mode == "create" or field == STEP_FIELD
    proposal = CatalogueProposal(
        kind=kind, target_slug=slug or None, field=field or "*", mode=mode,
        proposed=text or "", reason=reason, project=project,
        payload_json=json.dumps(payload) if keeps_payload else None,
    )

    if _auto_applies(mode) and not hold:
        db.session.add(proposal)
        ok, message = apply_proposal(proposal)
        if not ok:
            db.session.rollback()
            if message in ("already there", "exists"):
                return {"action": "unchanged", "slug": slug or proposal.target_slug,
                        "reason": "that is already in the catalogue"}, 200
            return {"error": message}, 400
        proposal.status = "applied"
        proposal.decided_at = datetime.now(timezone.utc)
        db.session.commit()
        return {"action": "applied", "id": proposal.id,
                "slug": proposal.target_slug,
                "note": "Applied on arrival. It can be reverted from the "
                        "catalogue inbox."}, 200

    # A rewrite. Snapshot what it would replace so the inbox can show the
    # diff, and wait.
    if mode == "create":
        proposal.previous = None  # nothing to put back; a create is retired instead
    else:
        row = _target(kind, slug)
        if field == STEP_FIELD:
            proposal.previous = steps_text(steps_snapshot(row))
        else:
            current = getattr(row, field)
            proposal.previous = "" if current is None else str(current)
    proposal.status = "pending"
    db.session.add(proposal)
    db.session.commit()
    return {"action": "pending", "id": proposal.id, "slug": slug,
            "note": "Waiting for Michael in the catalogue inbox. It will "
                    "not affect any build prompt until accepted."}, 200


@guidance_bp.route("/proposals", methods=["POST"])
def propose():
    body = request.get_json(silent=True) or {}
    kind = _cap(body.get("kind"), 10).lower()
    if kind == "features":
        kind = "feature"
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    # A create can carry its fields at the top level too, which is how the
    # bridge sends them.
    if _cap(body.get("mode"), 10) == "create" and not payload:
        payload = {k: v for k, v in body.items()
                   if k not in ("kind", "mode", "reason", "project")}
    result, status = _propose(
        kind=kind,
        slug=_slugify(body.get("slug") or ""),
        field=_cap(body.get("field"), 40),
        mode=_cap(body.get("mode"), 10).lower(),
        text=_cap(body.get("text"), 6000),
        reason=_cap(body.get("reason"), 1000),
        project=_cap(body.get("project"), 120),
        payload=payload,
    )
    return jsonify(result), status


@guidance_bp.route("/lessons", methods=["POST"])
def report_lesson():
    """A lesson learned somewhere else lands in the catalogue.

    The original door, kept for the sessions that use it: append when the
    entry exists, create a rule when it does not. Both now travel as
    proposals, so the inbox holds the whole history of what the field has
    taught this board and any of it can be put back.
    """
    body = request.get_json(silent=True) or {}
    wrong = _cap(body.get("what_went_wrong"), 4000)
    gold = _cap(body.get("how_to_build"), 4000)
    project = _cap(body.get("project"), 120)
    if not wrong or not project:
        return jsonify({"error": "what_went_wrong and project are both "
                                 "required - a lesson is what happened and "
                                 "who it happened to"}), 400

    slug = _slugify(body.get("slug") or "")
    name = _cap(body.get("name"), 160)
    feature = None
    if slug:
        feature = Feature.query.filter_by(slug=slug).first()
    if feature is None and name:
        feature = Feature.query.filter(Feature.name.ilike(name)).first()

    if feature is not None:
        result, status = _propose(kind=feature.kind, slug=feature.slug,
                                  field="pitfalls_md", mode="append", text=wrong,
                                  reason="", project=project)
        if status != 200:
            return jsonify(result), status
        if gold and gold not in (feature.gold_standard_md or ""):
            _propose(kind=feature.kind, slug=feature.slug, field="gold_standard_md",
                     mode="append", text=gold, reason="", project=project)
        action = "appended" if result.get("action") == "applied" else "unchanged"
        return jsonify({"action": action, "slug": feature.slug,
                        "reason": result.get("reason", "")})

    if not name:
        return jsonify({"error": "no matching entry - give a name to create "
                                 "one"}), 400
    kind = "feature" if body.get("kind") == "feature" else "rule"
    result, status = _propose(
        kind=kind, slug="", field="*", mode="create", text="", reason="",
        project=project,
        payload={"name": name, "category": body.get("category"),
                 "summary": body.get("summary"), "what_went_wrong": wrong,
                 "how_to_build": gold, "path": body.get("path")})
    if status != 200:
        return jsonify(result), status
    if result.get("action") == "unchanged":
        return jsonify({"action": "unchanged", "slug": result.get("slug"),
                        "reason": "that entry already exists - name it by "
                                  "slug to append to it"})
    return jsonify({"action": "created", "slug": result["slug"], "kind": kind})


# ── Operational writes: money and projects ───────────────
#
# What a session doing real work for a client is allowed to record here. A
# session that stands up a Railway service for a client should be able to
# say so, log what it cost and what it took, without a human retyping it
# that evening. It is still not allowed to talk to the client, close their
# ticket or send them paper.


def _find_client(ref):
    """A client by id or by name. Returns (client, error)."""
    ref = str(ref or "").strip()
    if not ref:
        return None, "client is required"
    if ref.isdigit():
        client = db.session.get(Client, int(ref))
        return (client, None) if client else (None, f"no client with id {ref}")
    like = f"%{ref}%"
    rows = Client.query.filter(db.or_(Client.name.ilike(like),
                                      Client.company.ilike(like))).all()
    exact = [c for c in rows if c.name.lower() == ref.lower()]
    if len(exact) == 1:
        return exact[0], None
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, f"no client matches {ref!r}"
    return None, ("more than one client matches: "
                  + ", ".join(f"{c.name} (id {c.id})" for c in rows))


def _find_project(client, ref):
    """A project belonging to `client`, by id or name. Returns (project, error)."""
    ref = str(ref or "").strip()
    if not ref:
        return None, "project is required"
    if ref.isdigit():
        project = db.session.get(Project, int(ref))
        if project is None or project.client_id != client.id:
            return None, f"no project with id {ref} for {client.name}"
        return project, None
    rows = Project.query.filter_by(client_id=client.id) \
        .filter(Project.name.ilike(f"%{ref}%")).all()
    exact = [p for p in rows if p.name.lower() == ref.lower()]
    if len(exact) == 1:
        return exact[0], None
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, (f"{client.name} has no project matching {ref!r}; "
                      "their projects are: "
                      + ", ".join(p.name for p in client.projects))
    return None, ("more than one project matches: "
                  + ", ".join(f"{p.name} (id {p.id})" for p in rows))


def _parse_date(raw):
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


@guidance_bp.route("/projects", methods=["POST"])
def upsert_project():
    body = request.get_json(silent=True) or {}
    project_ref = _cap(body.get("project"), 120)
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    name = _cap(body.get("name") or project_ref, 200)
    if not name:
        return jsonify({"error": "name is required"}), 400
    provenance = _cap(body.get("source"), 120)

    project = None
    if project_ref:
        project, _ = _find_project(client, project_ref)
    if project is None:
        project = Project.query.filter_by(client_id=client.id) \
            .filter(Project.name.ilike(name)).first()

    created = project is None
    if created:
        project = Project(client_id=client.id, name=name)
        db.session.add(project)
    description = _cap(body.get("description"), 4000)
    if description:
        project.description = description
    status = _cap(body.get("status"), 20)
    if status in ("active", "paused", "completed", "archived"):
        project.status = status
    if provenance:
        stamp = f"({provenance}, {_today()}) filed through the guidance API"
        if stamp not in (project.notes or ""):
            project.notes = ((project.notes or "").rstrip() + "\n\n" + stamp).strip()
    db.session.commit()
    return jsonify({"action": "created" if created else "updated",
                    "id": project.id, "name": project.name,
                    "client": client.name})


@guidance_bp.route("/expenses", methods=["POST"])
def log_expense():
    body = request.get_json(silent=True) or {}
    amount = _number(body.get("amount"))
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a positive number"}), 400
    description = _cap(body.get("description"), 500)
    if not description:
        return jsonify({"error": "description is required"}), 400
    when = _parse_date(body.get("date"))
    if when is None:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400

    client = project = None
    if body.get("client"):
        client, err = _find_client(body.get("client"))
        if err:
            return jsonify({"error": err}), 400
        if body.get("project"):
            project, err = _find_project(client, body.get("project"))
            if err:
                return jsonify({"error": err}), 400

    source = _cap(body.get("source"), 120)
    if source:
        description = f"{description} (logged from {source})"
    expense = Expense(
        amount=amount, description=description,
        category=_cap(body.get("category"), 50) or "misc", date=when,
        client_id=client.id if client else None,
        project_id=project.id if project else None,
    )
    db.session.add(expense)
    db.session.commit()
    return jsonify({"action": "logged", "id": expense.id, "amount": amount,
                    "date": when.isoformat()})


@guidance_bp.route("/time", methods=["POST"])
def log_time():
    body = request.get_json(silent=True) or {}
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    project, err = _find_project(client, body.get("project"))
    if err:
        return jsonify({"error": err}), 400
    hours = _number(body.get("hours"))
    if hours is None or hours <= 0 or hours > 24:
        return jsonify({"error": "hours must be between 0 and 24"}), 400
    when = _parse_date(body.get("date"))
    if when is None:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    rate_type = _cap(body.get("rate_type"), 20) or "maintenance"
    if rate_type not in ("maintenance", "new_feature", "mvp_build"):
        return jsonify({"error": "rate_type must be maintenance, new_feature "
                                 "or mvp_build"}), 400
    description = _cap(body.get("description"), 2000)
    source = _cap(body.get("source"), 120)
    if source:
        description = f"{description} (logged from {source})".strip()
    entry = TimeEntry(project_id=project.id, client_id=client.id, hours=hours,
                      description=description, rate_type=rate_type, date=when)
    db.session.add(entry)
    db.session.commit()
    return jsonify({"action": "logged", "id": entry.id, "hours": hours,
                    "project": project.name, "billable": entry.cost})


@guidance_bp.route("/hosting-resources", methods=["POST"])
def register_hosting_resource():
    """The infrastructure a session just stood up, mapped to the build it
    belongs to - which is what lets the hosting page hold that build's fee
    against what it actually costs."""
    body = request.get_json(silent=True) or {}
    provider_ref = _cap(body.get("provider"), 50).lower()
    provider = ServiceProvider.query.filter(
        db.or_(ServiceProvider.name.ilike(provider_ref),
               ServiceProvider.display_name.ilike(provider_ref))).first()
    if provider is None:
        names = ", ".join(p.name for p in ServiceProvider.query.all())
        return jsonify({"error": f"no provider {provider_ref!r}; this board "
                                 f"tracks: {names}"}), 400
    identifier = _cap(body.get("resource_identifier"), 300)
    if not identifier:
        return jsonify({"error": "resource_identifier is required - the id "
                                 "the provider knows the thing by"}), 400
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    project = None
    if body.get("project"):
        project, err = _find_project(client, body.get("project"))
        if err:
            return jsonify({"error": err}), 400

    mapping = ServiceMapping.query.filter_by(
        provider_id=provider.id, resource_identifier=identifier).first()
    created = mapping is None
    if created:
        mapping = ServiceMapping(provider_id=provider.id,
                                 resource_identifier=identifier)
        db.session.add(mapping)
    mapping.client_id = client.id
    mapping.project_id = project.id if project else mapping.project_id
    label = _cap(body.get("label"), 300)
    if label:
        mapping.resource_label = label
    monthly = _number(body.get("monthly_cost"))
    if monthly is not None:
        mapping.monthly_cost = monthly
    mapping.is_active = True
    db.session.commit()
    return jsonify({"action": "registered" if created else "updated",
                    "id": mapping.id, "provider": provider.display_name,
                    "client": client.name,
                    "project": project.name if project else None})
