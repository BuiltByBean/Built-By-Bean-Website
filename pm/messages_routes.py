"""What clients and leads have written, and the replies.

One list of conversations, newest activity first, and one page per
conversation with the reply box at the bottom. Sending is Michael's own
act - the attention page brings him here, nothing goes out on its own.
"""
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   abort, request, current_app)
from flask_login import login_required

from models import db, Message
from pm import mail_service

messages_bp = Blueprint("messages", __name__, url_prefix="/admin/messages")


def _threads():
    """Root messages with the time of their latest activity, newest first."""
    roots = (Message.query.filter(Message.thread_id == Message.id)
             .order_by(Message.received_at.desc()).all())
    latest = dict(db.session.query(Message.thread_id, db.func.max(Message.received_at))
                  .group_by(Message.thread_id).all())
    waiting = {tid for (tid,) in db.session.query(Message.thread_id)
               .filter(Message.direction == "in", Message.status == "new").distinct().all()}
    counts = dict(db.session.query(Message.thread_id, db.func.count(Message.id))
                  .group_by(Message.thread_id).all())
    rows = []
    for root in roots:
        rows.append({
            "root": root,
            "latest": latest.get(root.id) or root.received_at,
            "waiting": root.id in waiting,
            "count": counts.get(root.id, 1),
        })
    rows.sort(key=lambda r: (not r["waiting"], -(r["latest"].timestamp() if r["latest"] else 0)))
    return rows


@messages_bp.route("/")
@login_required
def index():
    mail_service.kick(current_app._get_current_object())
    return render_template("pm/messages/index.html", threads=_threads(),
                           mail=mail_service.status(),
                           configured=mail_service.configured())


@messages_bp.route("/sync", methods=["POST"])
@login_required
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
@login_required
def detail(id):
    message = db.session.get(Message, id) or abort(404)
    root_id = message.thread_id or message.id
    thread = (Message.query.filter_by(thread_id=root_id)
              .order_by(Message.received_at).all())
    # The message the reply box answers: the newest inbound in the thread.
    last_in = next((m for m in reversed(thread) if m.direction == "in"), None)
    return render_template("pm/messages/detail.html", thread=thread,
                           root=thread[0] if thread else message, last_in=last_in,
                           configured=mail_service.configured())


@messages_bp.route("/<int:id>/reply", methods=["POST"])
@login_required
def reply(id):
    message = db.session.get(Message, id) or abort(404)
    text = (request.form.get("body") or "").strip()
    if not text:
        flash("Write something first.", "warning")
        return redirect(url_for("messages.detail", id=message.id))
    try:
        mail_service.send_reply(message, text)
    except Exception as err:  # noqa: BLE001 - said on the page, not in a log
        flash(f"Could not send it: {str(err)[:200]}", "warning")
        return redirect(url_for("messages.detail", id=message.id))
    flash(f"Sent to {message.from_email}.", "success")
    return redirect(url_for("messages.detail", id=message.id))


@messages_bp.route("/<int:id>/archive", methods=["POST"])
@login_required
def archive(id):
    message = db.session.get(Message, id) or abort(404)
    root_id = message.thread_id or message.id
    now = datetime.now(timezone.utc)
    for m in Message.query.filter_by(thread_id=root_id, direction="in").all():
        if m.status == "new":
            m.status = "archived"
            m.replied_at = m.replied_at or now
    db.session.commit()
    flash("Archived.", "success")
    return redirect(request.form.get("next") or url_for("messages.index"))
