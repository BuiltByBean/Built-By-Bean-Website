"""Every business Michael owns, and the sales tax returns each one files.

Michael, 2026-10-30: "I'm not just Built by Bean anymore. I'm EntertainHQ
also ... I need a command center for all of it." So the board keeps one row
per business with what the state knows it by, and each quarter's return is
worked out here, typed into WebFile by hand, and recorded here from the
confirmation page with the confirmation itself kept beside it.

The pages (CEO only, because a WebFile number links a tax account to
whoever's eSystems login types it):

  /admin/businesses                          every business: logo, name, start
                                             date, lifetime revenue
  /admin/businesses/<id>                     one business, its tax inside it
  /admin/businesses/new, /<id>/edit          a business, its logo, locations, hub
  /admin/taxes/sales/returns                 every period owed, every business
  /admin/taxes/sales/returns/<slug>/<y>/q<n> one return: what to type, then
                                             what was paid, and its files
  /admin/taxes/sales/guide                   how it is done, end to end

One store, two doors. A business with an app of its own (EntertainHQ) talks
to the same rows over the hub, signed with ITS secret exactly as a client's
tickets are (hub.py): the board asks the app for its sales, and the app asks
the board for its returns, records one, and puts or gets a confirmation.
Nothing is kept in two places, so a partner working in that business's admin
site sees the return Michael recorded here, and the other way round. A
WebFile number never crosses the wire: it links the tax account to an
eSystems login, which is Michael's to do.
"""
import base64
import json
import os
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user

import books_service
import hub
import sales_tax
import app_icon_service
from models import (db, AppLink, Business, BusinessDocument, BusinessLocation, Client, Invoice,
                    Project, SalesTaxFiling, SalesTaxFilingFile, SalesTaxSetting)
from pm.users_routes import ceo_required
from stripe_service import get_stripe_invoice_totals, import_invoices_from_stripe

business_bp = Blueprint("businesses", __name__)

ESYSTEMS_URL = "https://security.app.cpa.state.tx.us/"
FILE_DIR = "tax_filings"
FILE_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
              "jpeg": "image/jpeg", "webp": "image/webp"}
MAX_FILE = 10 * 1024 * 1024
HUB_SALES_PATH = "/api/hub/tax/sales"
LOGO_DIR = "business_logos"
LOGO_TYPES = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp", "svg": "svg", "gif": "gif"}
MAX_LOGO = 2 * 1024 * 1024
# How long an app's word on its lifetime sales is trusted before the
# business's page asks again, and how long it waits for the answer: a page
# Michael opened must not hang on somebody else's server.
REVENUE_FRESH_SECONDS = 3600
REVENUE_TIMEOUT = 6
# A company's own paperwork. LegalZoom hands it over as PDFs; a scan or a
# photo of a letter from the IRS is an image; an operating agreement somebody
# edited is sometimes Word.
DOC_DIR = "business_documents"
DOC_TYPES = dict(FILE_TYPES, docx="application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.document")
MAX_DOC = 20 * 1024 * 1024


@business_bp.app_template_filter("age")
def age(day, today=None):
    """How long since `day`, the way a person says it: "2 years, 9 months".

    Whole calendar months, not days divided by thirty, so a business launched
    on the 17th turns a month older on the 17th. Under a month it counts
    weeks, then days. A day still to come reads as "Not yet".
    """
    if not day:
        return ""
    today = today or date.today()
    if day > today:
        return "Not yet"
    months = (today.year - day.year) * 12 + (today.month - day.month)
    if today.day < day.day:
        months -= 1
    years, months = divmod(months, 12)
    if years or months:
        parts = []
        if years:
            parts.append(f"{years} year{'' if years == 1 else 's'}")
        if months:
            parts.append(f"{months} month{'' if months == 1 else 's'}")
        return ", ".join(parts)
    days = (today - day).days
    if days >= 7:
        weeks = days // 7
        return f"{weeks} week{'' if weeks == 1 else 's'}"
    if days:
        return f"{days} day{'' if days == 1 else 's'}"
    return "Today"


# ── Small readers ────────────────────────────────────────────

def _text(field, limit=200):
    return (request.form.get(field) or "").strip()[:limit]


def _digits(field, limit):
    return re.sub(r"\D", "", request.form.get(field) or "")[:limit]


def _webfile(field):
    """RT123456 or XT123456: letters upper, spaces and dashes gone."""
    return re.sub(r"[^A-Za-z0-9]", "", request.form.get(field) or "").upper()[:20]


def _date(field):
    raw = (request.form.get(field) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _money(raw):
    raw = (raw or "").strip().replace(",", "").replace("$", "")
    if not raw:
        return 0.0
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    for suffix in ("-llc", "-inc", "-co", "-corp", "-ltd"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
    return slug[:40] or "business"


def _unique_slug(base, business_id=None):
    slug, n = base, 2
    while True:
        other = Business.query.filter_by(slug=slug).first()
        if other is None or other.id == business_id:
            return slug
        slug = f"{base[:36]}-{n}"
        n += 1


# ── Where a return's sales come from ─────────────────────────

def _board_rows():
    """Every invoice row the ledger counts, worked out the ledger's way.

    Stripe's invoices are made rows first, as the Sales tax page does, so a
    return opened the morning it is due counts last night's invoice. The
    list is cached for five minutes; a failure leaves the ledger as it was
    rather than the page broken.
    """
    try:
        import_invoices_from_stripe(ttl=300)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Returns: Stripe import failed: {e}")
    settings = SalesTaxSetting.get()
    ledger = sales_tax.build(settings, Client.query.order_by(Client.name, Client.id).all(),
                             Invoice.query.all(), Project.query.all())
    rows = []
    for entry in ledger["clients"]:
        rows.extend(entry["invoices"])
    return rows, settings.taxable_share


def _hub_sales(business, start, end, timeout=20):
    """Ask the business's own app for its sales. (sales, None) or (None, why)."""
    if not (business.hub_base_url and business.hub_secret and business.hub_slug):
        return None, "Its app is not connected yet."
    try:
        payload = hub.fetch(business.hub_base_url, HUB_SALES_PATH,
                            {"from": start.isoformat(), "to": end.isoformat()},
                            secret=business.hub_secret, origin_slug=business.hub_slug,
                            timeout=timeout)
    except hub.DeliveryError as exc:
        note = f"{business.label} did not answer: {exc}"[:300]
        business.hub_pull_note = note
        db.session.commit()
        return None, note
    sales = []
    for s in (payload or {}).get("sales") or []:
        try:
            day = date.fromisoformat(str(s["date"])[:10])
            total = float(s["total"])
        except (KeyError, TypeError, ValueError):
            continue
        taxable = s.get("taxable")
        sales.append({"date": day, "total": total,
                      "taxable": float(taxable) if taxable is not None else None,
                      "ref": str(s.get("ref") or "")[:60], "who": str(s.get("who") or "")[:120],
                      "invoice_id": None})
    business.hub_pulled_at = datetime.now(timezone.utc)
    business.hub_pull_note = f"{len(sales)} sale{'' if len(sales) == 1 else 's'}"
    db.session.commit()
    return sales, None


def sales_between(business, start, end, board=None):
    """(sales, share, note) for one business over [start, end].

    sales is None when there is nothing to compute from (typed in, or the
    app did not answer), and note says which. `board` is _board_rows()
    already fetched, so a page listing every period asks the ledger once.
    """
    if business.sales_source == "board":
        rows, share = board if board is not None else _board_rows()
        return sales_tax.board_sales(rows, start, end), share, None
    if business.sales_source == "hub":
        sales, note = _hub_sales(business, start, end)
        return sales, business.taxable_share, note
    return None, business.taxable_share, None


def return_for(business, year, quarter, sales, share):
    start, end = sales_tax.quarter_bounds(year, quarter)
    mine = [s for s in (sales or []) if start <= s["date"] <= end]
    return sales_tax.build_return(business.location_on, mine, share, year=year, quarter=quarter)


def periods_for(business, today, board=None):
    """Every period this business has owed a return for, newest first.

    One fetch for the whole range, then each period sliced out of it, so an
    app is asked once per page rather than once per quarter.
    """
    owed = sales_tax.periods_owed(business.sales_tax_first_sale, today)
    if not owed:
        return [], None
    first_start, _ = sales_tax.quarter_bounds(*owed[0])
    sales, share, note = sales_between(business, first_start, today, board)
    out = []
    for year, quarter in reversed(owed):
        filing = business.filing_for(year, quarter)
        figures = return_for(business, year, quarter, sales, share) if sales is not None else None
        out.append({
            "year": year, "quarter": quarter,
            "code": sales_tax.period_code(year, quarter),
            "label": sales_tax.period_label(year, quarter),
            "due": sales_tax.due_date(year, quarter),
            "status": sales_tax.status_of(year, quarter, filing, today),
            "filing": filing,
            "figures": figures,
        })
    return out, note


# ── The businesses, and each one ─────────────────────────────

def lifetime_revenue(business, ask=False):
    """Everything the business has earned, or None when nothing counts it.

    "board" is the dashboard's Total Revenue, read from the same call: paid
    less its sales tax, no back-tax invoices. It shipped on 2026-11-01 as the
    board's own invoice rows while the dashboard read Stripe's cash total, and
    that evening Michael found the two did not match; then he chose revenue
    without the tax, for both. One business's takings are one number, so the
    two pages read one function. "hub" is what the
    business's own app last said, asked again only when `ask` and the answer
    is older than REVENUE_FRESH_SECONDS. "manual" has nothing to count.
    """
    # A division is never "board": the board's invoices are its parent's
    # takings, and counting them again here would show one business's money
    # on two tiles. _fill refuses it; this holds for a row written elsewhere.
    import books_service
    if business.sales_source == "board" and not business.is_division:
        return round(get_stripe_invoice_totals()["revenue"] + books_service.board_dba_income_total(), 2)
    # A DBA of the board company that earned into the bank (Personal
    # Training's checks): what it earned, which its parent's tile includes.
    if business.is_division:
        dba = books_service.dba_income_between(business, date(2000, 1, 1), date.today() + timedelta(days=1))
        if dba:
            return round(sum(a for _, a, _, _ in dba), 2)
    # A company with its own Stripe connected earns there, and the Books page
    # already reads it; the tile reads the same rows rather than asking an app.
    if business.stripe_key and not business.is_division:
        import stripe_books
        return round(sum(a for _, a, _ in stripe_books.income_between(
            business, date(2000, 1, 1), date.today() + timedelta(days=1))), 2)
    if business.sales_source == "hub":
        if ask:
            age = None
            if business.revenue_as_of:
                age = (datetime.now(timezone.utc).replace(tzinfo=None)
                       - business.revenue_as_of.replace(tzinfo=None)).total_seconds()
            if age is None or age > REVENUE_FRESH_SECONDS:
                start = business.formed_on or date(2000, 1, 1)
                sales, _note = _hub_sales(business, start, date.today(), timeout=REVENUE_TIMEOUT)
                if sales is not None:
                    business.revenue_total = round(sum(s["total"] for s in sales), 2)
                    business.revenue_as_of = datetime.now(timezone.utc)
                    db.session.commit()
        return business.revenue_total
    return None


@business_bp.route("/admin/businesses")
@ceo_required
def index():
    """Every business as a business: its logo, its name, when it started and
    what it has made. The tax is inside each one. Nothing here asks another
    server: a business whose sales come from its own app shows what that app
    last said."""
    businesses = Business.query.order_by(Business.is_active.desc(), Business.name,
                                         Business.id).all()
    # A family per company: its tile, and its DBAs hung under it on a
    # connecting line (Michael, 2026-11-02), so Data Dungeon reads as Built by
    # Bean's rather than as a company of its own that happens to sit nearby.
    def tile(b):
        return {"business": b, "revenue": lifetime_revenue(b)}

    families = [{"tile": tile(b), "dbas": [tile(d) for d in businesses if d.parent_id == b.id]}
                for b in businesses if b.parent_id is None]
    placed = {f["tile"]["business"].id for f in families} | {
        d["business"].id for f in families for d in f["dbas"]}
    # A DBA whose parent is gone stands on its own rather than vanishing.
    families += [{"tile": tile(b), "dbas": []} for b in businesses if b.id not in placed]
    return render_template("pm/businesses/index.html", families=families)


@business_bp.route("/admin/businesses/<int:id>")
@ceo_required
def detail(id):
    business = db.session.get(Business, id) or abort(404)
    if business.is_division:
        # Its tax is its parent's: no numbers, no permit, no returns here.
        return render_template(
            "pm/businesses/detail.html", business=business,
            revenue=lifetime_revenue(business, ask=True), next=None, late=0,
            esystems_url=ESYSTEMS_URL, map_counts=_map_for(business)["counts"],
            **_papers(business))
    today = date.today()
    # _board_rows brings Stripe's invoices in first, which the revenue reads too.
    board = _board_rows() if business.sales_source == "board" else None
    # The returns list does not ask the app for figures: one return page at a
    # time does that. The revenue may ask, briefly, when its answer is old.
    periods, _note = (periods_for(business, today, board) if business.sales_source != "hub"
                      else _periods_without_figures(business, today))
    urgent = next((p for p in periods if p["status"] in ("late", "due")), None)
    return render_template(
        "pm/businesses/detail.html", business=business,
        revenue=lifetime_revenue(business, ask=True),
        next=urgent or next((p for p in periods if p["status"] == "open"), None),
        late=sum(1 for p in periods if p["status"] == "late"),
        esystems_url=ESYSTEMS_URL, map_counts=_map_for(business)["counts"],
            **_papers(business))


# ── Its paperwork ────────────────────────────────────────────

def _papers(business):
    """The documents in the order KINDS lists them, and the kinds on offer."""
    order = {k: i for i, (k, _label) in enumerate(BusinessDocument.KINDS)}
    docs = sorted(business.documents, key=lambda d: (order.get(d.kind, len(order)), d.id))
    return {"documents": docs, "doc_kinds": BusinessDocument.KINDS}


def _doc_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], DOC_DIR)
    os.makedirs(path, exist_ok=True)
    return path


@business_bp.route("/admin/businesses/<int:id>/documents", methods=["POST"])
@ceo_required
def document_add(id):
    """Keep one or more papers. Each gets the kind picked; the title is kept
    only for a single file, because one title on five files says nothing."""
    business = db.session.get(Business, id) or abort(404)
    kind = _text("kind", 20)
    kind = kind if kind in dict(BusinessDocument.KINDS) else "other"
    uploads = [u for u in request.files.getlist("document") if u and u.filename]
    title = _text("title", 200) if len(uploads) == 1 else ""
    kept, refused = 0, []
    for upload in uploads:
        name = os.path.basename(upload.filename)
        ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
        data = upload.read(MAX_DOC + 1)
        if ext not in DOC_TYPES or not data or len(data) > MAX_DOC:
            refused.append(name)
            continue
        stored = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(_doc_folder(), stored), "wb") as fh:
            fh.write(data)
        db.session.add(BusinessDocument(
            business_id=business.id, kind=kind, title=title, stored_name=stored,
            original_name=name[:300] or stored, content_type=DOC_TYPES[ext], size=len(data)))
        kept += 1
    db.session.commit()
    if kept:
        flash(f"{kept} document{'' if kept == 1 else 's'} kept.", "success")
    if refused:
        flash("Not kept (PDF, image or Word, under 20 MB): " + ", ".join(refused), "error")
    if not uploads:
        flash("Pick a file first.", "info")
    return redirect(url_for("businesses.detail", id=business.id) + "#documents")


@business_bp.route("/admin/businesses/documents/<int:doc_id>")
@ceo_required
def document_open(doc_id):
    doc = db.session.get(BusinessDocument, doc_id) or abort(404)
    if not os.path.exists(os.path.join(_doc_folder(), doc.stored_name)):
        flash(f"{doc.original_name} is not on the server any more.", "error")
        return redirect(url_for("businesses.detail", id=doc.business_id) + "#documents")
    resp = send_from_directory(_doc_folder(), doc.stored_name, as_attachment=False,
                               download_name=doc.original_name, mimetype=doc.content_type)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@business_bp.route("/admin/businesses/documents/<int:doc_id>/delete", methods=["POST"])
@ceo_required
def document_delete(doc_id):
    doc = db.session.get(BusinessDocument, doc_id) or abort(404)
    business_id = doc.business_id
    path = os.path.join(_doc_folder(), doc.stored_name)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(doc)
    db.session.commit()
    flash("Document removed.", "success")
    return redirect(url_for("businesses.detail", id=business_id) + "#documents")


def _logo_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], LOGO_DIR)
    os.makedirs(path, exist_ok=True)
    return path


@business_bp.route("/admin/businesses/<int:id>/logo")
@ceo_required
def logo(id):
    business = db.session.get(Business, id) or abort(404)
    if not business.logo_file:
        abort(404)
    resp = send_from_directory(_logo_folder(), business.logo_file, max_age=86400)
    # An uploaded SVG is a document that can carry script, as on My Apps.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _drop_logo_file(business):
    if business.logo_file:
        try:
            os.remove(os.path.join(_logo_folder(), business.logo_file))
        except OSError:
            pass  # a missing file is already the state we wanted
    business.logo_file = None


def _take_logo(business):
    """The logo choice from the form. Returns an error string or None.

    An uploaded image wins and clears an app's icon; choosing an app's icon
    removes an uploaded image; "none" clears both. Absent from the form means
    the form had no logo section, so nothing changes.
    """
    upload = request.files.get("logo_upload")
    if upload and upload.filename:
        ext = LOGO_TYPES.get(os.path.splitext(upload.filename)[1].lstrip(".").lower())
        if not ext:
            return "That file type cannot be used as a logo."
        data = upload.read(MAX_LOGO + 1)
        if len(data) > MAX_LOGO:
            return "That image is larger than 2MB."
        if len(data) < 64:
            return "That file is empty."
        _drop_logo_file(business)
        business.logo_file = app_icon_service.store(data, ext, _logo_folder())
        business.logo_app_id = None
        return None
    choice = request.form.get("logo_choice")
    if choice is None or choice == "upload":
        return None
    if choice == "none":
        _drop_logo_file(business)
        business.logo_app_id = None
        return None
    app = db.session.get(AppLink, int(choice)) if choice.isdigit() else None
    if app is None or not app.icon_file:
        return "That app has no icon to use."
    _drop_logo_file(business)
    business.logo_app_id = app.id
    return None


def _logo_apps():
    return AppLink.query.filter(AppLink.icon_file.isnot(None), AppLink.icon_file != "") \
        .order_by(AppLink.name, AppLink.id).all()


def _periods_without_figures(business, today):
    out = []
    for year, quarter in reversed(sales_tax.periods_owed(business.sales_tax_first_sale, today)):
        filing = business.filing_for(year, quarter)
        out.append({"year": year, "quarter": quarter,
                    "code": sales_tax.period_code(year, quarter),
                    "label": sales_tax.period_label(year, quarter),
                    "due": sales_tax.due_date(year, quarter),
                    "status": sales_tax.status_of(year, quarter, filing, today),
                    "filing": filing, "figures": None})
    return out, None


def _parent_choices(business):
    """The companies this one could be a division of: any company of its own
    other than itself. One level only, so a division is never offered."""
    q = Business.query.filter(Business.parent_id.is_(None))
    if business.id:
        q = q.filter(Business.id != business.id)
    return q.order_by(Business.name, Business.id).all()


def _take_parent(business):
    """The "Part of" choice. Returns an error string or None.

    The tax numbers of a business made a division are left exactly as they
    were rather than cleared: picking the wrong company in this one control
    must not cost Built by Bean its taxpayer number. A division is simply
    never asked for them, and the returns pages leave it out.
    """
    raw = request.form.get("parent_id")
    if raw is None:
        return None  # a form without the control changes nothing
    if not raw:
        business.parent_id = None
        return None
    parent = db.session.get(Business, int(raw)) if raw.isdigit() else None
    if parent is None or parent.id == business.id or parent.parent_id is not None:
        return "That cannot be the company it is part of."
    if business.id and Business.query.filter_by(parent_id=business.id).first():
        return f"{business.label} has divisions of its own, so it cannot be one."
    business.parent_id = parent.id
    if business.sales_source == "board":
        business.sales_source = "manual"
    return None


def _fill(business):
    """Copy the form onto a business. Returns an error string or None."""
    name = _text("name", 200)
    if not name:
        return "A business needs its name."
    business.name = name
    business.short_name = _text("short_name", 80)
    business.slug = _unique_slug(_slugify(_text("slug", 40) or business.short_name or name),
                                 business.id)
    business.texas_taxpayer_number = _digits("texas_taxpayer_number", 11)
    business.sos_file_number = _digits("sos_file_number", 20)
    business.conceived_on = _date("conceived_on")
    business.formed_on = _date("formed_on")
    business.launched_on = _date("launched_on")
    if business.conceived_on and business.launched_on and business.conceived_on > business.launched_on:
        return "The idea has to come before the launch."
    business.franchise_tax_webfile = _webfile("franchise_tax_webfile")
    business.sales_tax_webfile = _webfile("sales_tax_webfile")
    business.sales_tax_registered_on = _date("sales_tax_registered_on")
    business.sales_tax_first_sale = _date("sales_tax_first_sale")
    freq = _text("sales_tax_frequency", 12)
    business.sales_tax_frequency = freq if freq in dict(Business.FREQUENCIES) else "quarterly"
    share = _money(request.form.get("taxable_share"))
    business.taxable_share = min(100.0, max(0.0, share)) if share is not None else 80.0
    business.naics_code = _digits("naics_code", 10)
    source = _text("sales_source", 12)
    business.sales_source = source if source in dict(Business.SALES_SOURCES) else "manual"
    business.admin_url = _text("admin_url", 300)
    hub_slug = _slugify(_text("hub_slug", 40)) if _text("hub_slug", 40) else None
    if hub_slug and Business.query.filter(Business.hub_slug == hub_slug,
                                          Business.id != business.id).first():
        return f"Another business already answers to {hub_slug}."
    business.hub_slug = hub_slug
    business.hub_base_url = _text("hub_base_url", 300).rstrip("/")
    business.notes = (request.form.get("notes") or "").strip()
    business.is_active = request.form.get("is_active") == "1"
    return _take_parent(business)


@business_bp.route("/admin/businesses/new", methods=["GET", "POST"])
@ceo_required
def new():
    business = Business(sales_tax_frequency="quarterly", taxable_share=80.0,
                        sales_source="manual", is_active=True)
    if request.method == "POST":
        error = _fill(business) or _take_logo(business)
        if error:
            db.session.rollback()
            flash(error, "error")
        else:
            db.session.add(business)
            db.session.commit()
            flash(f"{business.label} is on the board. Add where it sells from next.", "success")
            return redirect(url_for("businesses.edit", id=business.id))
    return render_template("pm/businesses/form.html", business=business, editing=False,
                           logo_apps=_logo_apps(), parents=_parent_choices(business))


@business_bp.route("/admin/businesses/<int:id>/edit", methods=["GET", "POST"])
@ceo_required
def edit(id):
    business = db.session.get(Business, id) or abort(404)
    if request.method == "POST":
        error = _fill(business) or _take_logo(business)
        if error:
            db.session.rollback()
            flash(error, "error")
        else:
            db.session.commit()
            flash("Saved.", "success")
            return redirect(url_for("businesses.detail", id=business.id))
    return render_template("pm/businesses/form.html", business=business, editing=True,
                           logo_apps=_logo_apps(), parents=_parent_choices(business))


@business_bp.route("/admin/businesses/<int:id>/secret", methods=["POST"])
@ceo_required
def new_secret(id):
    """A fresh hub secret. The app's copy has to be changed to match, so the
    old one stops working the moment this is pressed."""
    business = db.session.get(Business, id) or abort(404)
    business.hub_secret = secrets.token_urlsafe(32)
    db.session.commit()
    flash("New secret made. Put it in the app's settings before it next asks.", "success")
    return redirect(url_for("businesses.edit", id=business.id) + "#hub")


def _fill_location(loc):
    label = _text("label", 100)
    if not label:
        return "A location needs a name, like the town."
    loc.label = label
    loc.webfile_number = _digits("webfile_number", 5)
    loc.address = _text("address", 300)
    loc.county = _text("county", 60)
    rate = _money(request.form.get("local_rate"))
    loc.local_rate = min(10.0, max(0.0, rate)) if rate is not None else 2.0
    loc.opened_on = _date("opened_on")
    loc.closed_on = _date("closed_on")
    if loc.opened_on and loc.closed_on and loc.closed_on < loc.opened_on:
        return "A location cannot close before it opened."
    loc.closure_filed = request.form.get("closure_filed") == "1"
    return None


@business_bp.route("/admin/businesses/<int:id>/locations", methods=["POST"])
@ceo_required
def location_add(id):
    business = db.session.get(Business, id) or abort(404)
    loc = BusinessLocation(business_id=business.id)
    error = _fill_location(loc)
    if error:
        flash(error, "error")
    else:
        db.session.add(loc)
        db.session.commit()
        flash(f"{loc.label} added.", "success")
    return redirect(url_for("businesses.edit", id=business.id) + "#locations")


@business_bp.route("/admin/businesses/<int:id>/locations/<int:loc_id>", methods=["POST"])
@ceo_required
def location_save(id, loc_id):
    loc = db.session.get(BusinessLocation, loc_id)
    if loc is None or loc.business_id != id:
        abort(404)
    error = _fill_location(loc)
    if error:
        db.session.rollback()
        flash(error, "error")
    else:
        db.session.commit()
        flash(f"{loc.label} saved.", "success")
    return redirect(url_for("businesses.edit", id=id) + "#locations")


@business_bp.route("/admin/businesses/<int:id>/locations/<int:loc_id>/delete", methods=["POST"])
@ceo_required
def location_delete(id, loc_id):
    loc = db.session.get(BusinessLocation, loc_id)
    if loc is None or loc.business_id != id:
        abort(404)
    label = loc.label
    db.session.delete(loc)
    db.session.commit()
    flash(f"{label} removed.", "success")
    return redirect(url_for("businesses.edit", id=id) + "#locations")


# ── Returns ──────────────────────────────────────────────────

@business_bp.route("/admin/taxes/sales/returns")
@ceo_required
def returns_index():
    today = date.today()
    board = None
    groups = []
    # Divisions are left out: their sales are their parent's, on its return.
    for b in Business.query.filter_by(is_active=True, parent_id=None).order_by(
            Business.name, Business.id):
        if b.sales_source == "board" and board is None:
            board = _board_rows()
        periods, note = periods_for(b, today, board)
        groups.append({"business": b, "periods": periods, "note": note})
    return render_template("pm/taxes/returns.html", groups=groups, today=today)


def _business_by_slug(slug):
    return Business.query.filter_by(slug=slug).first() or abort(404)


@business_bp.route("/admin/taxes/sales/returns/<slug>/<int:year>/q<int:quarter>")
@ceo_required
def return_page(slug, year, quarter):
    if quarter not in (1, 2, 3, 4):
        abort(404)
    business = _business_by_slug(slug)
    today = date.today()
    start, end = sales_tax.quarter_bounds(year, quarter)
    sales, share, note = sales_between(business, start, end)
    figures = return_for(business, year, quarter, sales, share) if sales is not None else None
    filing = business.filing_for(year, quarter)
    due = sales_tax.due_date(year, quarter)
    charges = sales_tax.charges_if_paid_on(figures["tax"], due, today) if figures else None
    # WebFile asks for a line for every location the permit lists in the
    # period, sales or not, until the state has been told one closed. Those
    # with nothing take the "No Sales or Purchases" tick instead of numbers.
    selling = {l["location"].id for l in figures["lines"]} if figures else set()
    quiet = [loc for loc in business.locations
             if loc.id not in selling
             and (loc.opened_on is None or loc.opened_on <= end)
             and (loc.closed_on is None or loc.closed_on >= start or not loc.closure_filed)]
    return render_template(
        "pm/taxes/return.html",
        business=business, year=year, quarter=quarter, figures=figures, note=note, quiet=quiet,
        filing=filing, due=due, charges=charges, today=today,
        code=sales_tax.period_code(year, quarter),
        label=sales_tax.period_label(year, quarter),
        status=sales_tax.status_of(year, quarter, filing, today),
        start=start, end=end, esystems_url=ESYSTEMS_URL,
        methods=SalesTaxFiling.METHODS,
    )


def _files_dir():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], FILE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def store_file(filing, name, data, content_type=None):
    """Keep one confirmation. Returns the row, or None if it is not a kind
    of file a confirmation comes as, or is too big."""
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if ext not in FILE_TYPES or not data or len(data) > MAX_FILE:
        return None
    stored = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(_files_dir(), stored), "wb") as fh:
        fh.write(data)
    row = SalesTaxFilingFile(filing_id=filing.id, stored_name=stored,
                             original_name=os.path.basename(name)[:300] or stored,
                             content_type=FILE_TYPES[ext], size=len(data))
    db.session.add(row)
    return row


def _store_uploads(filing):
    kept, refused = 0, []
    for upload in request.files.getlist("confirmation"):
        if not upload or not upload.filename:
            continue
        data = upload.read(MAX_FILE + 1)
        if store_file(filing, upload.filename, data):
            kept += 1
        else:
            refused.append(upload.filename)
    return kept, refused


def apply_filing(filing, values, who):
    """Write a recorded return. `values` holds the form's (or the hub's)
    figures, already read; anything missing keeps what the row has."""
    for key in ("reference_number", "payment_reference", "trace_number"):
        if key in values:
            setattr(filing, key, re.sub(r"\s", "", str(values[key] or ""))[:40])
    method = values.get("payment_method")
    if method in dict(SalesTaxFiling.METHODS):
        filing.payment_method = method
    for key in ("total_sales", "taxable_sales", "tax_due", "penalty", "late_filing_penalty",
                "interest", "discount", "processing_fee", "amount_paid"):
        if key in values and values[key] is not None:
            setattr(filing, key, round(float(values[key]), 2))
    if not values.get("amount_paid"):
        filing.amount_paid = round((filing.tax_due or 0) + (filing.penalty or 0)
                                   + (filing.late_filing_penalty or 0) + (filing.interest or 0)
                                   - (filing.discount or 0), 2)
    if values.get("filed_at"):
        filing.filed_at = values["filed_at"]
    if "locations" in values and isinstance(values["locations"], list):
        filing.locations_json = json.dumps(values["locations"])
    if "notes" in values:
        filing.notes = str(values["notes"] or "").strip()
    filing.recorded_by = who[:80]


def _form_values():
    values = {k: request.form.get(k, "") for k in
              ("reference_number", "payment_reference", "trace_number", "payment_method", "notes")}
    bad = []
    for key in ("total_sales", "taxable_sales", "tax_due", "penalty", "late_filing_penalty",
                "interest", "discount", "processing_fee", "amount_paid"):
        amount = _money(request.form.get(key))
        if amount is None:
            bad.append(key.replace("_", " "))
        values[key] = amount
    filed_on = _date("filed_on") or date.today()
    raw_time = (request.form.get("filed_time") or "").strip()
    try:
        at = time.fromisoformat(raw_time) if raw_time else time(0, 0)
    except ValueError:
        at = time(0, 0)
    values["filed_at"] = datetime.combine(filed_on, at)
    lines = []
    numbers = request.form.getlist("loc_number")
    for i, number in enumerate(numbers):
        def pick(name):
            vals = request.form.getlist(name)
            return vals[i] if i < len(vals) else ""
        lines.append({"number": number, "label": pick("loc_label"),
                      "total_sales": _money(pick("loc_total")) or 0,
                      "taxable_sales": _money(pick("loc_taxable")) or 0,
                      "state_tax": _money(pick("loc_state")) or 0,
                      "local_tax": _money(pick("loc_local")) or 0})
    values["locations"] = lines
    return values, bad


@business_bp.route("/admin/taxes/sales/returns/<slug>/<int:year>/q<int:quarter>/record",
                   methods=["POST"])
@ceo_required
def return_record(slug, year, quarter):
    business = _business_by_slug(slug)
    values, bad = _form_values()
    back = url_for("businesses.return_page", slug=slug, year=year, quarter=quarter)
    if bad:
        flash("Not a dollar amount: " + ", ".join(bad) + ".", "error")
        return redirect(back)
    if not values["reference_number"].strip():
        flash("The reference number from the confirmation page is the proof it was filed.",
              "error")
        return redirect(back)
    filing = business.filing_for(year, quarter)
    if filing is None:
        filing = SalesTaxFiling(business_id=business.id, year=year, quarter=quarter)
        db.session.add(filing)
    apply_filing(filing, values, getattr(current_user, "username", "") or "")
    db.session.flush()
    books_service.settle_sales_tax(filing)
    kept, refused = _store_uploads(filing)
    db.session.commit()
    flash(f"{sales_tax.period_label(year, quarter)} recorded"
          + (f" with {kept} file{'' if kept == 1 else 's'}" if kept else "") + ".", "success")
    if refused:
        flash("Not kept (PDF or image, under 10 MB): " + ", ".join(refused), "error")
    return redirect(back)


@business_bp.route("/admin/taxes/sales/filings/<int:id>/files", methods=["POST"])
@ceo_required
def filing_upload(id):
    filing = db.session.get(SalesTaxFiling, id) or abort(404)
    kept, refused = _store_uploads(filing)
    db.session.commit()
    if kept:
        flash(f"{kept} file{'' if kept == 1 else 's'} kept.", "success")
    if refused:
        flash("Not kept (PDF or image, under 10 MB): " + ", ".join(refused), "error")
    if not kept and not refused:
        flash("Pick the confirmation first.", "info")
    return redirect(url_for("businesses.return_page", slug=filing.business.slug,
                            year=filing.year, quarter=filing.quarter) + "#files")


@business_bp.route("/admin/taxes/sales/files/<int:id>")
@ceo_required
def file_download(id):
    row = db.session.get(SalesTaxFilingFile, id) or abort(404)
    path = os.path.join(_files_dir(), row.stored_name)
    if not os.path.exists(path):
        flash(f"{row.original_name} is not on the server any more.", "error")
        filing = row.filing
        return redirect(url_for("businesses.return_page", slug=filing.business.slug,
                                year=filing.year, quarter=filing.quarter))
    return send_from_directory(_files_dir(), row.stored_name, as_attachment=False,
                               download_name=row.original_name, mimetype=row.content_type)


@business_bp.route("/admin/taxes/sales/files/<int:id>/delete", methods=["POST"])
@ceo_required
def file_delete(id):
    row = db.session.get(SalesTaxFilingFile, id) or abort(404)
    filing = row.filing
    path = os.path.join(_files_dir(), row.stored_name)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(row)
    db.session.commit()
    flash("File removed.", "success")
    return redirect(url_for("businesses.return_page", slug=filing.business.slug,
                            year=filing.year, quarter=filing.quarter) + "#files")


@business_bp.route("/admin/taxes/sales/filings/<int:id>/delete", methods=["POST"])
@ceo_required
def filing_delete(id):
    """Take a record off the board, for one written against the wrong period.
    It does not touch the state: a filed return stays filed."""
    filing = db.session.get(SalesTaxFiling, id) or abort(404)
    slug, year, quarter = filing.business.slug, filing.year, filing.quarter
    for row in filing.files:
        path = os.path.join(_files_dir(), row.stored_name)
        if os.path.exists(path):
            os.remove(path)
    books_service.unsettle_sales_tax(filing)
    db.session.delete(filing)
    db.session.commit()
    flash("Record removed. The return itself is still filed with the state.", "success")
    return redirect(url_for("businesses.return_page", slug=slug, year=year, quarter=quarter))


@business_bp.route("/admin/taxes/sales/filings/<int:id>/record.pdf")
@ceo_required
def filing_pdf(id):
    """The board's own record of a return as a PDF, for the file drawer.

    Not a substitute for WebFile's confirmation page, which is the state's
    word; this is ours, and it exists so a return is never on the board with
    nothing to print.
    """
    filing = db.session.get(SalesTaxFiling, id) or abort(404)
    pdf = filing_record_pdf(filing)
    name = f"{filing.business.slug}-sales-tax-{filing.year}-q{filing.quarter}.pdf"
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


def filing_record_pdf(filing):
    from fpdf import FPDF

    def clean(text):
        # The core fonts are Latin-1: the period label's en dash is not.
        return (str(text).replace("\u2013", "-").replace("\u2014", "-")
                .encode("latin-1", "replace").decode("latin-1"))

    b = filing.business
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, clean(f"Texas sales and use tax return, {sales_tax.period_label(filing.year, filing.quarter)}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, clean(f"{b.name}  |  Taxpayer {b.texas_taxpayer_number}  |  Period {filing.period_code}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def row(label, value):
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(70, 7, clean(label))
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, clean(value), new_x="LMARGIN", new_y="NEXT")

    filed = filing.filed_at.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") if filing.filed_at else ""
    row("Filed", filed)
    row("Reference number", filing.reference_number or "")
    row("Payment reference", filing.payment_reference or "")
    row("Trace number", filing.trace_number or "")
    row("Paid by", dict(SalesTaxFiling.METHODS).get(filing.payment_method, filing.payment_method or ""))
    pdf.ln(3)
    money = lambda v: f"${(v or 0):,.2f}"  # noqa: E731
    row("Total Texas sales", money(filing.total_sales))
    row("Taxable sales", money(filing.taxable_sales))
    row("Tax", money(filing.tax_due))
    if filing.penalty:
        row("Penalty", money(filing.penalty))
    if filing.late_filing_penalty:
        row("Late filing penalty", money(filing.late_filing_penalty))
    if filing.interest:
        row("Interest", money(filing.interest))
    if filing.discount:
        row("Timely filing discount", "-" + money(filing.discount))
    row("Paid to the state", money(filing.amount_paid))
    if filing.processing_fee:
        row("Card processing fee", money(filing.processing_fee))
        row("Charged in all", money(filing.total_charged))

    lines = filing.location_rows
    if lines:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 10)
        widths = (20, 60, 35, 35, 35)
        for w, h in zip(widths, ("Loc #", "Location", "Total sales", "Taxable", "Tax")):
            pdf.cell(w, 7, h, border="B")
        pdf.ln()
        pdf.set_font("Helvetica", "", 10)
        for line in lines:
            tax = (line.get("state_tax") or 0) + (line.get("local_tax") or 0)
            for w, v in zip(widths, (line.get("number", ""), line.get("label", ""),
                                     f"{line.get('total_sales', 0):,.0f}",
                                     f"{line.get('taxable_sales', 0):,.0f}", money(tax))):
                pdf.cell(w, 7, clean(v))
            pdf.ln()
    if filing.notes:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, clean(filing.notes))
    return bytes(pdf.output())


@business_bp.route("/admin/taxes/sales/guide")
@ceo_required
def guide():
    businesses = Business.query.filter_by(is_active=True, parent_id=None).order_by(
        Business.name).all()
    return render_template("pm/taxes/guide.html", businesses=businesses,
                           esystems_url=ESYSTEMS_URL)


# ── The hub: a business's own app, talking to the same rows ──
#
# Signed with the business's own secret, exactly as a client's tickets are.
# Unknown origin and bad signature get the same answer, so a caller learns
# nothing about which businesses exist.

def _hub_business():
    slug = (request.headers.get(hub.ORIGIN_HEADER) or "").strip()
    if not slug:
        return None, (jsonify({"error": "no origin"}), 400)
    business = Business.query.filter_by(hub_slug=slug).first()
    secret = business.hub_secret if business else ""
    reason = hub.verify(secret, request.get_data(),
                        request.headers.get(hub.TIMESTAMP_HEADER),
                        request.headers.get(hub.SIGNATURE_HEADER))
    if business is None or reason:
        current_app.logger.warning("hub tax: refused %r: %s", slug, reason or "no such business")
        return None, (jsonify({"error": "unauthorised"}), 401)
    return business, None


def _hub_json():
    try:
        return json.loads(request.get_data() or b"{}") or {}
    except ValueError:
        return {}


def _filing_out(filing):
    return {
        "year": filing.year, "quarter": filing.quarter, "code": filing.period_code,
        "filed_at": filing.filed_at.isoformat() if filing.filed_at else None,
        "reference_number": filing.reference_number, "payment_reference": filing.payment_reference,
        "trace_number": filing.trace_number, "payment_method": filing.payment_method,
        "total_sales": filing.total_sales, "taxable_sales": filing.taxable_sales,
        "tax_due": filing.tax_due, "penalty": filing.penalty,
        "late_filing_penalty": filing.late_filing_penalty, "interest": filing.interest,
        "discount": filing.discount, "amount_paid": filing.amount_paid,
        "processing_fee": filing.processing_fee, "locations": filing.location_rows,
        "notes": filing.notes, "recorded_by": filing.recorded_by,
        "files": [{"id": f.id, "name": f.original_name, "content_type": f.content_type,
                   "size": f.size, "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None}
                  for f in filing.files],
    }


def _figures_out(figures):
    if not figures:
        return None
    return {"total_sales": figures["total_sales"], "taxable_sales": figures["taxable_sales"],
            "state_tax": figures["state_tax"], "local_tax": figures["local_tax"],
            "tax": figures["tax"], "unplaced": len(figures["unplaced"]),
            "lines": [{"number": l["number"], "label": l["label"],
                       "total_sales": l["total_sales"], "taxable_sales": l["taxable_sales"],
                       "state_tax": l["state_tax"], "local_tax": l["local_tax"]}
                      for l in figures["lines"]]}


@business_bp.route("/api/hub/tax/returns", methods=["POST"])
def hub_returns():
    """Every period this business owes, with its record if filed.

    The app may send its own sales ({"sales": [{date, total, taxable}]}) and
    gets the figures worked out against the locations kept here; without
    them a period carries no figures. The board never calls back into the
    app from inside this request, because two apps each waiting on the other
    is how a page hangs.
    """
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    today = date.today()
    sales = None
    if isinstance(data.get("sales"), list):
        sales = []
        for s in data["sales"]:
            try:
                sales.append({"date": date.fromisoformat(str(s["date"])[:10]),
                              "total": float(s["total"]),
                              "taxable": (float(s["taxable"]) if s.get("taxable") is not None
                                          else None)})
            except (KeyError, TypeError, ValueError):
                continue
    periods = []
    for year, quarter in reversed(sales_tax.periods_owed(business.sales_tax_first_sale, today)):
        filing = business.filing_for(year, quarter)
        figures = (return_for(business, year, quarter, sales, business.taxable_share)
                   if sales is not None else None)
        periods.append({
            "year": year, "quarter": quarter, "code": sales_tax.period_code(year, quarter),
            "label": sales_tax.period_label(year, quarter),
            "due": sales_tax.due_date(year, quarter).isoformat(),
            "status": sales_tax.status_of(year, quarter, filing, today),
            "figures": _figures_out(figures),
            "filing": _filing_out(filing) if filing else None,
        })
    return jsonify({
        "business": {"name": business.name, "texas_taxpayer_number": business.texas_taxpayer_number,
                     "frequency": business.sales_tax_frequency,
                     "first_sale": (business.sales_tax_first_sale.isoformat()
                                    if business.sales_tax_first_sale else None),
                     "registered_on": (business.sales_tax_registered_on.isoformat()
                                       if business.sales_tax_registered_on else None),
                     "locations": [{"number": l.webfile_number, "label": l.label,
                                    "address": l.address, "local_rate": l.local_rate,
                                    "opened_on": l.opened_on.isoformat() if l.opened_on else None,
                                    "closed_on": l.closed_on.isoformat() if l.closed_on else None}
                                   for l in business.locations]},
        "periods": periods,
    })


def _period_from(data):
    try:
        year, quarter = int(data.get("year")), int(data.get("quarter"))
    except (TypeError, ValueError):
        return None
    return (year, quarter) if 2000 <= year <= 2100 and quarter in (1, 2, 3, 4) else None


@business_bp.route("/api/hub/tax/filings", methods=["POST"])
def hub_record_filing():
    """Record (or correct) a return from the business's own admin site."""
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    period = _period_from(data)
    if not period:
        return jsonify({"error": "year and quarter, please"}), 400
    if not str(data.get("reference_number") or "").strip():
        return jsonify({"error": "reference_number is the proof it was filed"}), 400
    values = {k: data[k] for k in ("reference_number", "payment_reference", "trace_number",
                                   "payment_method", "notes", "locations") if k in data}
    for key in ("total_sales", "taxable_sales", "tax_due", "penalty", "late_filing_penalty",
                "interest", "discount", "processing_fee", "amount_paid"):
        if key in data:
            try:
                values[key] = round(float(data[key] or 0), 2)
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} is not an amount"}), 400
    if data.get("filed_at"):
        try:
            values["filed_at"] = datetime.fromisoformat(str(data["filed_at"])[:19])
        except ValueError:
            return jsonify({"error": "filed_at is not a date and time"}), 400
    filing = business.filing_for(*period)
    if filing is None:
        # Blank rather than the column's default: the app may not know how it
        # was paid, and a guessed "electronic check" is a fact nobody stated.
        filing = SalesTaxFiling(business_id=business.id, year=period[0], quarter=period[1],
                                payment_method="")
        db.session.add(filing)
    who = str(data.get("recorded_by") or business.hub_slug)
    apply_filing(filing, values, f"{who} via {business.hub_slug}")
    db.session.flush()
    books_service.settle_sales_tax(filing)
    db.session.commit()
    return jsonify({"ok": True, "filing": _filing_out(filing)})


@business_bp.route("/api/hub/tax/filings/undo", methods=["POST"])
def hub_undo_filing():
    """Take back a return the app itself recorded, for a Mark filed pressed in
    error over there.

    Only its own: a return recorded here, or one with a confirmation kept
    beside it, is refused, because an app's Undo must not wipe Michael's
    record of what the state was paid.
    """
    business, refused = _hub_business()
    if refused:
        return refused
    period = _period_from(_hub_json())
    filing = business.filing_for(*period) if period else None
    if filing is None:
        return jsonify({"ok": True, "removed": False})
    if not (filing.recorded_by or "").endswith(f"via {business.hub_slug}") or filing.files:
        return jsonify({"error": "recorded in the command center; take it back there"}), 409
    books_service.unsettle_sales_tax(filing)
    db.session.delete(filing)
    db.session.commit()
    return jsonify({"ok": True, "removed": True})


@business_bp.route("/api/hub/tax/files/put", methods=["POST"])
def hub_put_file():
    """Keep a confirmation with an already recorded return. Base64 in the
    JSON body, because the signature covers the body's exact bytes."""
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    period = _period_from(data)
    filing = business.filing_for(*period) if period else None
    if filing is None:
        return jsonify({"error": "record the return before its confirmation"}), 404
    try:
        raw = base64.b64decode(str(data.get("data") or ""), validate=True)
    except (ValueError, TypeError):
        return jsonify({"error": "data is not base64"}), 400
    row = store_file(filing, str(data.get("name") or "confirmation.pdf"), raw)
    if row is None:
        return jsonify({"error": "a PDF or image under 10 MB"}), 400
    db.session.commit()
    return jsonify({"ok": True, "file": {"id": row.id, "name": row.original_name,
                                         "size": row.size}})


@business_bp.route("/api/hub/tax/files/get", methods=["POST"])
def hub_get_file():
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    try:
        row = db.session.get(SalesTaxFilingFile, int(data.get("id")))
    except (TypeError, ValueError):
        row = None
    # Only its own: another business's confirmation is somebody else's tax.
    if row is None or row.filing.business_id != business.id:
        return jsonify({"error": "no such file"}), 404
    path = os.path.join(_files_dir(), row.stored_name)
    if not os.path.exists(path):
        return jsonify({"error": "the file is not on the server any more"}), 410
    with open(path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return jsonify({"name": row.original_name, "content_type": row.content_type,
                    "data": encoded})


# ── The map: everything that makes one business run ─────────
#
# business_map.layout does the drawing; this fetches, edits and fetches
# marks. The map page is the whole content area with the window never
# scrolling, so it reads like the overlay Michael asked for and still has an
# address, a back button and a place on the Businesses tile. Every kind of
# thing on it is a BusinessNode and every line a BusinessEdge with its why.

import business_map  # noqa: E402
from models import BusinessEdge, BusinessNeed, BusinessNeedLink, BusinessNode, Playbook  # noqa: E402

# The folder is the one the first version used for a service's own mark, so
# every file fetched before the nodes table existed is still where its row
# says it is.
NODE_ICON_DIR = "service_icons"
MARK_BATCH = 8


def _map_for(business):
    needs = BusinessNeed.query.order_by(BusinessNeed.sort_order, BusinessNeed.id).all()
    return business_map.layout(business, list(business.nodes), list(business.edges), needs,
                               BusinessNeedLink.query.all())


@business_bp.route("/admin/businesses/<int:id>/map")
@ceo_required
def map_page(id):
    business = db.session.get(Business, id) or abort(404)
    return render_template("pm/businesses/map.html", business=business, map=_map_for(business))


def _map_edit_context(business):
    needs = BusinessNeed.query.order_by(BusinessNeed.sort_order, BusinessNeed.id).all()
    playbooks = Playbook.query.filter_by(is_active=True).order_by(Playbook.display_name).all()
    order = {k: i for i, (k, _l) in enumerate(BusinessNode.KINDS)}
    nodes = sorted(business.nodes, key=lambda n: (order.get(n.kind, 9), n.sort_order, n.display_name.lower()))
    by_kind = {k: [n for n in nodes if n.kind == k] for k, _l in BusinessNode.KINDS}
    layer_label = dict((k, l) for k, l, _c in business_map_layers())
    want = request.args.get("need", "")
    return {
        "business": business, "needs": needs, "playbooks": playbooks, "nodes": nodes, "by_kind": by_kind,
        "kinds": BusinessNode.KINDS, "statuses": BusinessNode.STATUSES, "surface_kinds": BusinessNode.SURFACE_KINDS,
        "edges": list(business.edges),
        "need_options": [("", "No particular need")] + [(str(n.id), f"{n.name} ({layer_label.get(n.layer, n.layer)})")
                                                        for n in needs],
        "playbook_options": [("", "No playbook")] + [(str(p.id), p.display_name) for p in playbooks],
        "node_options": [(str(n.id), f"{n.display_name} ({n.kind_label})") for n in nodes],
        "preselect_kind": "service" if want else request.args.get("kind", "service"),
        "preselect_need": want,
        "preselect_id": next((str(n.id) for n in needs if n.slug == want), ""),
        "marks_waiting": sum(1 for n in business.nodes if n.wants_mark),
    }


def business_map_layers():
    """The business playbook's layers, for the need picker's labels."""
    return (
        ("legal", "Legal", ""), ("money", "Money", ""), ("infrastructure", "Infrastructure", ""),
        ("product", "Product", ""), ("operations", "Operations", ""), ("comms", "Comms", ""),
        ("growth", "Growth", ""), ("intelligence", "Intelligence", ""),
    )


@business_bp.route("/admin/businesses/<int:id>/map/edit")
@ceo_required
def map_edit(id):
    business = db.session.get(Business, id) or abort(404)
    return render_template("pm/businesses/map_edit.html", **_map_edit_context(business))


def _fill_node(node):
    """Copy the form onto a node. Returns an error string or None."""
    kind = _text("kind", 12) or node.kind or "service"
    node.kind = kind if kind in dict(BusinessNode.KINDS) else "service"
    node.name = _text("name", 120)
    if node.kind == "service":
        need_id = request.form.get("need_id", type=int)
        node.need_id = need_id if need_id and db.session.get(BusinessNeed, need_id) else None
        pb_id = request.form.get("playbook_id", type=int)
        node.playbook_id = pb_id if pb_id and db.session.get(Playbook, pb_id) else None
        if node.playbook_id is None and node.name:
            # Typed "Mercury" with no playbook picked, and there is one: it is
            # that playbook's, which is what the map's red mark is asking for.
            want = re.sub(r"[^a-z0-9]+", "-", node.name.lower()).strip("-")
            match = next((p for p in Playbook.query.all()
                          if p.slug == want or re.sub(r"[^a-z0-9]+", "-", (p.display_name or "").lower()).strip("-") == want), None)
            node.playbook_id = match.id if match else None
        if not node.name and node.playbook_id is None:
            return "A service with no playbook needs a name."
    else:
        node.need_id = None
        node.playbook_id = None
        if not node.name:
            return "It needs a name."
    node.role = _text("role", 400)
    allowed = dict(BusinessNode.STATUSES.get(node.kind, ()))
    status = _text("status", 12)
    node.status = status if status in allowed else (next(iter(allowed), "") if allowed else "")
    node.url = _text("url", 300)
    sk = _text("surface_kind", 12)
    node.surface_kind = sk if node.kind == "surface" and sk in dict(BusinessNode.SURFACE_KINDS) else ""
    node.notes = (request.form.get("notes") or "").strip()
    return None


# ── Marks ────────────────────────────────────────────────────

def _node_icon_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], NODE_ICON_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def fetch_node_mark(node):
    """Fetch and keep this node's mark off its URL. Returns whether one came.

    Best effort, as the runbooks' and My Apps' fetches are: a site that is
    down leaves the tile on its initials. Stamped either way, so a URL with
    no icon is not asked again on every press.
    """
    url = (node.url or "").strip()
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    got = None
    try:
        got = app_icon_service.fetch(url)
    except Exception:
        got = None
    if not got:
        host = url.split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
        try:
            got = app_icon_service.fetch_by_domain(host) if "." in host else None
        except Exception:
            got = None
    node.icon_fetched_at = datetime.now(timezone.utc)
    if not got:
        return False
    data, ext, source = got
    old = node.icon_file
    node.icon_file = app_icon_service.store(data, ext, _node_icon_folder())
    node.icon_source = source[:500] if source else None
    if old and old != node.icon_file:
        try:
            os.remove(os.path.join(_node_icon_folder(), old))
        except OSError:
            pass
    return True


@business_bp.route("/admin/businesses/<int:id>/map/nodes/<int:nid>/icon")
@ceo_required
def node_icon(id, nid):
    node = db.session.get(BusinessNode, nid) or abort(404)
    if node.business_id != id or not node.icon_file:
        abort(404)
    resp = send_from_directory(_node_icon_folder(), node.icon_file, max_age=86400)
    # Fetched from somebody else's server, and an SVG can carry script.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@business_bp.route("/admin/businesses/<int:id>/map/marks", methods=["POST"])
@ceo_required
def marks_fetch(id):
    """Go and get the marks still showing initials. On a press, never on render."""
    business = db.session.get(Business, id) or abort(404)
    waiting = [n for n in business.nodes if n.wants_mark]
    batch = waiting[:MARK_BATCH]
    missed = [n.display_name for n in batch if not fetch_node_mark(n)]
    db.session.commit()
    found, asked = len(batch) - len(missed), len(batch)
    if not asked:
        flash("Everything with a URL already has its mark.", "info")
    elif not missed:
        flash(f"Got all {found}." + (f" {len(waiting) - asked} still to ask." if len(waiting) > asked else ""),
              "success")
    else:
        flash(f"Got {found} of {asked}. Nothing found for " + ", ".join(missed[:5]) + ".",
              "warning" if found else "error")
    return redirect(url_for("businesses.map_edit", id=business.id))


# ── Nodes ────────────────────────────────────────────────────

@business_bp.route("/admin/businesses/<int:id>/map/nodes", methods=["POST"])
@ceo_required
def node_add(id):
    business = db.session.get(Business, id) or abort(404)
    node = BusinessNode(business_id=business.id)
    error = _fill_node(node)
    if error:
        flash(error, "error")
        return redirect(url_for("businesses.map_edit", id=business.id) + "#add")
    node.sort_order = max([n.sort_order for n in business.nodes if n.kind == node.kind] or [0]) + 10
    db.session.add(node)
    db.session.flush()
    if node.wants_mark:
        fetch_node_mark(node)
    db.session.commit()
    flash(f"{node.display_name} is on the map.", "success")
    return redirect(url_for("businesses.map_edit", id=business.id) + f"#node-{node.id}")


@business_bp.route("/admin/businesses/<int:id>/map/nodes/<int:nid>", methods=["POST"])
@ceo_required
def node_save(id, nid):
    node = db.session.get(BusinessNode, nid) or abort(404)
    if node.business_id != id:
        abort(404)
    error = _fill_node(node)
    if error:
        db.session.rollback()
        flash(error, "error")
    else:
        if node.wants_mark:
            fetch_node_mark(node)
        db.session.commit()
        flash("Saved.", "success")
    return redirect(url_for("businesses.map_edit", id=id) + f"#node-{nid}")


@business_bp.route("/admin/businesses/<int:id>/map/nodes/<int:nid>/delete", methods=["POST"])
@ceo_required
def node_delete(id, nid):
    node = db.session.get(BusinessNode, nid) or abort(404)
    if node.business_id != id:
        abort(404)
    name = node.display_name
    # Its lines go with it, by hand: SQLite does not enforce the cascade.
    for edge in list(BusinessEdge.query.filter(
            (BusinessEdge.from_node_id == nid) | (BusinessEdge.to_node_id == nid))):
        db.session.delete(edge)
    db.session.delete(node)
    db.session.commit()
    flash(f"{name} is off the map.", "success")
    return redirect(url_for("businesses.map_edit", id=id))


# ── Edges ────────────────────────────────────────────────────

@business_bp.route("/admin/businesses/<int:id>/map/edges", methods=["POST"])
@ceo_required
def edge_add(id):
    business = db.session.get(Business, id) or abort(404)
    a = db.session.get(BusinessNode, request.form.get("from_node_id", type=int) or 0)
    b = db.session.get(BusinessNode, request.form.get("to_node_id", type=int) or 0)
    if not a or not b or a.business_id != id or b.business_id != id or a.id == b.id:
        flash("Pick two different things on this map.", "error")
        return redirect(url_for("businesses.map_edit", id=id) + "#edges")
    existing = BusinessEdge.query.filter_by(business_id=id).filter(
        ((BusinessEdge.from_node_id == a.id) & (BusinessEdge.to_node_id == b.id))
        | ((BusinessEdge.from_node_id == b.id) & (BusinessEdge.to_node_id == a.id))).first()
    edge = existing or BusinessEdge(business_id=id, from_node_id=a.id, to_node_id=b.id)
    edge.why = _text("why", 300)
    db.session.add(edge)
    db.session.commit()
    flash(f"{a.display_name} and {b.display_name} are connected.", "success")
    return redirect(url_for("businesses.map_edit", id=id) + "#edges")


@business_bp.route("/admin/businesses/<int:id>/map/edges/<int:eid>/delete", methods=["POST"])
@ceo_required
def edge_delete(id, eid):
    edge = db.session.get(BusinessEdge, eid) or abort(404)
    if edge.business_id != id:
        abort(404)
    db.session.delete(edge)
    db.session.commit()
    flash("Line removed.", "success")
    return redirect(url_for("businesses.map_edit", id=id) + "#edges")
