"""What the Tend run reads and writes on the board.

Tend is the Best Practices upkeep run as a Claude Code session on Michael's
plan (.claude/skills/tend/SKILL.md), in place of the paid nightly curator
(Michael, 2026-11-04: "manually ... off of my max plan usage ... later once im
making more money we can set it up automatic every night"). It reaches the
board through the same door every session uses, and this module is the board's
half of the three things the door had no route for:

  brief          everything the run needs in one read: the notes waiting, the
                 rule list with where each is broken, playbooks, blueprints
                 with their repos and their closed gaps, and the repos the
                 sweeper watches.
  maps           a business map read as text and changed by a list of
                 operations, recorded as a CatalogueProposal of kind "map" with
                 the whole map before it, so History shows it with a Revert like
                 any other change.
  gaps           what one app should catch up on, upserted per (blueprint,
                 key); a row Michael closed is never reopened.

No model is called from here. The judgement is the session's.
"""
import json
import re
from datetime import datetime, timezone

MAP_KIND = "map"
NOTES_IN_BRIEF = 60


def _now():
    return datetime.now(timezone.utc)


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _key(title):
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:120]


def _date(value):
    return value.strftime("%Y-%m-%d") if value else "never"


# ── The brief ──────────────────────────────────────────


def brief():
    """The whole picture the run works from, as text."""
    import curate_practices as cp
    from models import (AppBlueprint, AppGap, CatalogueProposal, Feature, Playbook,
                        RepoWatch)
    out = [f"TEND BRIEF, {_now().strftime('%Y-%m-%d %H:%M')} UTC", ""]

    notes = (CatalogueProposal.query.filter_by(status="candidate")
             .order_by(CatalogueProposal.created_at, CatalogueProposal.id).all())
    out.append(f"NOTES WAITING: {len(notes):,}"
               + (f" (the oldest {NOTES_IN_BRIEF} below; the rest next run)" if len(notes) > NOTES_IN_BRIEF else ""))
    out.append("Each is a section the sweeper read in a core repo's CLAUDE.md, or a held change. "
               "Close every one you decide with close_note.")
    out.append("")
    for p in notes[:NOTES_IN_BRIEF]:
        out.append(cp.note_text(p))
        out.append("")

    rules = cp._active_rules()
    out.append(f"RULES: {len(rules):,} active, aiming for about {cp.TARGET_RULES}. "
               "slug | name | summary | size | from | added | where the audit finds it broken")
    out.append(cp.rule_index(rules, cp._broken_in()))
    out.append("")

    out.append("FEATURES (what a client can ask for by name): slug | name")
    out.append(cp._features_index())
    out.append("")

    out.append("PLAYBOOKS: slug | name | last updated")
    for p in Playbook.query.filter_by(is_active=True).order_by(Playbook.display_name).all():
        out.append(f"{p.slug} | {p.display_name} | {_date(p.updated_at)}")
    out.append("")

    out.append("BLUEPRINTS: slug | name | last updated | repos | business map | open gaps")
    blueprints = AppBlueprint.query.filter_by(is_active=True).order_by(AppBlueprint.name).all()
    for b in blueprints:
        open_n = b.gaps.filter_by(status="open").count()
        out.append(f"{b.slug} | {b.name} | {_date(b.updated_at)} | {b.source_repos or '-'} | "
                   f"{b.business.slug if b.business else '-'} | {open_n}")
        closed = b.gaps.filter(AppGap.status != "open").order_by(AppGap.id).all()
        if closed:
            out.append("  Closed, never suggest again: " + "; ".join(
                f"{g.title} ({'done' if g.status == 'done' else 'not wanted'})" for g in closed))
    out.append("")

    out.append("REPOS THE SWEEPER WATCHES: repo | last swept | last commit")
    for w in RepoWatch.query.order_by(RepoWatch.repo).all():
        out.append(f"{w.repo} | {_date(w.last_swept_at)} | {(w.last_sha or '-')[:10]}")
    return "\n".join(out)


def close_note(note_id, outcome, reason=""):
    """A note the run decided. Returns (ok, message)."""
    from models import db, CatalogueProposal
    p = db.session.get(CatalogueProposal, note_id)
    if p is None:
        return False, "no such note"
    if p.status != "candidate":
        return False, f"that note is already {p.status}"
    if outcome not in ("folded", "added", "discarded"):
        return False, "outcome must be folded, added or discarded"
    p.status = "discarded" if outcome == "discarded" else "curated"
    p.decided_at = _now()
    p.reason = ((p.reason or "") + f" Tend: {outcome}" + (f", {reason}" if reason else "")).strip()[:4000]
    db.session.commit()
    return True, ""


def record_run(counts, note=""):
    """One Tend run on the History tab's list of nights."""
    from models import db, CuratorRun, Feature
    rules = Feature.query.filter_by(is_active=True, kind="rule").count()
    run = CuratorRun(model=CuratorRun.TEND, status="ok", started_at=_now(), finished_at=_now(),
                     rules_before=int(counts.get("rules_before") or rules), rules_after=rules,
                     note=(note or "")[:20000])
    for field in ("added", "folded", "merged", "tightened", "retired", "discarded"):
        setattr(run, field, max(0, int(counts.get(field) or 0)))
    db.session.add(run)
    db.session.commit()
    return run.id


# ── Maps ──────────────────────────────────────────────


def business_by_slug(slug):
    from models import Business
    want = _norm(slug)
    for b in Business.query.order_by(Business.id).all():
        if want in (_norm(b.slug), _norm(b.short_name), _norm(b.name)):
            return b
    return None


NODE_FIELDS = ("kind", "name", "role", "status", "url", "surface_kind", "need_id",
               "playbook_id", "icon_file", "icon_source", "sort_order", "notes")


def snapshot(business):
    from models import BusinessEdge, BusinessNode
    nodes = BusinessNode.query.filter_by(business_id=business.id).order_by(BusinessNode.id).all()
    edges = BusinessEdge.query.filter_by(business_id=business.id).order_by(BusinessEdge.id).all()
    return {"nodes": [{"id": n.id, **{f: getattr(n, f) for f in NODE_FIELDS}} for n in nodes],
            "edges": [{"from": e.from_node_id, "to": e.to_node_id, "why": e.why or ""} for e in edges]}


def map_text(business):
    from models import BusinessEdge, BusinessNode
    nodes = BusinessNode.query.filter_by(business_id=business.id).order_by(BusinessNode.kind, BusinessNode.id).all()
    names = {n.id: n.display_name for n in nodes}
    out = [f"MAP OF {business.name} ({business.slug})", "",
           "NODES: id | kind | name | status | surface kind | url | playbook | role"]
    for n in nodes:
        out.append(" | ".join(str(x) for x in (
            n.id, n.kind, n.display_name, n.status or "-", n.surface_kind or "-", n.url or "-",
            n.playbook.slug if n.playbook else "-", " ".join((n.role or "").split()))))
    out += ["", "LINES: from -> to: why"]
    for e in BusinessEdge.query.filter_by(business_id=business.id).order_by(BusinessEdge.id).all():
        out.append(f"{names.get(e.from_node_id, e.from_node_id)} -> {names.get(e.to_node_id, e.to_node_id)}: {e.why or ''}")
    out += ["", "Kinds: audience, surface, service, outcome. Statuses: surface live/building/planned; "
            "service running/setting_up/planned; outcome delivered/in_progress/missing; audience none. "
            "Surface kinds: site, app, portal, phone, status, admin, inbox, other."]
    return "\n".join(out)


def _find_node(business, ref):
    from models import BusinessNode
    nodes = BusinessNode.query.filter_by(business_id=business.id).all()
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        hit = next((n for n in nodes if n.id == int(ref)), None)
        if hit:
            return hit
    want = _norm(str(ref))
    matches = [n for n in nodes if _norm(n.display_name) == want or _norm(n.name) == want]
    return matches[0] if len(matches) == 1 else None


def _playbook_id(ref):
    if not ref:
        return None
    import app_blueprints
    from models import Playbook
    slugs, _ = app_blueprints.resolve_playbooks([ref])
    p = Playbook.query.filter_by(slug=slugs[0]).first() if slugs else None
    return p.id if p else None


def _set_node(node, data):
    from models import BusinessNode
    kind = data.get("kind", node.kind)
    if kind not in dict(BusinessNode.KINDS):
        return f"kind must be one of {', '.join(dict(BusinessNode.KINDS))}"
    node.kind = kind
    for f, bound in (("name", 120), ("role", 400), ("url", 300)):
        if f in data:
            setattr(node, f, str(data[f] or "").strip()[:bound])
    if "status" in data:
        allowed = dict(BusinessNode.STATUSES.get(kind, ()))
        status = str(data["status"] or "")
        if status and status not in allowed:
            return f"status {status!r} is not one for a {kind}: {', '.join(allowed) or 'none'}"
        node.status = status
    if "surface_kind" in data:
        sk = str(data["surface_kind"] or "")
        if sk and sk not in dict(BusinessNode.SURFACE_KINDS):
            return f"surface_kind must be one of {', '.join(dict(BusinessNode.SURFACE_KINDS))}"
        node.surface_kind = sk
    if "playbook" in data:
        node.playbook_id = _playbook_id(data["playbook"])
        if data["playbook"] and node.playbook_id is None:
            return f"no playbook called {data['playbook']!r}"
    if not node.name and node.playbook_id is None:
        return "a node needs a name"
    return None


def apply_map_changes(business, changes):
    """Apply a list of operations to one map. Returns (summary lines, error).
    All or nothing: the caller rolls back on an error."""
    from models import db, BusinessEdge, BusinessNode
    if not isinstance(changes, list) or not changes:
        return None, "changes must be a non-empty list"
    if len(changes) > 80:
        return None, "at most 80 changes at a time"
    done = []
    for i, ch in enumerate(changes, 1):
        if not isinstance(ch, dict):
            return None, f"change {i} must be an object"
        op = ch.get("op")
        if op == "add_node":
            node = BusinessNode(business_id=business.id, kind=ch.get("kind") or "service", name="")
            err = _set_node(node, {k: v for k, v in ch.items() if k != "op"})
            if err:
                return None, f"change {i}: {err}"
            db.session.add(node)
            db.session.flush()
            done.append(f"added {node.kind} {node.display_name}")
        elif op in ("update_node", "remove_node"):
            node = _find_node(business, ch.get("node"))
            if node is None:
                return None, f"change {i}: no single node called {ch.get('node')!r}"
            if op == "remove_node":
                BusinessEdge.query.filter((BusinessEdge.from_node_id == node.id)
                                          | (BusinessEdge.to_node_id == node.id)).delete(synchronize_session=False)
                done.append(f"removed {node.kind} {node.display_name}")
                db.session.delete(node)
                db.session.flush()
            else:
                err = _set_node(node, {k: v for k, v in ch.items() if k not in ("op", "node")})
                if err:
                    return None, f"change {i}: {err}"
                done.append(f"updated {node.display_name}")
        elif op in ("add_edge", "remove_edge"):
            a, b = _find_node(business, ch.get("from")), _find_node(business, ch.get("to"))
            if a is None or b is None:
                return None, f"change {i}: no single node called {ch.get('from') if a is None else ch.get('to')!r}"
            edge = BusinessEdge.query.filter_by(business_id=business.id, from_node_id=a.id, to_node_id=b.id).first()
            if op == "add_edge":
                if edge is None:
                    edge = BusinessEdge(business_id=business.id, from_node_id=a.id, to_node_id=b.id)
                    db.session.add(edge)
                edge.why = str(ch.get("why") or "").strip()[:300]
                done.append(f"line {a.display_name} -> {b.display_name}")
            elif edge is not None:
                db.session.delete(edge)
                done.append(f"removed line {a.display_name} -> {b.display_name}")
        else:
            return None, f"change {i}: op must be add_node, update_node, remove_node, add_edge or remove_edge"
        db.session.flush()
    return done, None


def change_map(slug, changes, project, reason=""):
    """Validate, apply and record. Returns (dict, status)."""
    from models import db, CatalogueProposal
    business = business_by_slug(slug)
    if business is None:
        return {"error": f"no business called {slug!r}"}, 404
    if not project:
        return {"error": "project is required"}, 400
    before = snapshot(business)
    done, err = apply_map_changes(business, changes)
    if err:
        db.session.rollback()
        return {"error": err}, 400
    proposal = CatalogueProposal(
        kind=MAP_KIND, target_slug=business.slug, field="map", mode="replace",
        proposed="\n".join(done), reason=str(reason or "")[:1000], project=str(project)[:120],
        previous=f"{len(before['nodes'])} things and {len(before['edges'])} lines",
        payload_json=json.dumps({"previous_map": before, "changes": changes}, default=str),
        status="applied", decided_at=_now())
    db.session.add(proposal)
    db.session.commit()
    return {"action": "applied", "id": proposal.id, "changed": done,
            "note": "Applied. History has it with a Revert."}, 200


def revert_map(proposal):
    """Put a map back exactly as it was before the change. (ok, message)"""
    from models import db, BusinessEdge, BusinessNode
    business = business_by_slug(proposal.target_slug)
    if business is None:
        return False, "that business is gone"
    previous = (json.loads(proposal.payload_json or "{}") or {}).get("previous_map")
    if previous is None:
        return False, "nothing recorded to put back"
    BusinessEdge.query.filter_by(business_id=business.id).delete(synchronize_session=False)
    BusinessNode.query.filter_by(business_id=business.id).delete(synchronize_session=False)
    db.session.flush()
    ids = {}
    for n in previous["nodes"]:
        node = BusinessNode(business_id=business.id, **{f: n.get(f) for f in NODE_FIELDS})
        db.session.add(node)
        db.session.flush()
        ids[n["id"]] = node.id
    for e in previous["edges"]:
        if e["from"] in ids and e["to"] in ids:
            db.session.add(BusinessEdge(business_id=business.id, from_node_id=ids[e["from"]],
                                        to_node_id=ids[e["to"]], why=e.get("why") or ""))
    return True, ""


def map_label(slug):
    business = business_by_slug(slug or "")
    return f"{business.short_name or business.name} map" if business else f"{slug} map"


# ── Gaps ──────────────────────────────────────────────


def blueprint_by_ref(ref):
    from models import AppBlueprint
    want = _norm(ref)
    for b in AppBlueprint.query.order_by(AppBlueprint.id).all():
        if want in (_norm(b.slug), _norm(b.name)):
            return b
    return None


def file_gaps(blueprint_ref, gaps, project):
    """Upsert one app's gaps. Returns (dict, status). A row Michael closed is
    left closed: the run says what it found, he says what he wants."""
    from models import db, AppGap
    b = blueprint_by_ref(blueprint_ref or "")
    if b is None:
        return {"error": f"no blueprint called {blueprint_ref!r}"}, 404
    if not isinstance(gaps, list) or not gaps:
        return {"error": "gaps must be a non-empty list"}, 400
    added = updated = kept_closed = 0
    for i, g in enumerate(gaps[:40], 1):
        if not isinstance(g, dict) or not str(g.get("title") or "").strip():
            return {"error": f"gap {i} needs a title"}, 400
        title = str(g["title"]).strip()[:200]
        key = _key(g.get("key") or title)
        kind = g.get("kind") if g.get("kind") in dict(AppGap.KINDS) else "gap"
        source = blueprint_by_ref(g.get("from") or "") if g.get("from") else None
        row = AppGap.query.filter_by(blueprint_id=b.id, key=key).first()
        if row is not None and row.status != "open":
            kept_closed += 1
            continue
        if row is None:
            row = AppGap(blueprint_id=b.id, key=key)
            db.session.add(row)
            added += 1
        else:
            updated += 1
        row.title = title
        row.detail_md = str(g.get("detail_md") or "").strip()[:8000]
        row.kind = kind
        row.source_blueprint_id = source.id if source and source.id != b.id else None
        row.filed_by = str(project or "")[:120]
    db.session.commit()
    return {"action": "applied", "blueprint": b.slug, "added": added, "updated": updated,
            "left_closed": kept_closed}, 200
