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
from models import db, AppLink

apps_bp = Blueprint("apps", __name__, url_prefix="/admin/pm/apps")

ICON_DIR = "app_icons"


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


@apps_bp.route("/icon/<int:id>")
@login_required
def icon(id):
    link = db.session.get(AppLink, id) or abort(404)
    if not link.icon_file:
        abort(404)
    return send_from_directory(_icon_folder(), link.icon_file, max_age=86400)


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
        moved = creating or link.url != url

        link.name = name[:120]
        link.url = url[:500]
        link.description = (request.form.get("description") or "").strip()
        db.session.flush()

        # Only go looking when the address is new or has changed, or when
        # asked to. Refetching an unchanged URL on every edit is somebody
        # else's server paying for our save button.
        if moved or request.form.get("refresh_icon"):
            if not _refresh_icon(link) and moved:
                flash(f"Saved. {name} offers no icon, so it shows its initials.", "info")
        db.session.commit()
        flash(f"{name} saved.", "success")
        return redirect(url_for("apps.index"))

    return render_template("pm/apps/form.html", link=link)


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
