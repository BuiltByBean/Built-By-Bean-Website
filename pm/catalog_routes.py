"""The catalog: which apps prospects may see, and the links that let them in.

Two blueprints (issue #23):

- `catalog` at /admin/catalog, for anybody signed in to the board: approve
  apps, write their catalog name, pitch and what they do, add tour pictures,
  make a link per prospect, and see the showcase exactly as a prospect will.
- `showcase` at /work/<token>, the prospect's side. No login, and no way in
  without a live link: an unknown, expired or switched-off token is the same
  page that names nothing. Every answer is private, no-store and noindex,
  and sends no referrer, because the token is in the address.

The logic is catalog_service.py.
"""
import json
import os
from datetime import timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required

import catalog_service as cs
from models import db, AppLink, CatalogLink, CatalogShot

catalog_bp = Blueprint("catalog", __name__, url_prefix="/admin/catalog")
showcase_bp = Blueprint("showcase", __name__, url_prefix="/work")


# ── The board's side ─────────────────────────────────────


def _back():
    return redirect(url_for("catalog.index"))


@catalog_bp.route("/")
@login_required
def index():
    apps = cs.approved()
    others = (AppLink.query.filter(AppLink.catalog.is_(False))
              .order_by(AppLink.name).all())
    links = CatalogLink.query.order_by(CatalogLink.created_at.desc(), CatalogLink.id.desc()).all()
    names = {a.id: a.showcase_name for a in apps}
    return render_template("pm/catalog/index.html", apps=apps, others=others, links=links,
                           names=names, live=cs.live, now=cs.now(), cs=cs,
                           book=cs.marks())


@catalog_bp.route("/apps/add", methods=["POST"])
@login_required
def add():
    app = db.session.get(AppLink, request.form.get("app_id", type=int) or 0)
    if app is None:
        flash("Pick an app to add.", "warning")
        return _back()
    app.catalog = True
    last = max([a.catalog_position or 0 for a in cs.approved()] or [0])
    app.catalog_position = last + 1
    db.session.commit()
    flash(f"{app.name} is in the catalog.", "success")
    return _back()


@catalog_bp.route("/apps/<int:id>/remove", methods=["POST"])
@login_required
def remove(id):
    app = db.session.get(AppLink, id) or abort(404)
    app.catalog = False
    db.session.commit()
    flash(f"{app.showcase_name} is out of the catalog. Its words and tour are kept.", "success")
    return _back()


@catalog_bp.route("/apps/<int:id>/save", methods=["POST"])
@login_required
def save(id):
    app = db.session.get(AppLink, id) or abort(404)
    app.catalog_name = (request.form.get("catalog_name") or "").strip()[:120] or None
    app.catalog_pitch = (request.form.get("catalog_pitch") or "").strip()[:600] or None
    app.catalog_points = (request.form.get("catalog_points") or "").strip()[:2000] or None
    if "catalog_scale" in request.form:
        app.catalog_scale = (request.form.get("catalog_scale") or "").strip()[:160] or None
        app.catalog_highlights = (request.form.get("catalog_highlights") or "").strip()[:600] or None
    if "catalog_services_extra" in request.form:
        app.catalog_services_extra = (request.form.get("catalog_services_extra") or "").strip()[:1000] or None
        app.catalog_services_hidden = (request.form.get("catalog_services_hidden") or "").strip()[:1000] or None
    demo = (request.form.get("demo_url") or "").strip()
    if demo and not demo.startswith(("https://", "http://")):
        flash("A live demo address starts with https://", "warning")
        return _back()
    app.demo_url = demo[:500] or None
    db.session.commit()
    flash(f"{app.showcase_name} saved.", "success")
    return _back()


@catalog_bp.route("/apps/<int:id>/move", methods=["POST"])
@login_required
def move(id):
    apps = cs.approved()
    ids = [a.id for a in apps]
    if id not in ids:
        abort(404)
    i = ids.index(id)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    for pos, app_id in enumerate(ids, start=1):
        next(a for a in apps if a.id == app_id).catalog_position = pos
    db.session.commit()
    return _back()


@catalog_bp.route("/apps/<int:id>/shots", methods=["POST"])
@login_required
def add_shots(id):
    app = db.session.get(AppLink, id) or abort(404)
    added, refused = 0, 0
    for f in request.files.getlist("shots"):
        if not f or not f.filename:
            continue
        if cs.add_shot(app, f.read(cs.MAX_BYTES + 1)) is None:
            refused += 1
        else:
            added += 1
    if added:
        flash(f"{added} picture{'' if added == 1 else 's'} added to {app.showcase_name}'s tour.", "success")
    if refused:
        flash(f"{refused} file{'' if refused == 1 else 's'} skipped: PNG, JPEG or WebP, up to 8 MB.", "warning")
    return _back()


@catalog_bp.route("/apps/<int:id>/icon", methods=["POST"])
@login_required
def set_icon(id):
    app = db.session.get(AppLink, id) or abort(404)
    f = request.files.get("icon")
    name = cs.store_image(f.read(cs.MAX_BYTES + 1)) if f and f.filename else None
    if name is None:
        flash("An icon is a PNG, JPEG or WebP picture, up to 8 MB.", "warning")
        return _back()
    app.catalog_icon = name
    db.session.commit()
    flash(f"{app.showcase_name} has its own icon in the catalog.", "success")
    return _back()


@catalog_bp.route("/apps/<int:id>/icon-file")
@login_required
def icon_file(id):
    app = db.session.get(AppLink, id) or abort(404)
    return _app_icon(app)


@catalog_bp.route("/shots/<int:id>/caption", methods=["POST"])
@login_required
def caption(id):
    shot = db.session.get(CatalogShot, id) or abort(404)
    shot.caption = (request.form.get("caption") or "").strip()[:200]
    db.session.commit()
    return _back()


@catalog_bp.route("/shots/<int:id>/move", methods=["POST"])
@login_required
def move_shot(id):
    shot = db.session.get(CatalogShot, id) or abort(404)
    shots = list(shot.app.catalog_shots)
    i = shots.index(shot)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(shots):
        shots[i], shots[j] = shots[j], shots[i]
    for pos, s in enumerate(shots, start=1):
        s.position = pos
    db.session.commit()
    return _back()


@catalog_bp.route("/shots/<int:id>/delete", methods=["POST"])
@login_required
def delete_shot(id):
    shot = db.session.get(CatalogShot, id) or abort(404)
    path = os.path.join(cs.shots_folder(), shot.file)
    db.session.delete(shot)
    db.session.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    return _back()


@catalog_bp.route("/shots/<int:id>")
@login_required
def shot_file(id):
    shot = db.session.get(CatalogShot, id) or abort(404)
    return _send_shot(shot)


@catalog_bp.route("/links", methods=["POST"])
@login_required
def make_link():
    label = (request.form.get("label") or "").strip()
    if not label:
        flash("Say who the link is for.", "warning")
        return _back()
    approved = {a.id for a in cs.approved()}
    picked = [int(v) for v in request.form.getlist("app_ids") if v.isdigit() and int(v) in approved]
    # Every approved app ticked is the same as none ticked: all of them,
    # including any approved later.
    ids = picked if picked and set(picked) != approved else None
    days = request.form.get("days", type=int) or cs.LINK_DAYS
    link = cs.make_link(label, ids, days=max(1, min(days, 365)), user=current_user)
    flash(f"Link made for {link.label}. Copy it from the list.", "success")
    return _back()


@catalog_bp.route("/links/<int:id>/off", methods=["POST"])
@login_required
def link_off(id):
    link = db.session.get(CatalogLink, id) or abort(404)
    link.revoked_at = cs.now()
    db.session.commit()
    flash(f"{link.label}'s link is switched off.", "success")
    return _back()


@catalog_bp.route("/links/<int:id>/extend", methods=["POST"])
@login_required
def link_extend(id):
    link = db.session.get(CatalogLink, id) or abort(404)
    link.revoked_at = None
    link.expires_at = max(link.expires_at, cs.now()) + timedelta(days=cs.LINK_DAYS)
    db.session.commit()
    flash(f"{link.label}'s link is good for another {cs.LINK_DAYS} days.", "success")
    return _back()


@catalog_bp.route("/preview")
@login_required
def preview():
    """The showcase as a prospect sees it, every approved app. Nothing is
    recorded: a look from the board is not a prospect opening it."""
    apps = cs.approved()
    return _showcase(apps, preview=True)


@catalog_bp.route("/preview/<int:id>")
@login_required
def preview_app(id):
    apps = cs.approved()
    app = next((a for a in apps if a.id == id), None) or abort(404)
    return _app_page(app, apps, preview=True)


# ── The prospect's side ──────────────────────────────────


def _private(resp):
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _gone():
    from flask import make_response
    return _private(make_response(render_template("showcase/gone.html"), 404))


def _addresses(link):
    """Where the showcase's own links go: through the prospect's token, or,
    for Michael's preview, through the board."""
    if link is not None:
        return dict(
            base_url=url_for("showcase.showcase", token=link.token),
            icon_token=link.token,
            app_href=lambda a: url_for("showcase.showcase_app", token=link.token, id=a.id),
            shot_href=lambda s: url_for("showcase.showcase_shot", token=link.token, id=s.id))
    return dict(
        base_url=url_for("catalog.preview"),
        icon_token="preview",
        app_href=lambda a: url_for("catalog.preview_app", id=a.id),
        shot_href=lambda s: url_for("catalog.shot_file", id=s.id))


def _showcase(apps, link=None, preview=False):
    from flask import make_response
    book = cs.marks()
    return _private(make_response(render_template(
        "showcase/index.html", apps=apps, glance=cs.overview(apps, book), link=link, preview=preview,
        cs=cs, book=book, **_addresses(link))))


def _app_page(app, apps, link=None, preview=False):
    from flask import make_response
    return _private(make_response(render_template(
        "showcase/app.html", app=app, apps=apps, link=link, preview=preview, cs=cs,
        book=cs.marks(), **_addresses(link))))


def _send_shot(shot):
    resp = send_from_directory(cs.shots_folder(), shot.file, max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'"
    return _private(resp)


@showcase_bp.route("/<token>")
def showcase(token):
    link = cs.by_token(token)
    if link is None:
        return _gone()
    apps = cs.apps_for(link)
    cs.record_view(link)
    return _showcase(apps, link=link)


@showcase_bp.route("/<token>/<int:id>")
def showcase_app(token, id):
    link = cs.by_token(token)
    if link is None:
        return _gone()
    apps = cs.apps_for(link)
    app = next((a for a in apps if a.id == id), None)
    if app is None:
        return _gone()
    cs.record_view(link, app)
    return _app_page(app, apps, link=link)


@showcase_bp.route("/<token>/shot/<int:id>")
def showcase_shot(token, id):
    link = cs.by_token(token)
    shot = db.session.get(CatalogShot, id)
    if link is None or shot is None or shot.app_link_id not in {a.id for a in cs.apps_for(link)}:
        abort(404)
    return _send_shot(shot)


def _icon_response(folder, name):
    resp = send_from_directory(folder, name, max_age=3600)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return _private(resp)


@showcase_bp.route("/<token>/icon/<int:id>")
def showcase_icon(token, id):
    """An approved app's own icon, through the link."""
    link = cs.by_token(token) if token != "preview" else None
    allowed = cs.apps_for(link) if link else (cs.approved() if token == "preview" and current_user.is_authenticated else [])
    app = next((a for a in allowed if a.id == id), None)
    if app is None:
        abort(404)
    return _app_icon(app)


def _app_icon(app):
    """The catalog's own icon, else the tile's unless the catalog renamed the
    app (then the tile's icon is the client's, and is never shown)."""
    if app.catalog_icon:
        return _icon_response(cs.shots_folder(), app.catalog_icon)
    if app.icon_file and not app.renamed:
        from pm.apps_routes import _icon_folder
        return _icon_response(_icon_folder(), app.icon_file)
    abort(404)


@showcase_bp.route("/<token>/mark/<slug>")
def showcase_mark(token, slug):
    """A service's fetched mark, through the link. A chosen mark (logo_path)
    is a static file and needs none of this."""
    from models import Playbook
    if not (cs.by_token(token) or (token == "preview" and current_user.is_authenticated)):
        abort(404)
    pb = Playbook.query.filter_by(slug=slug, is_active=True).first()
    if pb is None or not pb.icon_file:
        abort(404)
    from pm.playbooks_routes import _icon_folder as pb_folder
    return _icon_response(pb_folder(), pb.icon_file)
