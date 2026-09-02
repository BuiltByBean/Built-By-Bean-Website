"""Vendor runbooks: the tile grid, the runbook, and editing one.

Addressed by slug rather than id, because these get linked to from notes and
from each other, and `/admin/playbooks/twilio` survives a reseed while
`/9` does not. Delete is the one exception: it takes an id, because a delete
posted against a name is the request most likely to be aimed at the wrong row
after somebody renames one.
"""
import re

import markdown
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort,
)
from flask_login import login_required
from markupsafe import Markup

from models import db, Playbook, ServiceProvider

playbooks_bp = Blueprint("playbooks", __name__, url_prefix="/admin/playbooks")


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

    return render_template("pm/playbooks/index.html",
                           playbooks=playbooks, groups=groups)


# Declared before the slug rule. Werkzeug would sort a static rule ahead of a
# converter anyway, but a route whose correctness rests on that is one refactor
# away from /new opening a playbook called "new".
@playbooks_bp.route("/new", methods=["GET", "POST"])
@login_required
def playbook_create():
    playbook = Playbook()
    if request.method == "POST":
        error = _apply_form(playbook)
        if error:
            flash(error, "error")
            return render_template("pm/playbooks/form.html", playbook=playbook,
                                   providers=_providers(), categories=Playbook.CATEGORIES, editing=False)
        db.session.add(playbook)
        db.session.commit()
        flash(f"{playbook.display_name} playbook created.", "success")
        return redirect(url_for("playbooks.playbook_detail", slug=playbook.slug))

    return render_template("pm/playbooks/form.html", playbook=playbook,
                           providers=_providers(), categories=Playbook.CATEGORIES, editing=False)


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


@playbooks_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def playbook_delete(id):
    playbook = db.session.get(Playbook, id)
    if playbook is None:
        abort(404)
    name = playbook.display_name
    db.session.delete(playbook)
    db.session.commit()
    flash(f"{name} playbook deleted.", "success")
    return redirect(url_for("playbooks.playbooks_index"))
