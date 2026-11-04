"""The support board across every business Michael owns.

Michael, 2026-11-04: "each app I have already has its own built in ticket
system ... so just needs to be way more user friendly as an overall customer
support board for all my businesses. but making sure those systems talk to each
other properly ... and where I can see the health of my clients satisfaction
rates at a glance. quick nav buttons over to those site own portal etc."

Tickets reach the board two ways, and they are owned differently:

- **The hub** (hub.py, the routes in app.py). A client's app pushes its tickets
  here and the board pulls as a safety net. The app owns the words; the board
  owns status after creation. Unchanged.
- **A desk.** EntertainHQ and Data Dungeon each run a support desk of their own,
  where their partners triage. The DESK owns those tickets: the board reads them
  through the desk's API door (EntertainHQ's `/support/api/`, docs/SUPPORT_API.md
  in its repo) and every reply or status pressed here goes through that door, so
  it lands exactly as a click on the desk would. The board never keeps a triage
  of its own for a desk ticket that a pull could overwrite or that could
  overwrite the desk's. Board-only marks (circle back, out of scope, billing)
  stay here and never travel.

A desk ticket is keyed by the desk's own name for it, "<company>:<id>", in
`Ticket.origin_ref`, and the hub's two drains skip anything with one. That is
the whole separation: a desk ticket can never be sent down the hub.

J&D's Talent Booker has sent its tickets to EntertainHQ's desk since the cutover
of 2026-11-01, and Michael chose (2026-11-04) to see them there, once. So the
board stops asking Talent Booker directly (`SupportApp.moved_to`), and a ticket
it already holds from Talent Booker is ADOPTED by the desk's copy rather than
shown twice: same ticket, same marks, now read from the desk.

No model is called anywhere in here, and nothing is sent that Michael did not
press: the pullers only read.
"""

import json
import logging
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from models import (
    db, Business, Client, SupportApp, Ticket, TicketNote,
    TICKET_CATEGORIES, TICKET_CLOSED_STATUSES, TICKET_PRIORITIES, TICKET_STATUSES,
)

log = logging.getLogger(__name__)

USER_AGENT = "BuiltByBean-Support/1.0"

# Defaults in code, edits in the database: a row is made from these on first
# sight and is the board's to change after that.
DEFAULTS = {
    "entertainhq": {
        "name": "EntertainHQ", "kind": "desk", "business": "entertainhq", "sort_order": 10,
        "support_url": "https://entertainhq.com/admin/support",
        "admin_url": "https://entertainhq.com/admin",
        "site_url": "https://entertainhq.com",
        "status_url": "https://status.entertainhq.com",
        "desk_url": "https://app.entertainhq.com",
        "desk_acting_for": "mbean@entertainhq.com",
    },
    "data-dungeon": {
        "name": "Data Dungeon", "kind": "desk", "business": "data dungeon", "sort_order": 20,
        "support_url": "https://datadungeon.io/admin/support",
        "admin_url": "https://datadungeon.io/admin",
        "site_url": "https://datadungeon.io",
        "desk_url": "https://datadungeon.io",
        "desk_acting_for": "mbean@entertainhq.com",
    },
    # Its tickets go to EntertainHQ's desk now.
    "talent-booker": {"moved_to": "entertainhq"},
    "kuper": {"support_path": "/admin/tickets", "admin_path": "/admin"},
    "robinson": {"support_path": "/support"},
    "robinson-co": {"support_path": "/support"},
}

WINDOW_DAYS = 30
# A reply that could not reach a desk for this long is left for Michael to see
# as "not sent", never delivered late on its own.
DESK_REPLY_FRESH = timedelta(days=2)
# Threads read per pass. The desk allows 60 calls a minute across every caller,
# Michael's own sessions included, so the board takes well under half.
DESK_FETCH_PER_PASS = 25


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive(dt):
    """Naive UTC, whatever came in. The columns carry no zone and the clock
    does, so every comparison goes through here."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


# ── The apps ────────────────────────────────────────────────────────────


def _match_business(word):
    word = (word or "").lower()
    if not word:
        return None
    for b in Business.query.order_by(Business.id).all():
        for text in (b.slug, b.short_name, b.name):
            if word in (text or "").lower():
                return b
    return None


def _hub_app_name(client):
    slug = (client.origin_slug or "").replace("-", " ").lower()
    for p in client.projects:
        name = p.name or ""
        if slug and (slug in name.lower() or name.lower().split(" ")[0] in slug):
            return name
    return client.company or client.name


def ensure_apps():
    """A row for every desk in the defaults and every wired client app.

    Idempotent and cheap: one query when nothing is new. Commits only when it
    made something.
    """
    have = {a.origin for a in SupportApp.query.all()}
    made = False
    for origin, d in DEFAULTS.items():
        if d.get("kind") != "desk" or origin in have:
            continue
        b = _match_business(d.get("business"))
        db.session.add(SupportApp(
            origin=origin, name=d["name"], kind="desk",
            business_id=b.id if b else None, sort_order=d.get("sort_order", 100),
            support_url=d.get("support_url", ""), admin_url=d.get("admin_url", ""),
            site_url=d.get("site_url", ""), status_url=d.get("status_url", ""),
            desk_url=d.get("desk_url", ""), desk_acting_for=d.get("desk_acting_for", ""),
        ))
        have.add(origin)
        made = True
    clients = Client.query.filter(Client.origin_slug.isnot(None)).all()
    for c in clients:
        if c.origin_slug in have:
            continue
        d = DEFAULTS.get(c.origin_slug, {})
        base = (c.origin_base_url or "").rstrip("/")
        db.session.add(SupportApp(
            origin=c.origin_slug, name=_hub_app_name(c), kind="hub",
            support_url=(base + d["support_path"]) if base and d.get("support_path") else "",
            admin_url=(base + d["admin_path"]) if base and d.get("admin_path") else "",
            site_url=base, moved_to=d.get("moved_to", ""),
        ))
        have.add(c.origin_slug)
        made = True
    if made:
        db.session.commit()


def apps():
    """Every app on the board, desks first, in the order the tiles show."""
    return SupportApp.query.order_by(SupportApp.sort_order, SupportApp.name).all()


def moved_origins():
    return {a.origin for a in SupportApp.query.filter(SupportApp.moved_to != "",
                                                      SupportApp.moved_to.isnot(None)).all()}


def app_for(origin):
    return SupportApp.query.filter_by(origin=origin).first() if origin else None


# ── Who speaks next ─────────────────────────────────────────────────────


def refresh_waiting(ticket):
    """Who has to speak next on a hub or hand-raised ticket.

    A desk ticket takes the desk's own answer instead (`_apply_summary`), since
    the desk sees replies the board never does.
    """
    if ticket.from_desk:
        return
    if ticket.status in TICKET_CLOSED_STATUSES:
        ticket.waiting_on, ticket.waiting_since = "", None
        return
    if ticket.id is None:
        db.session.flush()
    last = (TicketNote.query.filter_by(ticket_id=ticket.id)
            .order_by(TicketNote.created_at.desc(), TicketNote.id.desc()).first())
    if last is None:
        ticket.waiting_on = "you"
        ticket.waiting_since = naive(ticket.created_at) or utcnow()
    else:
        ticket.waiting_on = "them" if last.is_staff_reply else "you"
        ticket.waiting_since = naive(last.created_at) or utcnow()


def status_changed(ticket, old, new, when=None):
    """Stamp a status move the board has seen happen."""
    when = when or utcnow()
    if new == "resolved" and old != "resolved":
        ticket.resolved_at = when
    if old == "resolved" and new not in TICKET_CLOSED_STATUSES:
        ticket.reopen_count = (ticket.reopen_count or 0) + 1
        ticket.resolved_at = None


def staff_replied(ticket, when=None):
    if ticket.first_reply_at is None:
        ticket.first_reply_at = when or utcnow()


def waiting_count():
    """The sidebar badge: exactly the Waiting on you tab."""
    return waiting_query(Ticket.query).count()


def waiting_query(query):
    return query.filter(~Ticket.status.in_(TICKET_CLOSED_STATUSES),
                        Ticket.waiting_on == "you",
                        Ticket.out_of_scope.is_(False))


# ── Health ──────────────────────────────────────────────────────────────


def span(delta):
    """A duration as a person says it: 40m, 5h, 3d."""
    if delta is None:
        return ""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _median(deltas):
    if not deltas:
        return None
    return timedelta(seconds=statistics.median(d.total_seconds() for d in deltas))


def _tone(value, good, ok):
    """green, amber or red for a number where smaller is better."""
    if value is None:
        return ""
    return "good" if value <= good else ("ok" if value <= ok else "bad")


def health(app_list, now=None):
    """Each app's tile: what is waiting and how well it has been answered.

    Response and fix times over the last WINDOW_DAYS, from timestamps stamped
    when they happened. A figure with nothing behind it is None and the tile
    says so, rather than a zero that reads as instant.
    """
    now = naive(now) or utcnow()
    since = now - timedelta(days=WINDOW_DAYS)
    origins = [a.origin for a in app_list]
    out = {o: {"open": 0, "waiting": 0, "oldest": None, "first_reply": None,
               "fix": None, "reopen": None, "confirmed": None, "solved": None,
               "answered": 0, "fixed": 0} for o in origins}
    if not origins:
        return out
    rows = (Ticket.query.filter(Ticket.origin.in_(origins))
            .filter(db.or_(~Ticket.status.in_(TICKET_CLOSED_STATUSES),
                           Ticket.created_at >= since, Ticket.resolved_at >= since,
                           Ticket.updated_at >= since)).all())
    by = {o: [] for o in origins}
    for t in rows:
        by[t.origin].append(t)
    for origin, tickets in by.items():
        h = out[origin]
        first, fix, verify_asked, verified = [], [], 0, 0
        closed_seen, reopened, yes, no = 0, 0, 0, 0
        for t in tickets:
            created = naive(t.created_at)
            if t.status not in TICKET_CLOSED_STATUSES and not t.out_of_scope:
                h["open"] += 1
                if t.waiting_on == "you":
                    h["waiting"] += 1
                    since_wait = naive(t.waiting_since) or created
                    if since_wait and (h["oldest"] is None or now - since_wait > h["oldest"]):
                        h["oldest"] = now - since_wait
            if created and created >= since and t.first_reply_at:
                first.append(naive(t.first_reply_at) - created)
            if t.resolved_at and naive(t.resolved_at) >= since and created:
                fix.append(naive(t.resolved_at) - created)
            if (t.resolved_at and naive(t.resolved_at) >= since) or (t.reopen_count and naive(t.updated_at) and naive(t.updated_at) >= since):
                closed_seen += 1
                reopened += 1 if t.reopen_count else 0
            if t.verify_requested_at and naive(t.verify_requested_at) >= since:
                verify_asked += 1
                verified += 1 if t.verified_at else 0
            if t.said_solved is not None and naive(t.updated_at) and naive(t.updated_at) >= since:
                yes += 1 if t.said_solved else 0
                no += 0 if t.said_solved else 1
        h["first_reply"] = _median(first)
        h["fix"] = _median(fix)
        h["answered"], h["fixed"] = len(first), len(fix)
        h["reopen"] = (reopened / closed_seen) if closed_seen else None
        h["confirmed"] = (verified, verify_asked) if verify_asked else None
        h["solved"] = (yes, yes + no) if (yes + no) else None
        h["tones"] = {
            "oldest": _tone(h["oldest"], timedelta(hours=24), timedelta(hours=72)) if h["waiting"] else "good",
            "first_reply": _tone(h["first_reply"], timedelta(hours=4), timedelta(hours=24)),
            "fix": _tone(h["fix"], timedelta(days=3), timedelta(days=7)),
            "reopen": _tone(h["reopen"], 0.10, 0.25),
            "confirmed": _tone(1 - verified / verify_asked, 0.2, 0.5) if verify_asked else "",
            "solved": _tone(1 - yes / (yes + no), 0.2, 0.4) if (yes + no) else "",
        }
    return out


# ── The desk's API door ─────────────────────────────────────────────────


class DeskError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _call(app, method, path, *, query=None, body=None, timeout=20):
    """One call through a desk's door. Raises DeskError with the desk's reason.

    `acting_for` rides on every call because the door refuses one that names
    nobody: it is the desk login whose click this is.
    """
    url = (app.desk_url or "").rstrip("/") + path
    q = dict(query or {})
    data = None
    if method == "GET":
        q["acting_for"] = app.desk_acting_for or ""
    else:
        data = json.dumps(dict(body or {}, acting_for=app.desk_acting_for or "")).encode("utf-8")
    if q:
        url += "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + (app.desk_secret or ""),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        reason = ""
        try:
            text = exc.read().decode("utf-8", "replace")
            try:
                reason = (json.loads(text) or {}).get("error") or text[:200]
            except ValueError:
                reason = text[:200]
        except Exception:                                # noqa: BLE001
            pass
        raise DeskError(f"{exc.code}: {reason}".strip(), exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeskError(str(exc)) from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        # A login page with a 200 is not an empty desk.
        raise DeskError(f"not JSON: {raw[:120]}") from exc


def _split(ref):
    company, _, num = (ref or "").rpartition(":")
    return company, int(num)


def _ticket_path(ticket):
    company, num = _split(ticket.origin_ref)
    return "/support/api/tickets/%s/%d" % (urllib.parse.quote(company, safe=""), num)


def _same_words(a, b):
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _adopt(app, company, num, key):
    """The board's own copy of a ticket another app sent to this desk.

    J&D's tickets reached the board straight from Talent Booker before the
    cutover; the desk's copy is the same ticket. It is taken over rather than
    shown twice: the marks Michael put on it stay, and its thread is matched up
    by words on the next read. The old note ids are cleared because they were
    Talent Booker's numbering and the desk's would collide with them.
    """
    if not company.startswith("hub."):
        return None
    old = Ticket.query.filter_by(origin=company[4:], origin_ticket_id=num).first()
    if old is None:
        return None
    old.origin = app.origin
    old.origin_ref = key
    old.origin_ticket_id = None
    if app.business_id:
        old.business_id = app.business_id
    for n in old.notes:
        n.origin_note_id = None
    return old


def _apply_summary(app, t, row, is_new):
    old_status = t.status
    if is_new or not t.category:
        t.category = row.get("type") if row.get("type") in TICKET_CATEGORIES else "other"
    elif row.get("type") in TICKET_CATEGORIES:
        t.category = row["type"]
    status = row.get("status") if row.get("status") in TICKET_STATUSES else (t.status or "new")
    if row.get("priority") in TICKET_PRIORITIES:
        t.priority = row["priority"]
    if app.business_id:
        t.business_id = app.business_id
    t.reporter_name = (row.get("reporter") or "")[:200]
    if not t.description:
        t.description = (row.get("summary") or "")[:20000]
    t.origin_url = (row.get("desk_url") or "")[:500]
    t.created_at = parse_time(row.get("created_at")) or t.created_at
    t.updated_at = parse_time(row.get("updated_at")) or utcnow()
    t.resolved_at = parse_time(row.get("resolved_at"))
    if not is_new and old_status == "resolved" and status not in TICKET_CLOSED_STATUSES:
        t.reopen_count = (t.reopen_count or 0) + 1
    t.status = status
    t.hub_status_sent = status
    waiting = {"team": "you", "reporter": "them"}.get(row.get("waiting_on") or "", "")
    if status in TICKET_CLOSED_STATUSES:
        waiting = ""
    t.waiting_on = waiting
    t.waiting_since = (parse_time(row.get("waiting_since")) or naive(t.updated_at)) if waiting else None
    if row.get("awaiting_verification") and t.verify_requested_at is None:
        t.verify_requested_at = utcnow()


def _apply_thread(t, full):
    t.description = (full.get("description") or t.description or "")[:20000]
    t.source_label = (full.get("source_label") or "")[:200]
    t.source_path = (full.get("source_path") or "")[:500]
    t.verify_requested_at = parse_time(full.get("verification_requested_at")) or t.verify_requested_at
    t.verified_at = parse_time(full.get("verified_at"))
    if isinstance(full.get("solved"), bool):
        t.said_solved = full["solved"]
    known = {n.origin_note_id for n in t.notes if n.origin_note_id is not None}
    loose = [n for n in t.notes if n.origin_note_id is None]
    team_times = []
    for dn in full.get("notes") or []:
        try:
            nid = int(dn.get("id"))
        except (TypeError, ValueError):
            continue
        team = bool(dn.get("team"))
        at = parse_time(dn.get("at"))
        if team and at:
            team_times.append(at)
        if nid in known:
            continue
        match = next((n for n in loose if n.is_staff_reply == team and _same_words(n.body, dn.get("body"))), None)
        if match is not None:
            # A reply written here, now on the desk: the same note, not two.
            match.origin_note_id = nid
            if team and match.delivered_at is None:
                match.delivered_at = at or utcnow()
            loose.remove(match)
            known.add(nid)
            continue
        t.notes.append(TicketNote(
            origin_note_id=nid, author_name=(dn.get("by") or "")[:200],
            body=(dn.get("body") or "")[:5000], is_staff_reply=team,
            created_at=at or utcnow(),
            # Theirs, read on the desk, is read here too; ours went out by
            # the desk's own hand.
            read_at=parse_time(dn.get("read")),
            delivered_at=(at or utcnow()) if team else None,
        ))
        known.add(nid)
    if team_times:
        t.first_reply_at = min(team_times)
    t.origin_updated_at = parse_time(full.get("updated_at")) or utcnow()


def refresh_ticket(app, ticket):
    """Read one desk ticket's whole thread again, now. Raises DeskError."""
    answer = _call(app, "GET", _ticket_path(ticket))
    full = answer.get("ticket") if isinstance(answer, dict) else None
    if not isinstance(full, dict):
        raise DeskError("answered without a ticket")
    _apply_summary(app, ticket, full, is_new=False)
    _apply_thread(ticket, full)
    db.session.commit()


def pull_desk(app, fetch_limit=DESK_FETCH_PER_PASS):
    """Read a desk's whole list, then the threads that moved. Never raises.

    Returns the note written beside the app: what came back, or why nothing did.
    """
    if not app.desk_ready:
        return "not connected"
    try:
        listing = _call(app, "GET", "/support/api/tickets", query={"status": "all"})
    except DeskError as exc:
        db.session.rollback()
        app.pulled_at = utcnow()
        app.pull_note = str(exc)[:300]
        db.session.commit()
        log.warning("support: %s desk refused: %s", app.origin, exc)
        return app.pull_note
    if not isinstance(listing, dict) or not isinstance(listing.get("tickets"), list):
        app.pulled_at = utcnow()
        app.pull_note = "answered without a list of tickets"
        db.session.commit()
        return app.pull_note

    rows = list(listing.get("tickets") or []) + list(listing.get("out_of_scope") or [])
    created, stale = 0, []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            company, num = str(row["company"]), int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        key = f"{company}:{num}"[:80]
        t = Ticket.query.filter_by(origin=app.origin, origin_ref=key).first()
        is_new = False
        if t is None:
            t = _adopt(app, company, num, key)
        if t is None:
            t = Ticket(origin=app.origin, origin_ref=key, business_id=app.business_id,
                       title="", status="new")
            db.session.add(t)
            is_new = True
            created += 1
        _apply_summary(app, t, row, is_new)
        moved = parse_time(row.get("updated_at"))
        if t.origin_updated_at is None or (moved and moved > naive(t.origin_updated_at)):
            stale.append((moved or utcnow(), t))
    db.session.commit()

    stale.sort(key=lambda pair: pair[0], reverse=True)
    read = 0
    for _moved, t in stale[:fetch_limit]:
        try:
            answer = _call(app, "GET", _ticket_path(t))
        except DeskError as exc:
            db.session.rollback()
            log.warning("support: %s thread %s would not read: %s", app.origin, t.origin_ref, exc)
            if exc.status == 429:
                break
            continue
        full = answer.get("ticket") if isinstance(answer, dict) else None
        if isinstance(full, dict):
            _apply_thread(t, full)
            db.session.commit()
            read += 1

    note = f"{len(rows)} read, {created} new, {read} threads"
    if len(stale) > read:
        note += f", {len(stale) - read} next pass"
    unreadable = listing.get("unreadable") or []
    if unreadable:
        note += f"; could not read {', '.join(str(u) for u in unreadable)[:80]}"
    app.pulled_at = utcnow()
    app.pull_note = note[:300]
    db.session.commit()
    return app.pull_note


def pull_all_desks(force=False, min_gap=timedelta(minutes=8)):
    """Every connected desk. Skips one read in the last few minutes unless
    forced, so two gunicorn workers each running the schedule read once."""
    ensure_apps()
    out = []
    for app in SupportApp.query.filter_by(kind="desk").order_by(SupportApp.sort_order).all():
        if not app.desk_ready:
            continue
        if not force and app.pulled_at and utcnow() - naive(app.pulled_at) < min_gap:
            continue
        out.append((app, pull_desk(app)))
    return out


# ── Writes, only ever on Michael's press ────────────────────────────────


def desk_reply(ticket, note):
    """Send one reply written here through the desk's door.

    The note is already on the thread (recorded first, as every reply is). On
    success it is stamped delivered and the thread is read back, which matches
    the desk's copy to this one. A 409 is the desk saying those words are
    already its last reply: delivered. Returns None or the reason it did not go.
    """
    app = app_for(ticket.origin)
    if app is None or not app.desk_ready:
        return "this desk is not connected"
    try:
        _call(app, "POST", _ticket_path(ticket) + "/reply", body={"message": note.body or ""})
    except DeskError as exc:
        if exc.status != 409:
            return str(exc)
    note.delivered_at = utcnow()
    staff_replied(ticket)
    db.session.commit()
    try:
        refresh_ticket(app, ticket)
    except DeskError as exc:
        db.session.rollback()
        log.warning("support: read-back of %s failed: %s", ticket.origin_ref, exc)
    return None


DESK_NOTIFY = {"quiet": "0", "tell": "1", "verify": "verify"}


def desk_set_status(ticket, status, notify=None):
    """A status pressed here, carried out by the desk. Returns None or why not.

    The board's own status only changes by reading the desk back, so the two
    can never disagree about where a ticket is.
    """
    app = app_for(ticket.origin)
    if app is None or not app.desk_ready:
        return "this desk is not connected"
    if status not in ("in-progress", "resolved", "dismissed"):
        return "the desk takes In progress, Resolve or Close"
    body = {"status": status}
    if status == "resolved" and not ticket.desk_external:
        if notify not in DESK_NOTIFY:
            return "say whether to tell them"
        body["notify"] = DESK_NOTIFY[notify]
    try:
        _call(app, "POST", _ticket_path(ticket) + "/status", body=body)
    except DeskError as exc:
        if exc.status != 409:
            return str(exc)
    try:
        refresh_ticket(app, ticket)
    except DeskError as exc:
        db.session.rollback()
        return f"done on the desk, but reading it back failed: {exc}"
    return None


def deliver_desk_replies():
    """Retry replies that did not reach a desk on the press. Fresh ones only:
    a reply stuck for two days is Michael's to look at, not to send late."""
    cutoff = utcnow() - DESK_REPLY_FRESH
    pending = (TicketNote.query.join(Ticket, TicketNote.ticket_id == Ticket.id)
               .filter(Ticket.origin_ref.isnot(None),
                       TicketNote.is_staff_reply.is_(True),
                       TicketNote.delivered_at.is_(None),
                       TicketNote.origin_note_id.is_(None),
                       TicketNote.created_at >= cutoff)
               .order_by(TicketNote.created_at).limit(20).all())
    sent = failed = 0
    for note in pending:
        if desk_reply(note.ticket, note) is None:
            sent += 1
        else:
            failed += 1
    return sent, failed
