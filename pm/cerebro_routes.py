"""Cerebro: every client held against the catalogue, on one screen.

Pick things from the catalogue - a product, a feature, a playbook, a rule
- and the page answers, per project, who has it and who does not, and for
a rule, who is breaking it and where. Add a second chip and the answer is
the intersection: of the sites with text messaging, which ones still use
naive UTC. That is what a batch fix starts from.

Nothing here is typed in. Products come from sales, playbooks from what
was applied to a project, features from the packages scoped for a client,
and rules from the nightly audit that runs the catalogue's scanners over
every repository. The one thing a person does on this page is tell it
which repository a project lives in, once.
"""
import json
import re

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required

import audit_repos
from models import (db, Client, Project, Product, ProductSale, Playbook,
                    ProjectPlaybook, Feature, MvpPackage, MvpPackageItem,
                    RuleAudit, RepoWatch)

cerebro_bp = Blueprint("cerebro", __name__, url_prefix="/admin/cerebro")

KINDS = ("product", "feature", "playbook", "rule")
KIND_LABELS = {"product": "Product", "feature": "Feature",
               "playbook": "Playbook", "rule": "Rule"}
VIEWS = (("all", "Everyone"), ("has", "Has everything"),
         ("missing", "Missing something"), ("breaking", "Breaking a rule"))
MAX_CHIPS = 8


def _lookup(kind, slug):
    if kind == "product":
        return Product.query.filter_by(slug=slug, is_active=True).first()
    if kind == "playbook":
        return Playbook.query.filter_by(slug=slug, is_active=True).first()
    if kind in ("feature", "rule"):
        return Feature.query.filter_by(slug=slug, kind=kind, is_active=True).first()
    return None


def _label(kind, row):
    return getattr(row, "display_name", None) or row.name


def _chips():
    """[(kind, slug, row)] from ?c=kind:slug, validated, deduplicated."""
    out, seen = [], set()
    for raw in request.args.getlist("c"):
        kind, _, slug = (raw or "").partition(":")
        if kind not in KINDS or not slug or (kind, slug) in seen:
            continue
        row = _lookup(kind, slug)
        if row is None:
            continue
        seen.add((kind, slug))
        out.append((kind, slug, row))
        if len(out) >= MAX_CHIPS:
            break
    return out


def _evidence(chips, projects):
    """Per chip, a map from project id to (has, label, href). Built with
    one query per chip rather than one per cell."""
    maps = []
    for kind, slug, row in chips:
        by_project = {}
        if kind == "product":
            sales = ProductSale.query.filter_by(product_id=row.id).all()
            for p in projects:
                hit = next((s for s in sales if s.project_id == p.id), None) or \
                      next((s for s in sales if s.client_id == p.client_id
                            and s.project_id is None), None)
                if hit:
                    when = getattr(hit, "sold_at", None) or getattr(hit, "created_at", None)
                    by_project[p.id] = (True, "sold" + (f" {when:%b %Y}" if when else ""),
                                        url_for("products.products_index"))
        elif kind == "playbook":
            applied = {a.project_id: a for a in
                       ProjectPlaybook.query.filter_by(playbook_id=row.id).all()}
            for p in projects:
                a = applied.get(p.id)
                if a:
                    by_project[p.id] = (True, "applied" + (f" {a.added_at:%b %Y}" if a.added_at else ""),
                                        url_for("pm.project_detail", id=p.id))
        elif kind == "feature":
            items = (db.session.query(MvpPackageItem, MvpPackage)
                     .join(MvpPackage, MvpPackage.id == MvpPackageItem.package_id)
                     .filter(MvpPackageItem.feature_id == row.id).all())
            for p in projects:
                hit = next(((item, pkg) for item, pkg in items if pkg.client_id == p.client_id), None)
                if hit:
                    _, pkg = hit
                    by_project[p.id] = (True, f"{pkg.name} ({pkg.status})",
                                        url_for("mvp.package_detail", id=pkg.id))
        elif kind == "rule":
            audits = {a.repo: a for a in RuleAudit.query.filter_by(rule_id=row.id).all()}
            for p in projects:
                if not p.repo:
                    by_project[p.id] = (None, "no repo linked", None)
                    continue
                a = audits.get(p.repo)
                if a is None:
                    by_project[p.id] = (None, "not audited yet", None)
                elif a.violations:
                    by_project[p.id] = (False, f"{a.violations} hit{'s' if a.violations != 1 else ''}",
                                        url_for("cerebro.audit_detail", repo=p.repo, slug=slug))
                else:
                    by_project[p.id] = (True, "clean", None)
        maps.append(by_project)
    return maps


def _rows(chips):
    projects = (Project.query.join(Client, Project.client_id == Client.id)
                .filter(Project.status != "archived")
                .order_by(Client.name, Project.name).all())
    maps = _evidence(chips, projects)
    rows = []
    for p in projects:
        cells = []
        for (kind, slug, row), by_project in zip(chips, maps):
            has, label, href = by_project.get(p.id, (False, "", None))
            if not label:
                label = "not yet" if kind != "rule" else "unchecked"
            cells.append({"kind": kind, "has": has, "label": label, "href": href})
        rows.append({
            "project": p,
            "cells": cells,
            "has_all": all(c["has"] is True for c in cells) if cells else True,
            "missing": any(c["has"] is False and c["kind"] != "rule" for c in cells),
            "breaking": any(c["has"] is False and c["kind"] == "rule" for c in cells),
        })
    return rows


def _filtered(rows, view):
    if view == "has":
        return [r for r in rows if r["has_all"]]
    if view == "missing":
        return [r for r in rows if r["missing"]]
    if view == "breaking":
        return [r for r in rows if r["breaking"]]
    return rows


def _options():
    return {
        "product": [(p.slug, p.name) for p in
                    Product.query.filter_by(is_active=True).order_by(Product.sort_order, Product.name)],
        "feature": [(f.slug, f.name) for f in
                    Feature.query.filter_by(is_active=True, kind="feature").order_by(Feature.sort_order, Feature.name)],
        "playbook": [(p.slug, p.display_name) for p in
                     Playbook.query.filter_by(is_active=True).order_by(Playbook.sort_order, Playbook.display_name)],
        "rule": [(f.slug, f.name) for f in
                 Feature.query.filter_by(is_active=True, kind="rule").order_by(Feature.sort_order, Feature.name)],
    }


def _words(text):
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) >= 4}


def _suggest(project, repos):
    """The repo whose name shares a word with the project or its client."""
    wanted = _words(project.name) | _words(project.client.name if project.client else "")
    for repo in repos:
        name = repo.split("/", 1)[-1].lower().replace("-", "").replace("_", "")
        if any(w in name for w in wanted):
            return repo
    return ""


@cerebro_bp.route("/")
@login_required
def index():
    chips = _chips()
    view = request.args.get("view") or "all"
    if view not in dict(VIEWS):
        view = "all"
    rows = _rows(chips)
    shown = _filtered(rows, view)

    rules_with_checks = (Feature.query.filter_by(kind="rule", is_active=True)
                         .filter(Feature.check_pattern.isnot(None)).all())
    health = audit_repos.health(rules_with_checks)
    health_counts = {"PASS": 0, "FAIL": 0, "NONE": 0}
    for _, status in health:
        health_counts[status] = health_counts.get(status, 0) + 1

    repos = sorted({r.repo for r in RepoWatch.query.all()}
                   | {a.repo for a in db.session.query(RuleAudit.repo).distinct()})
    unlinked = [p for p in Project.query.filter(Project.repo.is_(None))
                .filter(Project.status != "archived")
                .join(Client, Project.client_id == Client.id)
                .order_by(Client.name, Project.name).all()]
    suggestions = {p.id: _suggest(p, repos) for p in unlinked}
    last_audit = db.session.query(db.func.max(RuleAudit.checked_at)).scalar()

    def link(new_chips=None, new_view=None):
        return url_for("cerebro.index",
                       c=[f"{k}:{s}" for k, s, _ in (new_chips if new_chips is not None else chips)],
                       view=(new_view or view))

    chip_views = [{"kind": k, "slug": s, "label": _label(k, row),
                   "remove": link([c for c in chips if c[1] != s or c[0] != k])}
                  for k, s, row in chips]
    repo_options = [("", "No repository")] + [(r, r.split("/")[-1]) for r in repos]

    return render_template(
        "pm/cerebro/index.html",
        chips=chip_views, view=view, views=VIEWS, rows=shown, total=len(rows),
        repo_options=repo_options,
        options=_options(), kind_labels=KIND_LABELS, kinds=KINDS,
        health=health_counts, scanners=len(health), last_audit=last_audit,
        unlinked=unlinked, repos=repos, suggestions=suggestions,
        link=link, label=_label,
        counts={"has": sum(1 for r in rows if r["has_all"]),
                "missing": sum(1 for r in rows if r["missing"]),
                "breaking": sum(1 for r in rows if r["breaking"])})


@cerebro_bp.route("/link", methods=["POST"])
@login_required
def link_repo():
    project = db.session.get(Project, request.form.get("project_id", type=int) or 0) or abort(404)
    repo = (request.form.get("repo") or "").strip()
    project.repo = repo or None
    db.session.commit()
    flash(f"{project.name} reads from {repo}." if repo else f"{project.name} unlinked.", "success")
    nxt = request.form.get("next") or ""
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("cerebro.index"))


@cerebro_bp.route("/audit/<path:repo>/<slug>")
@login_required
def audit_detail(repo, slug):
    rule = Feature.query.filter_by(slug=slug, kind="rule").first() or abort(404)
    audit = RuleAudit.query.filter_by(repo=repo, rule_id=rule.id).first() or abort(404)
    try:
        samples = json.loads(audit.sample_json or "[]")
    except ValueError:
        samples = []
    projects = Project.query.filter_by(repo=repo).all()
    return render_template("pm/cerebro/audit.html", rule=rule, audit=audit,
                           samples=samples, repo=repo, projects=projects)
