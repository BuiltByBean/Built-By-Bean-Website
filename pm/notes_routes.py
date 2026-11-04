"""Notes became the Workspace's Tasks on 2026-11-04.

Every note was carried across as a task with the same id (migration
a5d17c3e92b4), so the only thing left here is the old address, which now
opens the board. Kept as a blueprint so a `url_for("notes.index")` anywhere
still resolves.
"""
from flask import Blueprint, redirect, url_for
from flask_login import login_required

notes_bp = Blueprint("notes", __name__, url_prefix="/admin/notes")


@notes_bp.route("/")
@login_required
def index():
    return redirect(url_for("workspace.tasks"), 301)
