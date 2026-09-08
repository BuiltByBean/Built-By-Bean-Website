"""Notes: the to-do list for everything no other page owns.

One filtered list, so it gets contained scroll and every press is a live
action: ticking a note off must not throw the page back to the top of a
list you were reading (CLAUDE.md LM-4, and the live-action pattern in
base.html).

The four attachments are optional and independent. That is the whole point:
a thought arrives as "chase Cason about the deposit on the plumbing site
before Friday", which is a client, a project and a date at once, and a form
that makes you pick one of them loses two thirds of it.
"""
from datetime import date, datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort,
)
from flask_login import login_required

from models import db, Note, Client, Project, Product, Playbook

notes_bp = Blueprint("notes", __name__, url_prefix="/admin/notes")

# What the status filter may say. "open" leads because that is what a to-do
# list is for; nobody opens this page to read what is finished.
VIEWS = (("open", "Open"), ("done", "Done"), ("all", "All"))


def _date(field):
    """A date off the form, or None. A typo is no date, never today."""
    raw = (request.form.get(field) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _link_id(field, model):
    """An attachment off the form, or None when it was left blank.

    Checked against the table rather than trusted: these arrive as ids in a
    posted form and a stale one would otherwise write a foreign key pointing
    at nothing.
    """
    raw = request.form.get(field, type=int)
    if not raw:
        return None
    return raw if db.session.get(model, raw) else None


def _apply(note):
    note.title = (request.form.get("title") or "").strip()[:200]
    note.body = (request.form.get("body") or "").strip()
    note.due_on = _date("due_on")
    note.client_id = _link_id("client_id", Client)
    note.project_id = _link_id("project_id", Project)
    note.product_id = _link_id("product_id", Product)
    note.playbook_id = _link_id("playbook_id", Playbook)
    return note


def _options():
    """The four pickers, each with a blank row so a link can be taken off.

    An explicit empty option is required: the placeholder alone is not
    selectable, so without this a note could be attached and never detached
    (LM-2).
    """
    return {
        "clients": [("", "No client")] + [
            (c.id, c.name) for c in Client.query.order_by(Client.name).all()],
        "projects": [("", "No project")] + [
            (p.id, p.name) for p in Project.query.order_by(Project.name).all()],
        "products": [("", "No product")] + [
            (p.id, p.name) for p in
            Product.query.filter_by(is_active=True).order_by(Product.name).all()],
        "playbooks": [("", "No playbook")] + [
            (p.id, p.display_name) for p in
            Playbook.query.order_by(Playbook.display_name).all()],
    }


@notes_bp.route("/")
@login_required
def index():
    view = request.args.get("view", "open")
    if view not in {v for v, _ in VIEWS}:
        view = "open"

    q = Note.query
    if view == "open":
        q = q.filter(Note.done_at.is_(None))
    elif view == "done":
        q = q.filter(Note.done_at.isnot(None))

    for field, model in (("client_id", Client), ("project_id", Project),
                         ("product_id", Product), ("playbook_id", Playbook)):
        chosen = request.args.get(field, type=int)
        if chosen:
            q = q.filter(getattr(Note, field) == chosen)

    # Dated first and soonest first, because a date is the only thing here
    # that makes one note more urgent than another. Undated fall to the
    # bottom in the order they were written rather than being hidden.
    notes = sorted(
        q.all(),
        key=lambda n: (n.is_done, n.due_on is None, n.due_on or date.max, -n.id))

    counts = {
        "open": Note.query.filter(Note.done_at.is_(None)).count(),
        "overdue": sum(1 for n in Note.query.filter(Note.done_at.is_(None)).all()
                       if n.is_overdue),
    }
    return render_template("pm/notes/index.html", notes=notes, view=view,
                           views=VIEWS, counts=counts, today=date.today(),
                           filters={f: request.args.get(f, type=int) for f in
                                    ("client_id", "project_id", "product_id",
                                     "playbook_id")},
                           **_options())


@notes_bp.route("/new", methods=["POST"])
@login_required
def create():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("A note needs a line to say what it is.", "warning")
        return redirect(request.form.get("next") or url_for("notes.index"))
    db.session.add(_apply(Note()))
    db.session.commit()
    flash("Noted.", "success")
    return redirect(request.form.get("next") or url_for("notes.index"))


@notes_bp.route("/<int:id>", methods=["POST"])
@login_required
def update(id):
    note = db.session.get(Note, id) or abort(404)
    if not (request.form.get("title") or "").strip():
        flash("A note needs a line to say what it is.", "warning")
        return redirect(request.form.get("next") or url_for("notes.index"))
    _apply(note)
    db.session.commit()
    flash("Saved.", "success")
    return redirect(request.form.get("next") or url_for("notes.index"))


@notes_bp.route("/<int:id>/toggle", methods=["POST"])
@login_required
def toggle(id):
    note = db.session.get(Note, id) or abort(404)
    note.done_at = None if note.is_done else datetime.now(timezone.utc)
    db.session.commit()
    return redirect(request.form.get("next") or url_for("notes.index"))


@notes_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    note = db.session.get(Note, id) or abort(404)
    db.session.delete(note)
    db.session.commit()
    flash("Deleted.", "success")
    return redirect(request.form.get("next") or url_for("notes.index"))
