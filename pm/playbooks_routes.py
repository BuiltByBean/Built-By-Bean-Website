"""Vendor runbooks: the tile grid, the runbook, and editing one.

Addressed by slug rather than id, because these get linked to from notes and
from each other, and `/admin/playbooks/twilio` survives a reseed while
`/9` does not. Delete is the one exception: it takes an id, because a delete
posted against a name is the request most likely to be aimed at the wrong row
after somebody renames one.
"""
import os
import re
from datetime import datetime, timezone

import markdown
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort,
    current_app, send_from_directory,
)
from flask_login import login_required
from markupsafe import Markup

import app_icon_service
from models import db, Playbook, ServiceProvider

playbooks_bp = Blueprint("playbooks", __name__, url_prefix="/admin/playbooks")

# Kept apart from the app icons: the two are fetched the same way but belong
# to different rows, and one board clearing its cache must not blank the other.
ICON_DIR = "playbook_icons"

# A press asks a handful of other people's servers, each with its own timeout.
# Capped so the answer arrives while somebody is still looking at the page.
MARK_BATCH = 8

# What may be handed over directly, for a vendor whose front door answers
# nothing. Same set the app board takes.
UPLOAD_TYPES = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp",
                "svg": "svg", "gif": "gif", "ico": "ico"}
MAX_UPLOAD = 2 * 1024 * 1024


def _icon_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], ICON_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def refresh_playbook_icon(playbook):
    """Fetch and store this vendor's mark. Returns whether one was found.

    Best effort by design, exactly as the app board's is: a vendor that is
    down, slow or offers nothing leaves the runbook on its monogram, which is
    a page that renders rather than a page that hangs.
    """
    domain = playbook.mark_domain
    if not domain:
        return False
    url = (playbook.vendor_url or "").strip()
    # A vendor_url filed through the door is whatever the session typed, and
    # a bare domain is the common case. fetch refuses anything without a
    # scheme, so it would have silently found nothing.
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    got = None
    for attempt in (url, "https://" + domain):
        if not attempt:
            continue
        try:
            got = app_icon_service.fetch(attempt)
        except Exception:
            got = None
        if got:
            break
    if not got:
        # The site itself said nothing. Ask for the same picture the other
        # way before giving up, because "no mark" here has almost always
        # meant a front door refusing a request rather than a vendor with
        # no logo.
        try:
            got = app_icon_service.fetch_by_domain(domain)
        except Exception:
            got = None
    # Stamped either way, so a vendor with no icon is not asked again on the
    # next press.
    playbook.icon_fetched_at = datetime.now(timezone.utc)
    if not got:
        return False
    data, ext, source = got
    old = playbook.icon_file
    playbook.icon_file = app_icon_service.store(data, ext, _icon_folder())
    playbook.icon_source = (source or "")[:500]
    if old and old != playbook.icon_file:
        try:
            os.remove(os.path.join(_icon_folder(), old))
        except OSError:
            pass  # a missing file is already the state we wanted
    return True


# ── Markdown ────────────────────────────────────────────────

# Only these may appear in an href or a src. Everything else is neutralised.
# `javascript:` in a link is the one injection markdown will build for you
# even with raw HTML turned off: the tags are escaped, but `[x](javascript:…)`
# still compiles to a live anchor.
_SAFE_URL = re.compile(r"^(?:https?://|mailto:|/|\#|\.{0,2}/)", re.I)
_ATTR = re.compile(r'\b(href|src)="([^"]*)"', re.I)


def _safe_attrs(html):
    def scrub(m):
        attr, value = m.group(1), m.group(2)
        return f'{attr}="{value}"' if _SAFE_URL.match(value.strip()) else f'{attr}="#"'
    return _ATTR.sub(scrub, html)


def render_markdown(text):
    """Markdown to HTML, with no path from the source to live HTML.

    The two raw-HTML handlers are deregistered rather than the output being run
    through a sanitiser afterwards. That way `<input` inside a code block stays
    the literal text somebody typed instead of being escaped twice, which is
    what pre-escaping the source would do to half the content on these pages.

    Authoring is admin-only, so this is defence in depth rather than the only
    thing standing between a stranger and a script tag. It still belongs here:
    a runbook is exactly the kind of page that ends up holding a snippet
    somebody pasted from a vendor's docs.
    """
    if not text:
        return Markup("")
    md = markdown.Markdown(
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return Markup(_safe_attrs(md.convert(text)))


@playbooks_bp.app_template_filter("markdown")
def markdown_filter(text):
    return render_markdown(text)


# ── Form handling ───────────────────────────────────────────

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(value):
    return _SLUG_STRIP.sub("-", (value or "").strip().lower()).strip("-")[:60]


def _apply_form(playbook):
    """Read the form onto a playbook. Returns an error string, or None."""
    display_name = request.form.get("display_name", "").strip()
    if not display_name:
        return "A playbook needs a name."

    slug = _slugify(request.form.get("slug", "")) or _slugify(display_name)
    if not slug:
        return "That name does not reduce to a usable slug. Set one by hand."

    clash = Playbook.query.filter(Playbook.slug == slug).first()
    if clash and clash.id != playbook.id:
        return f"There is already a playbook at /{slug}."

    playbook.slug = slug
    playbook.display_name = display_name
    playbook.one_liner = request.form.get("one_liner", "").strip()
    playbook.vendor_url = request.form.get("vendor_url", "").strip()
    playbook.logo_path = request.form.get("logo_path", "").strip()
    playbook.is_active = bool(request.form.get("is_active"))
    chosen = request.form.get("category", "").strip()
    if chosen in {value for value, _, _ in Playbook.CATEGORIES}:
        playbook.category = chosen

    try:
        playbook.sort_order = int(request.form.get("sort_order") or 0)
    except ValueError:
        playbook.sort_order = 0

    provider_id = request.form.get("service_provider_id", "").strip()
    playbook.service_provider_id = int(provider_id) if provider_id.isdigit() else None

    for field, _heading in Playbook.SECTIONS:
        setattr(playbook, field, request.form.get(field, "").strip())

    return None


def _providers():
    return ServiceProvider.query.order_by(ServiceProvider.display_name).all()


# ── Views ───────────────────────────────────────────────────


@playbooks_bp.route("/")
@login_required
def playbooks_index():
    playbooks = Playbook.query.order_by(
        Playbook.sort_order, Playbook.display_name
    ).all()

    # Grouped in CATEGORIES order rather than sorted by the column, so the
    # page reads slowest-first: the ones with a person and an approval in
    # front of them, then the ones that are only mine, then the ones that are
    # a key. An empty group is dropped rather than shown as a bare heading.
    groups = []
    for value, label, blurb in Playbook.CATEGORIES:
        rows = [p for p in playbooks if p.category == value]
        if rows:
            groups.append({"label": label, "blurb": blurb, "playbooks": rows})

    # Anything carrying a category that is no longer in CATEGORIES still has to
    # appear, or editing the list silently hides a runbook.
    known = {value for value, _, _ in Playbook.CATEGORIES}
    orphans = [p for p in playbooks if p.category not in known]
    if orphans:
        groups.append({"label": "Uncategorised", "blurb": "", "playbooks": orphans})

    # Counted so the page can offer the fetch only when there is something
    # to fetch. A button that can only tell you it did nothing is furniture.
    return render_template("pm/playbooks/index.html",
                           playbooks=playbooks, groups=groups,
                           missing=sum(1 for p in playbooks if p.wants_mark))


def store_playbook_upload(playbook, upload):
    """Take a mark straight from him. Returns why not, or None.

    The one path that cannot fail on somebody else's server. A fetch depends
    on a vendor answering; this depends on nothing.
    """
    ext = os.path.splitext(upload.filename or "")[1].lstrip(".").lower()
    ext = UPLOAD_TYPES.get(ext)
    if not ext:
        return "That file type cannot be used as a mark."
    data = upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return "That image is larger than 2MB."
    if len(data) < 64:
        return "That file is empty."
    old = playbook.icon_file
    playbook.icon_file = app_icon_service.store(data, ext, _icon_folder())
    # No source means it was given rather than found, which is what stops a
    # later sweep from fetching over the top of it.
    playbook.icon_source = None
    playbook.icon_fetched_at = datetime.now(timezone.utc)
    if old and old != playbook.icon_file:
        try:
            os.remove(os.path.join(_icon_folder(), old))
        except OSError:
            pass
    return None


@playbooks_bp.route("/<slug>/mark", methods=["POST"])
@login_required
def mark_upload(slug):
    playbook = Playbook.query.filter_by(slug=slug).first() or abort(404)
    upload = request.files.get("mark")
    if not upload or not upload.filename:
        flash("Choose an image first.", "warning")
        return redirect(url_for("playbooks.playbook_detail", slug=slug))
    problem = store_playbook_upload(playbook, upload)
    if problem:
        flash(problem, "error")
    else:
        db.session.commit()
        flash(f"{playbook.display_name} has its mark.", "success")
    return redirect(url_for("playbooks.playbook_detail", slug=slug))


@playbooks_bp.route("/<slug>/icon")
@login_required
def icon(slug):
    playbook = Playbook.query.filter_by(slug=slug).first() or abort(404)
    if not playbook.icon_file:
        abort(404)
    resp = send_from_directory(_icon_folder(), playbook.icon_file, max_age=86400)
    # Fetched from other people's servers, and an SVG is a document that can
    # carry script. Nothing here loads or runs anything, so say so.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@playbooks_bp.route("/marks", methods=["POST"])
@login_required
def marks_refresh():
    """Go and get the marks for the runbooks still showing a monogram.

    Not on page render: this is a network call to somebody else's server, and
    a board that hangs waiting for a picture is worse than one without it.
    """
    waiting = [p for p in Playbook.query.order_by(Playbook.sort_order).all()
               if p.wants_mark]
    batch = waiting[:MARK_BATCH]
    missed = [p.display_name for p in batch if not refresh_playbook_icon(p)]
    db.session.commit()
    found, asked = len(batch) - len(missed), len(batch)
    if not asked:
        flash("Every runbook already has its mark.", "info")
    elif not missed:
        flash(f"Got all {found}." +
              (f" {len(waiting) - asked} still to ask." if len(waiting) > asked else ""),
              "success")
    else:
        # Named, not counted. "None published a mark" sends you looking at the
        # vendors; the ones that failed are what you actually need.
        names = ", ".join(missed[:5]) + ("..." if len(missed) > 5 else "")
        flash(f"Got {found} of {asked}. Nothing found for {names}. "
              "Upload one on the runbook.", "warning" if found else "error")
    return redirect(url_for("playbooks.playbooks_index"))


# No create route. A playbook is written by the session that set the vendor
# up, through the guidance door (suggest_update, kind playbook), and adjusted
# the same way; the form here only edits what a session already filed.
@playbooks_bp.route("/<slug>")
@login_required
def playbook_detail(slug):
    playbook = Playbook.query.filter_by(slug=slug).first()
    if playbook is None:
        abort(404)
    return render_template("pm/playbooks/detail.html", playbook=playbook)


@playbooks_bp.route("/<slug>/edit", methods=["GET", "POST"])
@login_required
def playbook_edit(slug):
    playbook = Playbook.query.filter_by(slug=slug).first()
    if playbook is None:
        abort(404)

    if request.method == "POST":
        error = _apply_form(playbook)
        if error:
            flash(error, "error")
            return render_template("pm/playbooks/form.html", playbook=playbook,
                                   providers=_providers(), categories=Playbook.CATEGORIES, editing=True)
        db.session.commit()
        flash(f"{playbook.display_name} playbook saved.", "success")
        return redirect(url_for("playbooks.playbook_detail", slug=playbook.slug))

    return render_template("pm/playbooks/form.html", playbook=playbook,
                           providers=_providers(), categories=Playbook.CATEGORIES, editing=True)


# No delete route, deliberately. A playbook is the written record of how a
# vendor gets set up and it outlives every project that used it, so there is
# nothing that wants deleting one and a hidden endpoint is still an endpoint.
# Taking the button away and leaving the route would only mean the next person
# to read the file puts the button back.
