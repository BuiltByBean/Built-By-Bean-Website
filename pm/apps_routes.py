"""The My Apps board: everything deployed, as tiles that keep themselves.

This was a hardcoded page at /admin, then rows with a form to edit them. The
form went on 2026-11-05 (Michael: "an edit button on these my apps should not
even [be] there ... icons, links repos etc. should automatically update.
nothing should be manual"). What it set is kept by the board now:

  - name, address, repo, Railway link, store ids, project: register_app when a
    session ships something, and railway_watch.match_tiles nightly, which
    moves a tile's Railway link, repo and platform address to what Railway
    says serves it;
  - the icon: fetched from the app's own site (app_icon_service), again
    monthly and whenever the address moves (tile_upkeep);
  - store ids: read out of the repo (store_ids_service);
  - the half of the board and the order: the drag edge on the tile;
  - taking a tile off: retire_app, or the nightly Railway read when the
    project is gone from Railway (app_retire).

Fetching an icon is a network call to somebody else's server, so it never
happens while a page is being rendered.
"""

import os
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort,
    current_app, send_from_directory,
)
from flask_login import login_required

import app_icon_service
import store_versions_service
from models import db, AppLink, Project

apps_bp = Blueprint("apps", __name__, url_prefix="/admin/apps")

ICON_DIR = "app_icons"


def _normalise(url):
    """An address as something a browser can follow: a bare domain means
    https, and a leading / is a page inside this app, left alone. The door
    (register_app) reads it."""
    url = (url or "").strip()
    if not url or url.startswith(("http://", "https://", "/")):
        return url
    return "https://" + url


def _icon_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], ICON_DIR)
    os.makedirs(path, exist_ok=True)
    return path


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
    """The board, split by whose work it is.

    Client work first, because that is the half with somebody waiting on it.
    Which half a tile is in is the project it carries unless the tile says
    otherwise (AppLink.board_group): a project is a record of who paid for a
    build, not a promise that it is current work. Ordering inside each group
    stays by id, so a tile does not move under the cursor when it changes
    halves.
    """
    apps = AppLink.query.order_by(AppLink.position.is_(None), AppLink.position, AppLink.id).all()
    # A phone app's store versions are asked for on the way in when the last
    # answer is older than FRESH_FOR - two short requests per such tile, so
    # the board is never more than a few hours behind the store pages, and a
    # store that is slow keeps its previous answer rather than blanking it.
    stale = [a for a in apps if store_versions_service.is_stale(a)]
    for a in stale:
        store_versions_service.refresh(a)
    if stale:
        db.session.commit()
    return render_template(
        "pm/apps/index.html",
        site_down=_site_down(apps),
        groups=[{"key": key, "label": label,
                 "apps": [a for a in apps if a.is_client_work == (key == "client")]}
                for key, label in GROUP_LABELS],
        total=len(apps))


def _site_down(apps):
    """{tile id: down since} for tiles whose site has failed the nightly
    check two nights running (live_watch). Read only, no network."""
    from models import SiteCheck
    import live_watch
    try:
        checks = {c.url.rstrip("/").lower(): c for c in
                  SiteCheck.query.filter(SiteCheck.fail_nights >= live_watch.DOWN_NIGHTS).all()}
    except Exception:  # noqa: BLE001 - the table may not exist yet
        db.session.rollback()
        return {}
    out = {}
    for a in apps:
        c = checks.get((a.url or "").rstrip("/").lower())
        if c is not None:
            out[a.id] = c.down_since
    return out


@apps_bp.route("/railway")
@login_required
def railway_unlisted():
    """Live on Railway, not on My Apps: what the nightly Railway read found
    serving an address with no tile for it (railway_watch.unlisted)."""
    import railway_watch
    from models import RailwayService
    services = railway_watch.unlisted()
    ignored = (RailwayService.query.filter_by(ignored=True)
               .order_by(RailwayService.project_name, RailwayService.service_name).all())
    return render_template("pm/apps/railway.html", services=services, ignored=ignored)


@apps_bp.route("/railway/<int:id>/add", methods=["POST"])
@login_required
def railway_add(id):
    """One press: a tile for this service. It answers the list again, so the
    live action swaps the row out where it stands; the flash names the tile,
    which is on My Apps to check."""
    import railway_watch
    from models import RailwayService
    s = db.session.get(RailwayService, id) or abort(404)
    if not s.domains:
        flash("That service has no address to put on a tile.", "warning")
        return redirect(url_for("apps.railway_unlisted"))
    domain = (s.custom_domains or s.domains)[0]
    link = AppLink(name=(s.project_name if s.service_name in ("web", s.project_name)
                         else f"{s.project_name} {s.service_name}")[:120],
                   url=f"https://{domain}"[:500], description="",
                   railway_url=s.dashboard_url[:500],
                   github_url=f"https://github.com/{s.repo}"[:500] if s.repo else None)
    projects = railway_watch.project_candidates(
        s.project_ref, RailwayService.query.all(), Project.query.all(), AppLink.query.all())
    if len(projects) == 1:
        link.project_id = next(iter(projects))
    db.session.add(link)
    db.session.flush()
    _refresh_icon(link)
    db.session.commit()
    flash(f"{link.name} is on My Apps.", "success")
    return redirect(url_for("apps.railway_unlisted"))


@apps_bp.route("/railway/<int:id>/ignore", methods=["POST"])
@login_required
def railway_ignore(id):
    """Not an app: never listed again. And back, from the same page."""
    from models import RailwayService
    s = db.session.get(RailwayService, id) or abort(404)
    s.ignored = request.form.get("undo") != "1"
    db.session.commit()
    import live_watch
    live_watch._CACHE["rows"] = None
    return redirect(url_for("apps.railway_unlisted"))


# The halves of the board (Michael, 2026-11-04): "the top section is products
# that make me money. bottom section is my personal projects." The stored
# values stay "client" and "mine" so no row moves; only the names changed.
GROUP_LABELS = (("client", "Makes money"), ("mine", "Personal projects"))


@apps_bp.route("/<int:id>/group", methods=["POST"])
@login_required
def move_group(id):
    """A tile dragged to the other half of the board. Answers JSON, because
    the page has already moved the tile and only needs to know it held."""
    link = db.session.get(AppLink, id) or abort(404)
    group = request.form.get("group") or ""
    if group not in AppLink.BOARD_GROUPS:
        return {"ok": False}, 400
    link.board_group = group
    db.session.commit()
    return {"ok": True, "group": group}


@apps_bp.route("/order", methods=["POST"])
@login_required
def order():
    """A tile dropped somewhere on the board: the half it landed in and that
    half's tiles in their new order, top left to bottom right. Only the tile
    that crossed halves has its half written; the rest only take positions,
    so a tile that follows its project keeps following it. Answers JSON,
    because the page has already moved the tiles."""
    group = request.form.get("group") or ""
    moved = request.form.get("moved", type=int)
    try:
        ids = [int(x) for x in (request.form.get("ids") or "").split(",") if x.strip()]
    except ValueError:
        return {"ok": False}, 400
    if group not in AppLink.BOARD_GROUPS or not ids or len(ids) != len(set(ids)):
        return {"ok": False}, 400
    links = {a.id: a for a in AppLink.query.filter(AppLink.id.in_(ids)).all()}
    if len(links) != len(ids):
        return {"ok": False}, 400
    for n, i in enumerate(ids):
        links[i].position = n
    if moved in links and links[moved].is_client_work != (group == "client"):
        links[moved].board_group = group
    db.session.commit()
    return {"ok": True}


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
