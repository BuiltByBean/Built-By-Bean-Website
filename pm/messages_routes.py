"""The inbox: all of Michael's Primary mail, read and answered here.

Michael, 2026-11-06 (issue #40): "similar to how I did the email receive and
send ability in the entertainhq admin portal I want that ability in my bbb pm
as well". His picks: all of Primary (inbox and sent, sixty days, no
Promotions, Social or Forums), through the app password the board already
used, its own sidebar link, his mailbox alone. It grew out of the Messages
page, which showed only clients and contact-form writers, so every link into
`messages.*` (Needs attention, a client's page) still lands.

A conversation is a thread (`thread_id`, Gmail's own conversation joined by
X-GM-THRID); the list is conversations by their latest mail. Read here is
`seen_at`; read in Gmail clears it too, on the next sync. Archive is the
board's: it takes a conversation off the list until something new arrives in
it, and leaves Gmail alone. A send is reply-all to the last mail from them,
and carries a key from the page, so a double press sends once.

His mail, so the CEO's alone.
"""
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, flash, abort, request,
                   current_app, jsonify, Response)

from models import db, Message
from pm import mail_service
from pm.users_routes import ceo_required

messages_bp = Blueprint("messages", __name__, url_prefix="/admin/messages")

PAGE = 60
VIEWS = [("all", "All"), ("unread", "Unread"), ("clients", "Clients and leads"),
         ("archived", "Archived")]
_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw)\s*:\s*)+", re.I)
# Opened in the browser; anything else downloads, so a mail cannot run a page.
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


def bare_subject(subject):
    return _PREFIX.sub("", subject or "").strip()


def _addresses(text):
    """[(name, email)] out of a To or Cc box: commas or semicolons."""
    from email.utils import getaddresses
    out, seen = [], set()
    for name, addr in getaddresses([(text or "").replace(";", ",")]):
        addr = (addr or "").strip().lower()
        if addr and "@" in addr and addr not in seen:
            seen.add(addr)
            out.append((name.strip(), addr))
    return out


def unread_count():
    """Inbound mail not yet read, in conversations still on the list: the
    sidebar's count."""
    return (Message.query.filter(Message.direction == "in", Message.seen_at.is_(None),
                                 Message.archived_at.is_(None), Message.thread_id.isnot(None))
            .count())


def conversations(view="all", q="", page=1):
    """One row per conversation, latest first, and how many there are."""
    m = Message
    unread = db.case((db.and_(m.direction == "in", m.seen_at.is_(None)), 1), else_=0)
    open_ = db.case((m.archived_at.is_(None), 1), else_=0)
    watched = db.case((m.watched.is_(True), 1), else_=0)
    grouped = (db.session.query(m.thread_id.label("tid"),
                                db.func.max(m.received_at).label("last"),
                                db.func.count(m.id).label("n"),
                                db.func.sum(unread).label("unread"),
                                db.func.sum(open_).label("open_n"),
                                db.func.sum(watched).label("w"))
               .filter(m.thread_id.isnot(None)).group_by(m.thread_id))
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        hits = db.session.query(m.thread_id).filter(db.or_(
            m.subject.ilike(like), m.from_name.ilike(like), m.from_email.ilike(like),
            m.to_email.ilike(like), m.recipients_json.ilike(like), m.body.ilike(like)))
        grouped = grouped.filter(m.thread_id.in_(hits))
    sub = grouped.subquery()
    query = db.session.query(sub)
    query = query.filter(sub.c.open_n == 0) if view == "archived" else query.filter(sub.c.open_n > 0)
    if view == "unread":
        query = query.filter(sub.c.unread > 0)
    elif view == "clients":
        query = query.filter(sub.c.w > 0)
    total = query.count()
    rows = (query.order_by(sub.c.last.desc(), sub.c.tid.desc())
            .offset(max(page - 1, 0) * PAGE).limit(PAGE).all())
    tids = [r.tid for r in rows]
    by = defaultdict(list)
    if tids:
        for msg in (Message.query.filter(Message.thread_id.in_(tids))
                    .order_by(Message.received_at, Message.id).all()):
            by[msg.thread_id].append(msg)
    out = []
    for r in rows:
        msgs = by.get(r.tid) or []
        if not msgs:
            continue
        root, last = msgs[0], msgs[-1]
        theirs = [x for x in msgs if x.direction == "in"]
        if theirs:
            who = theirs[-1].sender_label
        else:
            to = root.recipients["to"]
            who = (to[0][0] or to[0][1]) if to else (root.to_email or "")
        out.append({
            "id": r.tid,
            "subject": bare_subject(root.subject) or "(no subject)",
            "who": who,
            "snippet": " ".join(last.short_body.split())[:160],
            "last": r.last,
            "n": r.n,
            "unread": int(r.unread or 0),
            "client": next((x.client for x in msgs if x.client_id), None),
            "from_me": last.direction == "out",
            "files": any(x.attachments for x in msgs),
        })
    return out, total


def _thread(message):
    root_id = message.thread_id or message.id
    return (Message.query.filter(db.or_(Message.thread_id == root_id, Message.id == message.id))
            .order_by(Message.received_at, Message.id).all())


def _reply_plan(thread):
    """Who a reply goes to: the last mail from them, its sender in To and
    everyone else on it in Cc (less him). A conversation he started and
    nobody has answered goes back to whoever he sent it to."""
    own = mail_service.own_addresses()
    theirs = [m for m in thread if m.direction == "in"]
    if theirs:
        last = theirs[-1]
        to = [(last.from_name or "", last.from_email)]
        rest = last.recipients["to"] + last.recipients["cc"]
    else:
        last = thread[-1]
        to = [tuple(x) for x in last.recipients["to"]] or [("", last.to_email)]
        rest = last.recipients["cc"]
    taken = {e for _, e in to} | own
    cc, seen = [], set()
    for name, addr in rest:
        if addr not in taken and addr not in seen:
            seen.add(addr)
            cc.append((name, addr))
    return {"answers": last, "to": [x for x in to if x[1]], "cc": cc}


def _render(thread=None, compose=False):
    view = request.args.get("view", "all")
    if view not in dict(VIEWS):
        view = "all"
    q = (request.args.get("q") or "").strip()
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    convs, total = conversations(view, q, page)
    plan = _reply_plan(thread) if thread else None
    return render_template(
        "pm/messages/inbox.html", convs=convs, total=total, view=view, views=VIEWS, q=q,
        page=page, pages=max((total + PAGE - 1) // PAGE, 1), thread=thread,
        root=thread[0] if thread else None, plan=plan, compose=compose,
        archived=bool(thread) and all(m.archived_at for m in thread),
        send_key=uuid.uuid4().hex, mail=mail_service.status(),
        configured=mail_service.configured(),
        to=request.args.get("to", ""), subject=request.args.get("subject", ""))


@messages_bp.route("/")
@ceo_required
def index():
    mail_service.kick(current_app._get_current_object(), every=mail_service.INBOX_EVERY_SECONDS)
    return _render(compose=request.args.get("new") == "1")


@messages_bp.route("/poll")
@ceo_required
def poll():
    """What the open page asks every minute: a sync if one is due, and a
    stamp that changes when the list would."""
    mail_service.kick(current_app._get_current_object(), every=mail_service.INBOX_EVERY_SECONDS)
    newest = db.session.query(db.func.max(Message.id)).scalar() or 0
    unread = unread_count()
    return jsonify({"stamp": f"{newest}:{unread}", "unread": unread})


@messages_bp.route("/sync", methods=["POST"])
@ceo_required
def sync_now():
    result = mail_service.sync(force=True)
    if "error" in result:
        flash(f"Could not read the mailbox: {result['error']}", "warning")
    elif "skipped" in result:
        flash(f"Not checked: {result['skipped']}.", "warning")
    else:
        flash(f"{result['new']} new" if result["new"] else "Nothing new.", "success")
    return redirect(request.form.get("next") or url_for("messages.index"))


@messages_bp.route("/<int:id>")
@ceo_required
def detail(id):
    message = db.session.get(Message, id) or abort(404)
    thread = _thread(message)
    now = datetime.now(timezone.utc)
    changed = False
    for m in thread:
        if m.direction == "in" and m.seen_at is None:
            m.seen_at = now
            changed = True
    if changed:
        db.session.commit()
    return _render(thread=thread)


@messages_bp.route("/<int:id>/reply", methods=["POST"])
@ceo_required
def reply(id):
    message = db.session.get(Message, id) or abort(404)
    thread = _thread(message)
    root = thread[0]
    text = (request.form.get("body") or "").strip()
    if not text:
        flash("Write something first.", "warning")
        return redirect(url_for("messages.detail", id=root.id))
    plan = _reply_plan(thread)
    cc = plan["cc"] if request.form.get("reply_all", "1") == "1" else []
    subject = root.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {bare_subject(subject)}".strip()
    try:
        row, sent = mail_service.send_mail(plan["to"], subject, text, cc=cc,
                                           reply_to=plan["answers"],
                                           send_key=request.form.get("send_key") or None)
    except Exception as err:  # noqa: BLE001 - said on the page, not in a log
        flash(f"Could not send it: {str(err)[:200]}", "warning")
        return redirect(url_for("messages.detail", id=root.id))
    if sent:
        flash("Sent to " + ", ".join(e for _, e in plan["to"] + cc) + ".", "success")
    return redirect(url_for("messages.detail", id=row.thread_id or root.id))


@messages_bp.route("/send", methods=["POST"])
@ceo_required
def send():
    to = _addresses(request.form.get("to"))
    cc = _addresses(request.form.get("cc"))
    subject = (request.form.get("subject") or "").strip()
    text = (request.form.get("body") or "").strip()
    if not to or not subject or not text:
        flash("A new message needs who it goes to, a subject and something to say.", "warning")
        return redirect(url_for("messages.index", new=1, to=request.form.get("to", ""),
                                subject=subject))
    try:
        row, sent = mail_service.send_mail(to, subject, text, cc=cc,
                                           send_key=request.form.get("send_key") or None)
    except Exception as err:  # noqa: BLE001
        flash(f"Could not send it: {str(err)[:200]}", "warning")
        return redirect(url_for("messages.index", new=1, to=request.form.get("to", ""),
                                subject=subject))
    if sent:
        flash("Sent to " + ", ".join(e for _, e in to + cc) + ".", "success")
    return redirect(url_for("messages.detail", id=row.thread_id or row.id))


@messages_bp.route("/<int:id>/archive", methods=["POST"])
@ceo_required
def archive(id):
    message = db.session.get(Message, id) or abort(404)
    now = datetime.now(timezone.utc)
    # The row itself as well as its thread. A row with no thread_id once
    # matched nothing here while the flash still said "Archived.": a press
    # that claims to have worked has to have worked on the thing pressed.
    for m in _thread(message):
        m.archived_at = m.archived_at or now
        if m.direction == "in" and m.status == "new":
            m.status = "archived"
            m.replied_at = m.replied_at or now
    db.session.commit()
    flash("Archived.", "success")
    return redirect(request.form.get("next") or url_for("messages.index"))


@messages_bp.route("/<int:id>/unarchive", methods=["POST"])
@ceo_required
def unarchive(id):
    message = db.session.get(Message, id) or abort(404)
    for m in _thread(message):
        m.archived_at = None
    db.session.commit()
    flash("Back in the inbox.", "success")
    return redirect(url_for("messages.detail", id=message.thread_id or message.id))


@messages_bp.route("/<int:id>/file/<int:n>")
@ceo_required
def attachment(id, n):
    message = db.session.get(Message, id) or abort(404)
    if not message.gm_msgid or not any(a.get("n") == n for a in message.attachments):
        abort(404)
    try:
        got = mail_service.fetch_attachment(message.gm_msgid, n)
    except Exception as err:  # noqa: BLE001
        current_app.logger.warning("attachment fetch failed: %s", err)
        got = None
    if not got:
        abort(404)
    name, ctype, data = got
    safe = re.sub(r"[^\w.\- ]+", "_", name).strip() or "attachment"
    inline = ctype in INLINE_TYPES
    resp = Response(data, mimetype=ctype if inline else "application/octet-stream")
    resp.headers["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{safe}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return resp


def _central():
    from datetime import timedelta
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Chicago")
    except Exception:  # noqa: BLE001 - a machine with no tz database
        return timezone(timedelta(hours=-6))


@messages_bp.app_template_filter("mail_when")
def mail_when(dt, full=False):
    """A mail's time in Michael's own time zone: the time today, the day this
    year, the date before that. `full` is the day and the time, for a message."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    zone = _central()
    local = dt.astimezone(zone)
    now = datetime.now(zone)
    clock = local.strftime("%I:%M %p").lstrip("0")
    day = f"{local.strftime('%b')} {local.day}"
    if full:
        return f"{day}{'' if local.year == now.year else ', ' + str(local.year)}, {clock}"
    if local.date() == now.date():
        return clock
    return day if local.year == now.year else f"{day}, {local.year}"


# ── Email templates (issue #41) ───────────────────────────
#
# A saved email with blanks: he fills in who it goes to, sees it exactly as it
# will go, and it sends from his Gmail through send_mail, so it lands in the
# inbox's sent mail like anything else. The intro carries a catalog link made
# for that one person (catalog_service.make_link, the catalog's own way).

def _until(days):
    from datetime import timedelta
    d = datetime.now(timezone.utc) + timedelta(days=days)
    return f"{d.strftime('%B')} {d.day}"


@messages_bp.route("/templates")
@ceo_required
def templates():
    import email_templates
    return redirect(url_for("messages.template", slug=email_templates.all_templates()[0]["slug"]))


@messages_bp.route("/templates/<slug>")
@ceo_required
def template(slug):
    import catalog_service as cs
    import email_templates
    tpl = email_templates.get(slug) or abort(404)
    return render_template("pm/messages/template.html", tpl=tpl, templates=email_templates.all_templates(),
                           fields=email_templates.FIELDS, until=_until(cs.LINK_DAYS),
                           send_key=uuid.uuid4().hex, configured=mail_service.configured(),
                           original=email_templates.DEFAULTS.get(slug))


@messages_bp.route("/templates/<slug>/save", methods=["POST"])
@ceo_required
def template_save(slug):
    import email_templates
    email_templates.get(slug) or abort(404)
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not subject or not body:
        flash("A template needs a subject and a body.", "warning")
    else:
        email_templates.save(slug, subject, body)
        flash("Template saved.", "success")
    return redirect(url_for("messages.template", slug=slug))


@messages_bp.route("/templates/<slug>/reset", methods=["POST"])
@ceo_required
def template_reset(slug):
    import email_templates
    if slug not in email_templates.DEFAULTS:
        abort(404)
    email_templates.reset(slug)
    flash("Back to the original wording.", "success")
    return redirect(url_for("messages.template", slug=slug))


@messages_bp.route("/templates/<slug>/send", methods=["POST"])
@ceo_required
def template_send(slug):
    """Make this person's catalog link and send them the email as the page
    showed it (the subject and body come from the page, so a tweak for one
    person goes as seen without changing the template)."""
    import catalog_service as cs
    import email_templates
    from flask_login import current_user
    from models import CatalogLink
    tpl = email_templates.get(slug) or abort(404)
    key = request.form.get("send_key") or None
    if key:
        done = Message.query.filter_by(send_key=key).first()
        if done:
            return redirect(url_for("messages.detail", id=done.thread_id or done.id))
    name = " ".join((request.form.get("name") or "").split())
    to = (request.form.get("email") or "").strip().lower()
    company = " ".join((request.form.get("company") or "").split())
    line = (request.form.get("personal_line") or "").strip()
    if not name or not company or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
        flash("It needs their name, their email and their company.", "warning")
        return redirect(url_for("messages.template", slug=slug))
    used = {"subject": (request.form.get("subject") or tpl["subject"]),
            "body": (request.form.get("body") or tpl["body"])}
    link = None
    if "{catalog_link}" in used["body"]:
        link = cs.make_link(f"{name}, {company}"[:120], None, days=cs.LINK_DAYS, user=current_user)
        link.email = to[:200]
        client = mail_service.match_client(to)
        link.client_id = client.id if client else None
        db.session.commit()
    url = ("https://" + request.host + url_for("showcase.showcase", token=link.token)) if link else ""
    subject, text, html = email_templates.render(used, {
        "first_name": name.split()[0], "company": company, "personal_line": line,
        "catalog_link": url, "link_until": link.expires_at.strftime("%B ") + str(link.expires_at.day) if link else ""})
    try:
        row, _ = mail_service.send_mail([(name, to)], subject, text, html_body=html, send_key=key)
    except Exception as err:  # noqa: BLE001 - said on the page
        flash(f"It did not go: {str(err)[:200]}." + (" The link is made; it is on the Catalog page." if link else ""),
              "warning")
        return redirect(url_for("messages.template", slug=slug))
    if link is not None:
        link = db.session.get(CatalogLink, link.id)
        link.sent_at = cs.now()
        db.session.commit()
    flash(f"Sent to {name} at {to}.", "success")
    return redirect(url_for("messages.detail", id=row.thread_id or row.id))
