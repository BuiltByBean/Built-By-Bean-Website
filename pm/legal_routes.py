"""The Legal library's pages (issue #42): a sibling of Best Practices, never inside it.

  /admin/legal                 the library: every entry, filtered in place by product, status, topic and words
  /admin/legal/gaps            per product: the gaps, the lawyer items and the laws that moved
  /admin/legal/sources         every official document the library rests on, with its copy and its checks
  /admin/legal/sources/<key>/copy   the board's stored copy of one (the proof)
  /admin/legal/checks          the re-check runs, and the press that starts one
  /admin/legal/<slug>          one entry

Michael, 2026-11-07: kept apart from Best Practices "because it needs extra care and
attention". Entries arrive through the door (legal_door_routes, file_legal); the only
thing typed here is Michael's call on an entry's status, which is his to make. Every
page carries the disclaimer: nothing in the library is legal advice.
"""
from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory,
                   url_for)
from flask_login import current_user, login_required

import legal_library
from models import (LEGAL_STATUS_LABELS, LEGAL_STATUSES, LegalCheck, LegalEntry, LegalSource, db)

legal_bp = Blueprint("legal", __name__, url_prefix="/admin/legal")

TOPIC_LABELS = {
    "email": "Email", "push": "Push notifications", "texting": "Texting", "billing": "Charging customers",
    "renewal": "Renewal and cancellation", "prices": "Price changes", "late-payments": "Late payments",
    "collections": "Collections", "refunds": "Refunds and credits", "sales-tax": "Sales tax",
    "taxes": "Taxes and records", "personal-data": "Personal data", "breach": "Breach notice",
    "data-requests": "Exports and deletion", "deletion": "Deletion after cancellation", "e-sign": "E-signing",
    "contracts": "The contract itself", "disputes": "Disputes and venue", "marketing": "The site's claims",
    "minors": "Minors", "copyright": "Copyright and user content", "accessibility": "Accessibility",
    "phone-app": "The phone app", "money": "Money that moves through the product", "ai": "AI",
    "security": "Security", "formation": "The company",
}


@legal_bp.app_template_global("legal_counts")
def legal_counts():
    return legal_library.counts()


@legal_bp.app_template_global("legal_disclaimer")
def legal_disclaimer():
    return legal_library.DISCLAIMER


def _back(default):
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return default


@legal_bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip()
    product = (request.args.get("product") or "all").strip()
    topic = (request.args.get("topic") or "all").strip()
    if status not in LEGAL_STATUSES:
        status = "all"
    entries = (LegalEntry.query.filter_by(is_active=True)
               .order_by(LegalEntry.product, LegalEntry.topic, LegalEntry.title).all())
    products = sorted({e.product for e in entries if e.product})
    topics = sorted({e.topic for e in entries if e.topic})
    if product not in products:
        product = "all"
    if topic not in topics:
        topic = "all"
    rows = []
    for e in entries:
        search = " ".join([e.title, e.slug, e.topic, e.jurisdiction, e.laws_md or "", e.requires_md or "",
                           e.decision_md or "", e.notes_md or "", e.lawyer_question or "", e.issues or "",
                           " ".join(t.app_name for t in e.touches)]).lower()
        rows.append({"e": e, "search": search})
    return render_template(
        "pm/legal/index.html", rows=rows, q=q, status=status, product=product, topic=topic,
        topic_labels=TOPIC_LABELS, status_labels=LEGAL_STATUS_LABELS, total=len(entries),
        status_options=[("all", "Every status")] + [(k, v) for k, v in LEGAL_STATUS_LABELS.items()],
        product_options=[("all", "Every product")] + [(p, p) for p in products],
        topic_options=[("all", "Every topic")] + [(t, TOPIC_LABELS.get(t, t)) for t in topics])


@legal_bp.route("/gaps")
@login_required
def gaps():
    return render_template("pm/legal/gaps.html", groups=legal_library.gaps_by_product())


@legal_bp.route("/sources")
@login_required
def sources():
    rows = LegalSource.query.order_by(LegalSource.jurisdiction, LegalSource.key).all()
    return render_template("pm/legal/sources.html", sources=rows,
                           copies={s.id: bool(legal_library.copy_path(s)) for s in rows})


@legal_bp.route("/sources/<key>/copy")
@login_required
def source_copy(key):
    source = LegalSource.query.filter_by(key=key).first() or abort(404)
    path = legal_library.copy_path(source)
    if not path:
        abort(404)
    # The copy is another site's document. A PDF opens; an HTML page is handed
    # over as a file, never rendered on the board's origin, and nothing in it
    # may load or run.
    is_pdf = source.copy_file.lower().endswith(".pdf")
    resp = send_from_directory(legal_library.copy_folder(), source.copy_file, as_attachment=not is_pdf,
                               max_age=0)
    resp.headers["Content-Security-Policy"] = "default-src 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@legal_bp.route("/checks")
@login_required
def checks():
    runs = LegalCheck.query.order_by(LegalCheck.id.desc()).limit(30).all()
    return render_template("pm/legal/checks.html", runs=runs)


@legal_bp.route("/checks/run", methods=["POST"])
@login_required
def run_check():
    run_id = legal_library.start_recheck(current_app._get_current_object(), by=current_user.username or "board")
    flash(f"Re-check {run_id} started. Every source is fetched again and compared with its copy.", "success")
    return redirect(url_for("legal.checks"))


@legal_bp.route("/<slug>")
@login_required
def entry(slug):
    e = LegalEntry.query.filter_by(slug=slug, is_active=True).first() or abort(404)
    return render_template("pm/legal/entry.html", e=e, topic_labels=TOPIC_LABELS,
                           status_labels=LEGAL_STATUS_LABELS, statuses=LEGAL_STATUSES,
                           copies={lk.source.id: bool(legal_library.copy_path(lk.source)) for lk in e.links})


@legal_bp.route("/<slug>/status", methods=["POST"])
@login_required
def set_status(slug):
    """Michael's call on an entry: backed, a gap, the lawyer's, watch, or does
    not apply. The reason goes on the entry's notes with his name and the day."""
    from datetime import datetime, timezone
    e = LegalEntry.query.filter_by(slug=slug, is_active=True).first() or abort(404)
    status = (request.form.get("status") or "").strip()
    if status not in LEGAL_STATUSES:
        abort(400)
    reason = (request.form.get("reason") or "").strip()
    was = e.status
    e.status = status
    if status != was or reason:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        line = f"\n\n{current_user.first_name or current_user.username}, {stamp}: {LEGAL_STATUS_LABELS[status]}" \
               + (f". {reason}" if reason else ".")
        e.notes_md = (e.notes_md or "").rstrip() + line
    db.session.commit()
    flash(f"Marked {LEGAL_STATUS_LABELS[status].lower()}.", "success")
    return redirect(_back(url_for("legal.entry", slug=slug)))
