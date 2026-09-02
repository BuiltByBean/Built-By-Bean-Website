"""The My Apps board: everything deployed, as tiles you can edit.

This was a hardcoded page at /admin. It is rows now, so adding something is a
form rather than a deploy.

Each tile wears the app's own icon, fetched from its manifest or favicon —
see app_icon_service. That fetch is a network call to somebody else's server,
so it never happens while a page is being rendered: it runs on save, and on
demand from the board. A tile whose site offers no icon shows its initials
and is not retried on every view.
"""

import os
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort,
    current_app, send_from_directory,
)
from flask_login import login_required

import app_icon_service
from models import db, AppLink, Project

apps_bp = Blueprint("apps", __name__, url_prefix="/admin/apps")

ICON_DIR = "app_icons"

# What may be uploaded by hand, for the apps that expose nothing to fetch:
# anything behind a login, or a page inside this app.
UPLOAD_TYPES = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp",
                "svg": "svg", "gif": "gif", "ico": "ico"}
MAX_UPLOAD = 2 * 1024 * 1024


def _icon_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], ICON_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _normalise(url):
    """What the user typed, as something a browser can follow.

    A bare domain is the common case — somebody types builtbybeans.com and
    means https. A leading / is a page inside this app and is left alone.
    """
    url = (url or "").strip()
    if not url or url.startswith(("http://", "https://", "/")):
        return url
    return "https://" + url


def _refresh_icon(link):
    """Fetch and store this app's icon. Returns whether one was found."""
    got = app_icon_service.fetch(link.url)
    # Stamped either way, so a site with no icon is not re-fetched on every
    # visit to the board.
    link.icon_fetched_at = datetime.now(timezone.utc)
    if not got:
        return False
    data, ext, source = got
    old = link.icon_file
    link.icon_file = app_icon_service.store(data, ext, _icon_folder())
    link.icon_source = source[:500]
    if old:
        try:
            os.remove(os.path.join(_icon_folder(), old))
        except OSError:
            pass  # a missing file is already the state we wanted
    return True


@apps_bp.route("/")
@login_required
def index():
    return render_template("pm/apps/index.html",
                           apps=AppLink.query.order_by(AppLink.id).all())


def _store_upload(link, upload):
    """Take an icon straight from the user. Returns why not, or None."""
    ext = os.path.splitext(upload.filename or "")[1].lstrip(".").lower()
    ext = UPLOAD_TYPES.get(ext)
    if not ext:
        return "That file type cannot be used as an icon."
    data = upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return "That image is larger than 2MB."
    if len(data) < 64:
        return "That file is empty."
    old = link.icon_file
    link.icon_file = app_icon_service.store(data, ext, _icon_folder())
    # No source means it was given rather than found, which is what stops a
    # later URL change from fetching over the top of it.
    link.icon_source = None
    link.icon_fetched_at = datetime.now(timezone.utc)
    if old:
        try:
            os.remove(os.path.join(_icon_folder(), old))
        except OSError:
            pass
    return None


@apps_bp.route("/icon/<int:id>")
@login_required
def icon(id):
    link = db.session.get(AppLink, id) or abort(404)
    if not link.icon_file:
        abort(404)
    resp = send_from_directory(_icon_folder(), link.icon_file, max_age=86400)
    # These files come from other people's servers and from uploads, and an
    # SVG is a document that can carry script. Nothing here needs to load
    # anything or run anything, so say so.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@apps_bp.route("/new", methods=["GET", "POST"])
@apps_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit(id=None):
    link = (db.session.get(AppLink, id) or abort(404)) if id else None

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        url = _normalise(request.form.get("url"))
        if not name or not url:
            flash("A tile needs a name and a link.", "warning")
            return redirect(request.url)

        creating = link is None
        if creating:
            link = AppLink()
            db.session.add(link)
        # An icon that was uploaded by hand is not replaced just because the
        # address changed; it was chosen, not found.
        given = bool(link.icon_file) and link.icon_source is None
        moved = creating or link.url != url

        link.name = name[:120]
        link.url = url[:500]
        link.description = (request.form.get("description") or "").strip()
        link.railway_url = _normalise(request.form.get("railway_url"))[:500] or None
        link.github_url = _normalise(request.form.get("github_url"))[:500] or None
        # Blank means unattached, which is the normal state for the half of
        # the board that is mine rather than a client's.
        chosen = request.form.get("project_id", type=int)
        link.project_id = chosen if chosen and db.session.get(Project, chosen) else None
        db.session.flush()

        upload = request.files.get("icon_upload")
        if upload and upload.filename:
            problem = _store_upload(link, upload)
            if problem:
                db.session.rollback()
                flash(problem, "warning")
                return redirect(request.url)
        # Only go looking when the address is new or has changed, or when
        # asked to. Refetching an unchanged URL on every edit is somebody
        # else's server paying for our save button.
        elif (moved and not given) or request.form.get("refresh_icon"):
            if not _refresh_icon(link) and moved:
                flash(f"Saved. {name} offers no icon to fetch — "
                      f"upload one on this page, or it shows its initials.", "info")
        db.session.commit()
        flash(f"{name} saved.", "success")
        return redirect(url_for("apps.index"))

    # Pairs rather than objects, because the dropdown macro wants
    # (value, label) and Jinja has no zip to build them at render time.
    project_options = [("", "Not a client project")] + [
        (p.id, f"{p.name} — {p.client.name}")
        for p in Project.query.order_by(Project.name).all()
    ]
    return render_template("pm/apps/form.html", link=link,
                           project_options=project_options)


@apps_bp.route("/<int:id>/refresh-icon", methods=["POST"])
@login_required
def refresh_icon(id):
    link = db.session.get(AppLink, id) or abort(404)
    found = _refresh_icon(link)
    db.session.commit()
    flash(f"Icon updated for {link.name}." if found
          else f"{link.name} offers no icon to fetch.", "success" if found else "warning")
    return redirect(url_for("apps.index"))


@apps_bp.route("/refresh-icons", methods=["POST"])
@login_required
def refresh_all():
    """Go and get every icon that is missing one.

    Deliberately only the missing ones: a dozen sequential fetches is already
    slow enough to feel, and re-pulling icons that are already right buys
    nothing.
    """
    todo = AppLink.query.filter(AppLink.icon_file.is_(None)).all()
    found = sum(1 for link in todo if _refresh_icon(link))
    db.session.commit()
    if not todo:
        flash("Every tile already has its icon.", "info")
    else:
        flash(f"Fetched {found} of {len(todo)} missing icons. "
              f"The rest offer none and show initials.", "success")
    return redirect(url_for("apps.index"))


@apps_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    link = db.session.get(AppLink, id) or abort(404)
    if link.icon_file:
        try:
            os.remove(os.path.join(_icon_folder(), link.icon_file))
        except OSError:
            pass
    name = link.name
    db.session.delete(link)
    db.session.commit()
    flash(f"{name} removed from the board.", "success")
    return redirect(url_for("apps.index"))
