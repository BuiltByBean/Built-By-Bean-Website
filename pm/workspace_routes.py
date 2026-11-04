"""The Workspace: Messages, Tasks and Projects, one page with three tabs.

Michael, 2026-11-04: "I have a notes section. I want to replace that and
integrate the workspace feature from Entertain HQ into that, where we have the
messages, task, and projects. And so then the projects page that we have
standalone right now will get folded into that workspace thing ... I want that
to be the second tab under needs attention."

His picks the same day, one question each:

- **Messages** is team chat between people with a board login (him, Hannah,
  anyone added), direct or group, and a message can link to anything on the
  board. No email and no text. Client mail stays on Needs attention.
- **Tasks** replace Notes. Every note was carried across (migration
  a5d17c3e92b4). EntertainHQ's three columns with drag and drop, and a task can
  be for one person or several.
- **Projects** are the client projects this board already had, not a new kind:
  the list is cards, and a project's page keeps everything it had and adds its
  own task board and the messages about it. Its tickets, time and money are
  tiles that open those pages filtered to it.
- **Everyone sees everything**: with two people on the board, no member lists.
  The Tasks board opens on yours, and one press shows everybody's.

Each tab is its own address, so a link to any of them is a link. The tab row is
`data-keep` (base.html), so moving between tabs swaps the content under it and
never the row itself, and its mark slides (catalogue rule "In-page switches
glide, and only the part that changed is redrawn").

The counts are what is NEW, never the standing backlog (EntertainHQ,
2026-10-09: "I've got three tasks in my backlog, and that's persistently
showing a three"): unread messages, and tasks given to you that you have not
been shown. The board's render of a task is what marks it seen.
"""
import re
from datetime import date, datetime, timedelta, timezone

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request,
    session, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from models import (
    db, User, Client, Project, Product, Playbook, Ticket, Lead, Business,
    SignatureRequest, WorkTask, WorkTaskPerson, TeamConversation,
    TeamConversationMember, TeamMessage, TeamMessageLink, TASK_STAGES,
    TASK_STAGE_KEYS,
)

workspace_bp = Blueprint("workspace", __name__, url_prefix="/admin/workspace")

TABS = ("messages", "tasks", "projects")
# Done holds the latest of these; the rest are a press away. A board that
# grows a row a day is unreadable by spring otherwise.
DONE_SHOWN = 40
# How long a message can be. Generous: this is a chat, not a document.
BODY_MAX = 8000


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local_zone():
    """Texas time, where the business is. A slim image without the tz
    database still gets the right hour for most of the year rather than a
    page that will not render."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Chicago")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-6))


@workspace_bp.app_template_filter("ws_when")
def ws_when(dt):
    """A message's time the way a chat says it: the time today, the day this
    week, the date before that."""
    if not dt:
        return ""
    zone = _local_zone()
    local = _aware(dt).astimezone(zone)
    today = datetime.now(zone).date()
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == today:
        return clock
    if (today - local.date()).days < 7:
        return f"{local:%a} {clock}"
    return f"{local:%b} {local.day}, {clock}"


@workspace_bp.app_template_filter("initials")
def initials(user):
    if not user:
        return "?"
    first = (user.first_name or user.username or "?")[:1]
    last = (user.last_name or "")[:1]
    return (first + last).upper()


# ---------------------------------------------------------------- people

def people():
    """Everyone who can be written to or given a task: every active login.
    Switched-off accounts keep their history but take nothing new."""
    return (User.query.filter(User.is_active.is_(True))
            .order_by(User.first_name, User.username, User.id).all())


def _picked_people(field="people"):
    """The ids ticked on a form, checked against the active logins. A stale
    id is dropped rather than written as a row pointing at nobody."""
    wanted = {int(v) for v in request.form.getlist(field) if str(v).isdigit()}
    return [u.id for u in people() if u.id in wanted]


# ---------------------------------------------------------------- counts

def _unread_query(user_id):
    """Messages somebody else wrote in a conversation this person is in,
    after they last read it."""
    return (db.session.query(TeamMessage.id)
            .join(TeamConversationMember,
                  TeamConversationMember.conversation_id == TeamMessage.conversation_id)
            .filter(TeamConversationMember.user_id == user_id,
                    TeamMessage.author_id != user_id,
                    TeamMessage.deleted_at.is_(None),
                    db.or_(TeamConversationMember.last_read_at.is_(None),
                           TeamMessage.created_at > TeamConversationMember.last_read_at)))


def _new_tasks_query(user_id):
    """Open tasks given to this person that the board has not shown them."""
    return (WorkTaskPerson.query.join(WorkTask)
            .filter(WorkTaskPerson.user_id == user_id,
                    WorkTaskPerson.seen_at.is_(None),
                    WorkTask.stage != "done"))


def counts(user_id):
    """The three tab counts and their sum, which is the sidebar's badge.
    Projects carry no count: nothing about a project is news by itself."""
    messages = _unread_query(user_id).count()
    tasks = _new_tasks_query(user_id).count()
    return {"messages": messages, "tasks": tasks, "projects": 0,
            "total": messages + tasks}


def _ctx(tab):
    session["ws_tab"] = tab
    return {"ws_tab": tab, "ws_counts": counts(current_user.id), "ws_people": people()}


@workspace_bp.route("/")
@login_required
def index():
    """The tab you were last on, Messages the first time."""
    tab = session.get("ws_tab")
    return redirect(url_for(f"workspace.{tab if tab in TABS else 'messages'}"))


# ---------------------------------------------------------------- links

def _business_ok():
    return bool(getattr(current_user, "is_ceo", False))


LINK_KINDS = ("project", "client", "task", "ticket", "contract", "lead", "business")
LINK_LABELS = {"project": "Project", "client": "Client", "task": "Task",
               "ticket": "Ticket", "contract": "Contract", "lead": "Lead",
               "business": "Business"}


def resolve_link(kind, record_id):
    """(label, url) for a link, read live. None when the record has gone, or
    when this login may not open it (a business is CEO only)."""
    if kind == "project":
        r = db.session.get(Project, record_id)
        return (r.name, url_for("pm.project_detail", id=r.id)) if r else None
    if kind == "client":
        r = db.session.get(Client, record_id)
        return (r.name, url_for("pm.client_detail", id=r.id)) if r else None
    if kind == "task":
        r = db.session.get(WorkTask, record_id)
        return (r.title, url_for("workspace.tasks", who="all", open=r.id)) if r else None
    if kind == "ticket":
        r = db.session.get(Ticket, record_id)
        return ((r.title or f"Ticket {r.id}"), url_for("pm.ticket_detail", id=r.id)) if r else None
    if kind == "contract":
        r = db.session.get(SignatureRequest, record_id)
        return (r.title, url_for("contracts.contract_detail", id=r.id)) if r else None
    if kind == "lead":
        r = db.session.get(Lead, record_id)
        return (r.name, url_for("leads.index", q=r.name)) if r else None
    if kind == "business" and _business_ok():
        r = db.session.get(Business, record_id)
        return (r.name, url_for("businesses.detail", id=r.id)) if r else None
    return None


def _parse_links():
    """`kind:id` pairs off the form, each checked against its table."""
    out, seen = [], set()
    for raw in request.form.getlist("link"):
        m = re.fullmatch(r"(\w+):(\d+)", str(raw).strip())
        if not m or m.group(1) not in LINK_KINDS:
            continue
        key = (m.group(1), int(m.group(2)))
        if key in seen or not resolve_link(*key):
            continue
        seen.add(key)
        out.append(key)
    return out[:8]


@workspace_bp.route("/links")
@login_required
def link_search():
    """The Link picker's search: anything on the board by name, as JSON."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    rows = []

    def add(kind, record_id, label, sub=""):
        rows.append({"kind": kind, "id": record_id, "label": label,
                     "sub": sub, "type": LINK_LABELS[kind]})

    for p in Project.query.filter(Project.name.ilike(like)).order_by(Project.name).limit(6):
        add("project", p.id, p.name, p.client.name if p.client else "")
    for c in Client.query.filter(Client.name.ilike(like)).order_by(Client.name).limit(6):
        add("client", c.id, c.name, c.email or "")
    for t in WorkTask.query.filter(WorkTask.title.ilike(like)).order_by(WorkTask.id.desc()).limit(6):
        add("task", t.id, t.title, dict(TASK_STAGES).get(t.stage, ""))
    for t in Ticket.query.filter(Ticket.title.ilike(like)).order_by(Ticket.id.desc()).limit(6):
        add("ticket", t.id, t.title or f"Ticket {t.id}", t.client.name if t.client else "")
    for s in (SignatureRequest.query.filter(SignatureRequest.title.ilike(like))
              .order_by(SignatureRequest.id.desc()).limit(6)):
        add("contract", s.id, s.title, s.signer_name or "")
    for lead in Lead.query.filter(Lead.name.ilike(like)).order_by(Lead.name).limit(6):
        add("lead", lead.id, lead.name, lead.city or "")
    if _business_ok():
        for b in Business.query.filter(Business.name.ilike(like)).order_by(Business.name).limit(4):
            add("business", b.id, b.name)
    return jsonify(rows)


# ---------------------------------------------------------------- messages

def _membership(conversation_id, user_id):
    return TeamConversationMember.query.filter_by(
        conversation_id=conversation_id, user_id=user_id).first()


def _conversation_or_404(conversation_id):
    """A conversation opens only to the people in it: the page, the send, the
    poll and the delete. A 404 rather than a 403, so the door does not say
    that a conversation with that number exists."""
    conv = db.session.get(TeamConversation, conversation_id)
    if not conv or not _membership(conv.id, current_user.id):
        abort(404)
    return conv


def conversation_with(member_ids):
    """The conversation these exact people already share, or None. A pair is
    found by its key; a group by its member set."""
    ids = sorted(set(member_ids))
    if len(ids) == 2:
        return TeamConversation.query.filter_by(pair_key=f"{ids[0]}:{ids[1]}").first()
    mine = (TeamConversation.query.join(TeamConversationMember)
            .filter(TeamConversationMember.user_id == ids[0],
                    TeamConversation.pair_key.is_(None)).all())
    for conv in mine:
        if conv.member_ids == ids:
            return conv
    return None


def _start_conversation(member_ids, title=None):
    ids = sorted(set(member_ids))
    conv = TeamConversation(created_by_id=current_user.id, title=(title or None),
                            pair_key=f"{ids[0]}:{ids[1]}" if len(ids) == 2 else None)
    db.session.add(conv)
    db.session.flush()
    for uid in ids:
        db.session.add(TeamConversationMember(conversation_id=conv.id, user_id=uid))
    return conv


def _conversation_rows(user_id):
    """This person's conversations, latest first, each with its unread count."""
    convs = (TeamConversation.query.join(TeamConversationMember)
             .filter(TeamConversationMember.user_id == user_id)
             .order_by(func.coalesce(TeamConversation.last_message_at,
                                     TeamConversation.created_at).desc(),
                       TeamConversation.id.desc())
             .all())
    unread = dict(
        _unread_query(user_id)
        .with_entities(TeamMessage.conversation_id, func.count(TeamMessage.id))
        .group_by(TeamMessage.conversation_id).all())
    return [{"conv": c, "name": c.name_for(user_id), "others": c.others(user_id),
             "unread": unread.get(c.id, 0)} for c in convs]


def _message_view(m):
    links = []
    for link in m.links:
        got = resolve_link(link.kind, link.record_id)
        links.append({"type": LINK_LABELS.get(link.kind, link.kind),
                      "label": got[0] if got else "No longer on the board",
                      "url": got[1] if got else None})
    return {"m": m, "links": links, "mine": m.author_id == current_user.id}


def _thread(conv, after=0):
    q = conv.messages.filter(TeamMessage.id > after)
    return [_message_view(m) for m in q.all()]


def _mark_read(conv):
    member = _membership(conv.id, current_user.id)
    if member:
        member.last_read_at = _now()
        db.session.commit()


def _about_links():
    """`?about=project:5` from a record's own page: the first message starts
    out linked to it."""
    out = []
    for raw in request.args.getlist("about"):
        m = re.fullmatch(r"(\w+):(\d+)", raw or "")
        if m and m.group(1) in LINK_KINDS:
            got = resolve_link(m.group(1), int(m.group(2)))
            if got:
                out.append({"kind": m.group(1), "id": int(m.group(2)),
                            "type": LINK_LABELS[m.group(1)], "label": got[0]})
    return out


@workspace_bp.route("/messages")
@workspace_bp.route("/messages/<int:id>")
@login_required
def messages(id=None):
    """The conversation list beside one conversation. With no id, the last
    one opened (EntertainHQ: "have it open the last chat you had open instead
    of just showing the big empty box"), unless ?all=1 asks for the list."""
    conv = None
    if id is None and not request.args.get("all"):
        last = session.get("ws_conv")
        if last and _membership(last, current_user.id):
            return redirect(url_for("workspace.messages", id=last))
    if id is not None:
        conv = _conversation_or_404(id)
        session["ws_conv"] = conv.id
        _mark_read(conv)
    rows = _conversation_rows(current_user.id)
    return render_template(
        "pm/workspace/messages.html", rows=rows, conv=conv,
        thread=_thread(conv) if conv else [], about=_about_links(),
        **_ctx("messages"))


@workspace_bp.route("/messages/new")
@login_required
def message_new():
    """Who the message is to. Picking the people of a conversation that
    already exists opens that one, so the chat on screen is always the real
    one; otherwise the pane is a fresh chat locked to them, and the first
    send makes it."""
    others = [u for u in people() if u.id != current_user.id]
    to = sorted({int(v) for v in request.args.getlist("to") if str(v).isdigit()}
                & {u.id for u in others})
    if to:
        existing = conversation_with(to + [current_user.id])
        if existing:
            return redirect(url_for("workspace.messages", id=existing.id,
                                    about=request.args.getlist("about")))
    return render_template(
        "pm/workspace/messages.html", rows=_conversation_rows(current_user.id),
        conv=None, thread=[], composing=True, to=to, others=others,
        to_users=[u for u in others if u.id in to], about=_about_links(),
        **_ctx("messages"))


def _post(conv, body, links):
    msg = TeamMessage(conversation_id=conv.id, author_id=current_user.id, body=body,
                      created_at=_now())
    db.session.add(msg)
    db.session.flush()
    for kind, record_id in links:
        db.session.add(TeamMessageLink(message_id=msg.id, kind=kind, record_id=record_id))
    conv.last_message_at = msg.created_at
    member = _membership(conv.id, current_user.id)
    if member:
        member.last_read_at = msg.created_at
    return msg


@workspace_bp.route("/messages/send", methods=["POST"])
@login_required
def message_send():
    body = (request.form.get("body") or "").strip()[:BODY_MAX]
    links = _parse_links()
    if not body and not links:
        return ("", 204) if request.headers.get("X-Requested-With") == "fetch" else \
            redirect(request.referrer or url_for("workspace.messages"))

    conv_id = request.form.get("conversation_id", type=int)
    if conv_id:
        conv = _conversation_or_404(conv_id)
    else:
        to = _picked_people("to")
        to = [uid for uid in to if uid != current_user.id]
        if not to:
            flash("Pick who it is to.", "warning")
            return redirect(url_for("workspace.message_new"))
        members = to + [current_user.id]
        conv = conversation_with(members) or _start_conversation(
            members, (request.form.get("title") or "").strip()[:120] if len(to) > 1 else None)

    _post(conv, body, links)
    db.session.commit()

    # The thread asks for the rows since the last one it has, and appends
    # them; nothing else on the page moves. A first message navigates to
    # the conversation it made, which is the one send that does.
    if request.headers.get("X-Requested-With") == "fetch" and conv_id:
        after = request.form.get("after", type=int) or 0
        return render_template("pm/workspace/_message_rows.html", thread=_thread(conv, after))
    return redirect(url_for("workspace.messages", id=conv.id))


@workspace_bp.route("/messages/<int:id>/rows")
@login_required
def message_rows(id):
    """The poll: rows after `after`, and nothing (204) when there are none,
    so an idle chat costs one tiny answer every few seconds."""
    conv = _conversation_or_404(id)
    after = request.args.get("after", type=int) or 0
    thread = _thread(conv, after)
    if not thread:
        return "", 204
    _mark_read(conv)
    return render_template("pm/workspace/_message_rows.html", thread=thread)


@workspace_bp.route("/messages/list")
@login_required
def message_list():
    """The conversation list on its own, for its poll. The page compares it
    with what it shows and swaps only when they differ."""
    return render_template("pm/workspace/_conversations.html",
                           rows=_conversation_rows(current_user.id),
                           conv_id=request.args.get("open", type=int),
                           ws_counts=counts(current_user.id))


@workspace_bp.route("/messages/<int:id>/delete/<int:mid>", methods=["POST"])
@login_required
def message_delete(id, mid):
    """Your own message, marked deleted for everyone. Nobody else's."""
    conv = _conversation_or_404(id)
    msg = db.session.get(TeamMessage, mid)
    if not msg or msg.conversation_id != conv.id or msg.author_id != current_user.id:
        abort(404)
    msg.deleted_at = _now()
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return render_template("pm/workspace/_message_rows.html", thread=[_message_view(msg)])
    return redirect(url_for("workspace.messages", id=conv.id))


@workspace_bp.route("/messages/<int:id>/people", methods=["POST"])
@login_required
def conversation_people(id):
    """A group's people and name, edited from the group. A pair stays a
    pair: adding somebody to one starts a group, because the two of you
    still have your own chat."""
    conv = _conversation_or_404(id)
    picked = set(_picked_people("people")) | {current_user.id}
    if conv.pair_key:
        if picked == set(conv.member_ids):
            return redirect(url_for("workspace.messages", id=conv.id))
        target = conversation_with(sorted(picked)) or _start_conversation(sorted(picked))
        db.session.commit()
        return redirect(url_for("workspace.messages", id=target.id))
    if len(picked) < 2:
        flash("A group needs somebody else in it.", "warning")
        return redirect(url_for("workspace.messages", id=conv.id))
    have = {m.user_id: m for m in conv.members}
    for uid in picked - set(have):
        db.session.add(TeamConversationMember(conversation_id=conv.id, user_id=uid))
    for uid in set(have) - picked:
        db.session.delete(have[uid])
    conv.title = (request.form.get("title") or "").strip()[:120] or None
    db.session.commit()
    if current_user.id not in picked:
        return redirect(url_for("workspace.messages", all=1))
    return redirect(url_for("workspace.messages", id=conv.id))


def messages_about(kind, record_id, user_id, limit=20):
    """The messages linked to a record, in conversations this person is in.
    A record's page lists only what its reader could open anyway."""
    rows = (TeamMessage.query.join(TeamMessageLink)
            .join(TeamConversationMember,
                  TeamConversationMember.conversation_id == TeamMessage.conversation_id)
            .filter(TeamMessageLink.kind == kind, TeamMessageLink.record_id == record_id,
                    TeamConversationMember.user_id == user_id,
                    TeamMessage.deleted_at.is_(None))
            .order_by(TeamMessage.id.desc()).limit(limit).all())
    return [{"m": m, "conv": m.conversation, "name": m.conversation.name_for(user_id)}
            for m in rows]


# ---------------------------------------------------------------- tasks

def _date(field):
    """A date off the form, or None. A typo is no date, never today."""
    raw = (request.form.get(field) or "").strip()
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _link_id(field, model):
    raw = request.form.get(field, type=int)
    return raw if raw and db.session.get(model, raw) else None


def task_options():
    """The pickers on the task window, each with a blank row so a link can be
    taken off (the placeholder alone is not selectable, LM-2)."""
    return {
        "opt_clients": [("", "No client")] + [
            (c.id, c.name) for c in Client.query.order_by(Client.name).all()],
        "opt_projects": [("", "No project")] + [
            (p.id, f"{p.name} ({p.client.name})" if p.client else p.name)
            for p in Project.query.filter(Project.status != "archived")
            .order_by(Project.name).all()],
        "opt_products": [("", "No product")] + [
            (p.id, p.name) for p in
            Product.query.filter_by(is_active=True).order_by(Product.name).all()],
        "opt_playbooks": [("", "No playbook")] + [
            (p.id, p.display_name) for p in Playbook.query.order_by(Playbook.display_name).all()],
        "opt_stages": list(TASK_STAGES),
    }


def _set_people(task, ids):
    """Who a task is for, written in one place. Somebody newly put on it is
    told by the count, unless they put themselves there."""
    have = {p.user_id: p for p in task.people}
    for uid in ids:
        if uid not in have:
            task.people.append(WorkTaskPerson(
                user_id=uid, seen_at=_now() if uid == current_user.id else None))
    for uid, row in have.items():
        if uid not in ids:
            task.people.remove(row)


def _set_stage(task, stage):
    if stage not in TASK_STAGE_KEYS or stage == task.stage:
        return
    task.stage = stage
    task.done_at = _now() if stage == "done" else None


def _top_of(stage):
    low = db.session.query(func.min(WorkTask.position)).filter(WorkTask.stage == stage).scalar()
    return (low or 0) - 1


def board(who="mine", project=None, open_id=None):
    """The three columns. Mine is tasks for this person or set by them; a
    project's board is every task on the project, whoever it is for."""
    q = WorkTask.query
    if project is not None:
        q = q.filter(WorkTask.project_id == project.id)
    elif who == "mine":
        q = q.filter(db.or_(
            WorkTask.id.in_(db.session.query(WorkTaskPerson.task_id)
                            .filter(WorkTaskPerson.user_id == current_user.id)),
            db.and_(WorkTask.created_by_id == current_user.id,
                    ~WorkTask.people.any())))
    columns = {}
    for key, _label in TASK_STAGES:
        cq = q.filter(WorkTask.stage == key)
        if key == "done":
            total = cq.count()
            dq = cq.order_by(WorkTask.done_at.desc().nullslast(), WorkTask.id.desc())
            rows = dq.all() if request.args.get("done") == "all" else dq.limit(DONE_SHOWN).all()
        else:
            rows = cq.order_by(WorkTask.position, WorkTask.id.desc()).all()
            total = len(rows)
        columns[key] = {"rows": rows, "total": total}

    # The render that shows a task to its person is what makes it seen.
    # Which ones were new is read first, so they wear New this once.
    shown = [t.id for col in columns.values() for t in col["rows"]]
    fresh = set()
    if shown:
        mine = WorkTaskPerson.query.filter(WorkTaskPerson.task_id.in_(shown),
                                           WorkTaskPerson.user_id == current_user.id,
                                           WorkTaskPerson.seen_at.is_(None)).all()
        fresh = {p.task_id for p in mine}
        for p in mine:
            p.seen_at = _now()
        if mine:
            db.session.commit()
    return {"columns": columns, "stages": TASK_STAGES, "fresh": fresh, "who": who,
            "board_project": project, "open_id": open_id, "today": date.today()}


def _board_answer(project_id=None):
    """Where a task action lands: the board it was pressed on."""
    nxt = request.form.get("next") or ""
    if nxt.startswith("/admin/"):
        return redirect(nxt)
    if project_id:
        return redirect(url_for("pm.project_detail", id=project_id))
    return redirect(url_for("workspace.tasks"))


@workspace_bp.route("/tasks")
@login_required
def tasks():
    who = request.args.get("who", "mine")
    who = who if who in ("mine", "all") else "mine"
    return render_template("pm/workspace/tasks.html",
                           **board(who=who, open_id=request.args.get("open", type=int)),
                           **task_options(), **_ctx("tasks"))


def _apply_task(task):
    task.title = (request.form.get("title") or "").strip()[:200]
    task.body = (request.form.get("body") or "").strip()
    task.due_on = _date("due_on")
    task.client_id = _link_id("client_id", Client)
    task.project_id = _link_id("project_id", Project)
    task.product_id = _link_id("product_id", Product)
    task.playbook_id = _link_id("playbook_id", Playbook)
    # A task for a project's client is that client's: filled in rather than
    # asked, because the project already says.
    if task.project_id and not task.client_id:
        task.client_id = db.session.get(Project, task.project_id).client_id


@workspace_bp.route("/tasks/new", methods=["POST"])
@login_required
def task_create():
    if not (request.form.get("title") or "").strip():
        flash("A task needs a line to say what it is.", "warning")
        return _board_answer()
    task = WorkTask(created_by_id=current_user.id)
    _apply_task(task)
    stage = request.form.get("stage") or "backlog"
    task.stage = stage if stage in TASK_STAGE_KEYS else "backlog"
    task.done_at = _now() if task.stage == "done" else None
    task.position = _top_of(task.stage)
    ids = _picked_people("people") or [current_user.id]
    db.session.add(task)
    _set_people(task, ids)
    db.session.commit()
    flash("Task added.", "success")
    return _board_answer(task.project_id)


@workspace_bp.route("/tasks/<int:id>/window")
@login_required
def task_window(id):
    """The task's own window: every field, drawn into the board's overlay."""
    task = db.session.get(WorkTask, id) or abort(404)
    return render_template("pm/workspace/_task_window.html", task=task,
                           ws_people=people(), next=request.args.get("next") or "",
                           about=messages_about("task", task.id, current_user.id),
                           **task_options())


@workspace_bp.route("/tasks/<int:id>", methods=["POST"])
@login_required
def task_update(id):
    task = db.session.get(WorkTask, id) or abort(404)
    if not (request.form.get("title") or "").strip():
        flash("A task needs a line to say what it is.", "warning")
        return _board_answer(task.project_id)
    _apply_task(task)
    if "people_present" in request.form:
        ids = _picked_people("people")
        if not ids:
            flash("A task is for somebody. Pick at least one person.", "warning")
            return _board_answer(task.project_id)
        _set_people(task, ids)
    stage = request.form.get("stage")
    if stage in TASK_STAGE_KEYS and stage != task.stage:
        _set_stage(task, stage)
        task.position = _top_of(stage)
    db.session.commit()
    flash("Saved.", "success")
    return _board_answer(task.project_id)


@workspace_bp.route("/tasks/<int:id>/move", methods=["POST"])
@login_required
def task_move(id):
    """The drag's one post: the column it landed in and the ids of that
    column in their new order. Answers JSON; the page has already moved the
    card, and puts it back if this fails."""
    task = db.session.get(WorkTask, id) or abort(404)
    stage = request.form.get("stage")
    if stage not in TASK_STAGE_KEYS:
        abort(400)
    _set_stage(task, stage)
    order = [int(v) for v in request.form.get("order", "").split(",") if v.strip().isdigit()]
    if stage != "done" and order:
        rows = {t.id: t for t in WorkTask.query.filter(WorkTask.id.in_(order)).all()}
        for i, tid in enumerate(order):
            if tid in rows and rows[tid].stage == stage:
                rows[tid].position = i
    db.session.commit()
    return jsonify({"ok": True, "stage": task.stage, "counts": counts(current_user.id)})


@workspace_bp.route("/tasks/<int:id>/toggle", methods=["POST"])
@login_required
def task_toggle(id):
    """Done, or back to Backlog: the tick on a card."""
    task = db.session.get(WorkTask, id) or abort(404)
    _set_stage(task, "backlog" if task.is_done else "done")
    if not task.is_done:
        task.position = _top_of("backlog")
    db.session.commit()
    return _board_answer(task.project_id)


@workspace_bp.route("/tasks/<int:id>/delete", methods=["POST"])
@login_required
def task_delete(id):
    task = db.session.get(WorkTask, id) or abort(404)
    project_id = task.project_id
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return _board_answer(project_id)


# ---------------------------------------------------------------- projects

# Work is client builds and his own products together, in two sections;
# personal projects have their own view and never mix in with work (Michael,
# 2026-11-04: "Lets Cook doesnt even belong on this page"); archived is the
# third, whatever the kind.
PROJECT_VIEWS = (("work", "Work"), ("personal", "Personal"), ("archived", "Archived"))


def project_icons(projects):
    """{project id: the My Apps tile whose icon its card wears}. Its own
    tile with an icon first; failing that, the one unattached tile that is
    plainly its own (project_autofill.tile_for), which the nightly run then
    attaches, so a logo added on My Apps shows here with nothing typed."""
    from models import AppLink
    import project_autofill
    tiles = AppLink.query.order_by(AppLink.name, AppLink.id).all()
    loose = [t for t in tiles if not t.project_id]
    out = {}
    for p in projects:
        own = [t for t in tiles if t.project_id == p.id]
        pick = next((t for t in own if t.icon_file), None)
        if not pick and not own:
            match = project_autofill.tile_for(p, loose)
            pick = match if match and match.icon_file else None
        if pick:
            out[p.id] = pick
    return out


@workspace_bp.route("/projects")
@login_required
def projects():
    """Every project as a card: what the standalone Projects page was,
    folded in, with his own products apart from client builds."""
    from project_phases import sync_project_phases
    from forms import PHASE_CHOICES
    sync_project_phases()
    search = (request.args.get("q") or "").strip()
    phase = request.args.get("phase") or ""
    phase = phase if phase in dict(PHASE_CHOICES) else ""
    view = request.args.get("view") or "work"
    view = view if view in dict(PROJECT_VIEWS) else "work"

    q = Project.query.join(Client)
    if search:
        q = q.filter(db.or_(Project.name.ilike(f"%{search}%"), Client.name.ilike(f"%{search}%")))
    every = q.order_by(Project.created_at.desc(), Project.id.desc()).all()

    def in_view(p, v):
        if v == "archived":
            return p.status == "archived"
        if p.status == "archived":
            return False
        return (p.kind_effective == "personal") == (v == "personal")

    view_counts = {v: sum(1 for p in every if in_view(p, v)) for v, _ in PROJECT_VIEWS}
    shown = [p for p in every if in_view(p, view)]
    # Faceted: a phase's count is under the other filters, and a phase that
    # would return nothing is not offered. Phases are a client build's only.
    builds = [p for p in shown if p.is_client_build]
    by_phase = {}
    for p in builds:
        by_phase[p.phase] = by_phase.get(p.phase, 0) + 1
    phase_opts = [("", "Any phase")] + [
        (k, f"{label} ({by_phase.get(k, 0)})") for k, label in PHASE_CHOICES
        if by_phase.get(k) or k == phase]
    if phase:
        shown = [p for p in shown if p.is_client_build and p.phase == phase]

    sections = []
    if view == "work":
        for kind, title in (("client", "Client builds"), ("product", "My products")):
            rows = [p for p in shown if p.kind_effective == kind]
            if rows:
                sections.append((title, rows))
    elif shown:
        sections.append(("", shown))

    ids = [p.id for p in shown]
    open_tasks = dict(db.session.query(WorkTask.project_id, func.count(WorkTask.id))
                      .filter(WorkTask.project_id.in_(ids), WorkTask.stage != "done")
                      .group_by(WorkTask.project_id).all()) if ids else {}
    open_tickets = {}
    if ids:
        from models import TICKET_CLOSED_STATUSES
        open_tickets = dict(db.session.query(Ticket.project_id, func.count(Ticket.id))
                            .filter(Ticket.project_id.in_(ids),
                                    Ticket.status.notin_(TICKET_CLOSED_STATUSES))
                            .group_by(Ticket.project_id).all())
    from models import PRODUCT_STAGES
    return render_template("pm/workspace/projects.html", sections=sections, shown=shown,
                           open_tasks=open_tasks, open_tickets=open_tickets,
                           icons=project_icons(shown), product_stages=PRODUCT_STAGES,
                           search=search, phase=phase, view=view, views=PROJECT_VIEWS,
                           view_counts=view_counts, phase_opts=phase_opts, **_ctx("projects"))
