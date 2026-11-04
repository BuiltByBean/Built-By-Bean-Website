"""Time that logs itself from the Claude Code sessions that did the work.

Audit item 3, 2026-11-04. Every hour on the board was typed, run on the timer,
or guessed by a session calling log_time from memory. The truth was already on
the machine: every transcript line carries a timestamp. The SessionEnd hook
(tools/hooks/session_end.py) reads them, keeps the stretches where no gap was
longer than fifteen minutes, and sends them here with the session id and the
repo the session ran in. This module decides the rest:

- **Which project.** The repo, as `owner/name`, against `Project.repo`, then a
  My Apps tile's `github_url` and the project the tile belongs to. A repo that
  names no project is not client work, and nothing is written.
- **Not his own.** The rule "Never log time against your own products": a
  project of Michael's own client row, a business of his, or a tile he keeps
  under Personal projects is never logged. Nobody can be billed for it, and
  the door has no way to take an entry back.
- **Which rate.** The project's phase: build until it goes live, maintenance
  after. The maintenance window's free period is the entry's own business
  (`TimeEntry.is_free_maintenance`).
- **Once per hour.** Michael runs several sessions side by side. Each entry
  keeps its stretches, and an entry's hours are its stretches less every
  stretch an earlier session on the same project already covers, so an hour of
  his is billed once however many sessions were open in it.
- **Correct, never add.** Keyed on the session id: the hook running again for
  the same session (a resumed one ending a second time) rewrites its entry.
  An entry already on an invoice is never touched.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from models import (db, AppLink, Business, InvoiceLineItem, Project,
                    TimeEntry, User)

GAP_MINUTES = 15
BUILD_PHASES = ("contracted", "mvp")


# ── Stretches ────────────────────────────────────────────


def _stamp(value):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def spans_from_times(stamps, gap_minutes=GAP_MINUTES):
    """Timestamps to stretches of work: a gap longer than the limit ends one.
    The hook does this on the machine; it lives here too so the test and the
    hook agree on one definition."""
    times = sorted(t for t in (_stamp(s) if not isinstance(s, datetime) else s
                               for s in stamps) if t is not None)
    spans = []
    for t in times:
        if spans and (t - spans[-1][1]) <= timedelta(minutes=gap_minutes):
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return [s for s in spans if s[1] > s[0]]


def clean_spans(raw):
    """What the hook sent, as sorted, merged (start, end) pairs. Anything
    malformed is dropped rather than trusted."""
    out = []
    for pair in raw or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        start, end = _stamp(pair[0]), _stamp(pair[1])
        if start is None or end is None or end <= start:
            continue
        if end - start > timedelta(hours=24):
            continue
        out.append((start, end))
    out.sort()
    merged = []
    for start, end in out:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _less(spans, taken):
    """`spans` with every part `taken` covers cut out."""
    out = []
    for start, end in spans:
        pieces = [(start, end)]
        for t_start, t_end in taken:
            nxt = []
            for p_start, p_end in pieces:
                if t_end <= p_start or t_start >= p_end:
                    nxt.append((p_start, p_end))
                    continue
                if t_start > p_start:
                    nxt.append((p_start, t_start))
                if t_end < p_end:
                    nxt.append((t_end, p_end))
            pieces = nxt
        out.extend(pieces)
    return out


def _hours(spans):
    return sum((end - start).total_seconds() for start, end in spans) / 3600.0


def _dump(spans):
    return json.dumps([[s.isoformat(), e.isoformat()] for s, e in spans])


def _load(entry):
    try:
        return clean_spans(json.loads(entry.spans_json or "[]"))
    except ValueError:
        return []


# ── Which project, and whose ─────────────────────────────


def repo_key(raw):
    """"owner/name", lowercased, from a slug, a GitHub URL or a git remote."""
    text = (raw or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"\.git$", "", text.rstrip("/"))
    match = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+)", text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    parts = [p for p in text.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else "")


def _flat(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def project_for_repo(repo, folder=""):
    """The project a session in this repo worked on, or None.

    Exact owner/name first, on the project and then on a tile. Failing that,
    the repo's name alone (or the folder's) when exactly one project or tile
    answers to it: a fork under another owner is still the same build, and two
    answers is a guess this must not make.
    """
    key = repo_key(repo)
    projects = Project.query.filter(Project.repo.isnot(None)).all()
    tiles = AppLink.query.filter(AppLink.github_url.isnot(None),
                                 AppLink.project_id.isnot(None)).all()
    if key and "/" in key:
        for p in projects:
            if repo_key(p.repo) == key:
                return p
        for t in tiles:
            if repo_key(t.github_url) == key:
                return t.project
    name = _flat(key.split("/")[-1] if key else folder)
    if not name:
        return None
    hits = {p.id: p for p in projects if _flat(repo_key(p.repo).split("/")[-1]) == name}
    for t in tiles:
        if _flat(repo_key(t.github_url).split("/")[-1]) == name and t.project:
            hits[t.project.id] = t.project
    return next(iter(hits.values())) if len(hits) == 1 else None


def own_reason(project):
    """Why this project is Michael's own, or None when it is client work."""
    from flask import current_app, has_app_context
    client = project.client
    if client is None:
        return "it has no client"
    if has_app_context():
        from pm.mail_service import own_addresses
        if (client.email or "").strip().lower() in own_addresses(current_app):
            return f"{client.name} is his own client row"
    who = _flat(client.name)
    for user in User.query.filter(User.role.in_(("ceo", "owner", "admin"))).all():
        if who and who == _flat(f"{user.first_name or ''}{user.last_name or ''}"):
            return f"{client.name} is his own client row"
    for biz in Business.query.all():
        if who and who in (_flat(biz.name), _flat(biz.short_name)):
            return f"{client.name} is one of his businesses"
    for tile in AppLink.query.filter_by(project_id=project.id).all():
        if tile.board_group == "mine":
            return f"{tile.name} is one of his personal projects"
    return None


def rate_for(project, when):
    """Build until it goes live, maintenance after."""
    if project.go_live_date and when >= project.go_live_date:
        return "maintenance"
    if (project.phase or "contracted") in BUILD_PHASES:
        return "mvp_build"
    return "maintenance"


def _invoiced(entry):
    return InvoiceLineItem.query.filter_by(time_entry_id=entry.id).first() is not None


# ── The write ────────────────────────────────────────────


def _recount(project):
    """Every session entry on the project, oldest first, takes only the time
    no earlier session already holds. Returns {entry id: hours}."""
    entries = (TimeEntry.query.filter(TimeEntry.project_id == project.id,
                                      TimeEntry.session_ref.isnot(None))
               .order_by(TimeEntry.id).all())
    held, out = [], {}
    for entry in entries:
        mine = _load(entry)
        own = _less(mine, held)
        hours = round(_hours(own), 2)
        if not _invoiced(entry) and hours > 0 and abs((entry.hours or 0) - hours) >= 0.01:
            entry.hours = hours
        out[entry.id] = hours
        held = clean_spans([[s.isoformat(), e.isoformat()] for s, e in held + mine])
    return out


def log_session(body):
    """(answer dict, http status). The door's /time route hands a body with
    session_ref and spans here."""
    ref = str(body.get("session_ref") or "").strip()[:80]
    if not ref:
        return {"error": "session_ref is required"}, 400
    spans = clean_spans(body.get("spans"))
    if not spans:
        return {"action": "skipped", "reason": "no work in that session"}, 200

    project = None
    if body.get("project_id"):
        project = db.session.get(Project, int(body["project_id"]))
    if project is None:
        project = project_for_repo(body.get("repo"), body.get("folder") or "")
    if project is None:
        return {"action": "skipped",
                "reason": f"no project on the board for {body.get('repo') or body.get('folder') or 'that folder'}"}, 200
    why = own_reason(project)
    if why:
        return {"action": "skipped", "project": project.name,
                "reason": f"not client work: {why}"}, 200

    when = None
    try:
        when = date.fromisoformat(str(body.get("date") or "")[:10])
    except ValueError:
        when = spans[-1][1].date()
    description = str(body.get("description") or "").strip()[:2000] \
        or "Claude Code session"

    entry = TimeEntry.query.filter_by(session_ref=ref).first()
    if entry is not None and _invoiced(entry):
        return {"action": "unchanged", "id": entry.id, "project": project.name,
                "reason": "already on an invoice"}, 200

    created = entry is None
    if created:
        entry = TimeEntry(session_ref=ref, hours=0.01)
        db.session.add(entry)
    entry.project_id = project.id
    entry.client_id = project.client_id
    entry.date = when
    entry.rate_type = rate_for(project, when)
    entry.description = f"{description} (logged from the session, {len(spans)} stretch"\
                        f"{'' if len(spans) == 1 else 'es'})"
    entry.spans_json = _dump(spans)
    db.session.flush()

    hours = _recount(project).get(entry.id, 0)
    if hours <= 0:
        # Every minute of it was already held by another session on this
        # project. Nothing to bill twice, so no row.
        db.session.delete(entry)
        db.session.commit()
        return {"action": "skipped", "project": project.name,
                "reason": "another session on this project already covers that time"}, 200
    entry.hours = hours
    db.session.commit()
    return {"action": "logged" if created else "corrected", "id": entry.id,
            "hours": hours, "project": project.name, "client": project.client.name,
            "rate_type": entry.rate_type, "billable": entry.cost}, 200
