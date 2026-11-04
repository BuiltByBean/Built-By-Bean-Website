"""Books: each company's year, its months, its owners and its receipts.

Michael, 2026-11-03: "we're effectively building out our own bookkeeping
system". The board keeps the books for every company it knows about, and
this is where they are read:

  /admin/books/                    every company: the year so far, its months
                                   (closed or not, and what is left to do),
                                   its owners, and the mailboxes read for
                                   receipts
  /admin/books/<id>/year/<y>       the year-end report the accountant works
                                   from, grouped the way the return groups it,
                                   with a CSV of every line
  /admin/books/<id>/month/<y-m>    the monthly close: every bank line sorted,
                                   every expense with its receipt, the bank's
                                   balance agreeing, then one press
  /admin/books/receipts            receipts that matched no charge yet
  /api/hub/books                   the same figures for a company's own app,
                                   signed with its hub secret: EntertainHQ's
                                   admin shows its partners these numbers read
                                   only, so there is one set of books, not two

Every figure on all of them comes from books_service, so no two can differ.
"""
import csv
import io
import json
import os
from datetime import date, datetime, timezone

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)

import books_service
import receipts_service
from forms import EXPENSE_CATEGORY_CHOICES
from models import (db, Business, BusinessOwner, MonthClose, Receipt, ReceiptMailbox)
from pm.users_routes import ceo_required

books_bp = Blueprint("books", __name__)
BOOKS_START = date(2026, 4, 1)


def _companies():
    return Business.query.filter_by(parent_id=None, is_active=True).order_by(Business.id).all()


def _month(value):
    try:
        y, m = (int(x) for x in value.split("-"))
        return date(y, m, 1)
    except (ValueError, AttributeError):
        abort(404)


def _months(through):
    out, m = [], BOOKS_START
    while m <= through:
        out.append(m)
        m = books_service.month_bounds(m)[1]
    return out


def month_status(business, month):
    """What is left before a month can close."""
    start, end = books_service.month_bounds(month)
    summary = books_service.summarize(business, start, end)
    closed = MonthClose.query.filter_by(business_id=business.id, month=start).first()
    return {"month": start, "summary": summary, "closed": closed,
            "unsorted": summary["unsorted"], "no_receipt": len(summary["no_receipt"]),
            "finished": end <= date.today()}


@books_bp.route("/admin/books/")
@ceo_required
def index():
    """One company at a time, or the connections, never everything on one
    long scroll (Michael, 2026-11-03: "this book's page is just one long
    scroll. It's hard to follow"). `tab` is a company's id or "connections";
    only the tab shown is worked out."""
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    all_companies = _companies()
    tab = request.args.get("tab") or (str(all_companies[0].id) if all_companies else "connections")
    tabs = [(str(b.id), b.short_name or b.name) for b in all_companies] + [("connections", "Connections")]
    if tab not in {t for t, _ in tabs}:
        tab = tabs[0][0]
    companies = []
    for b in all_companies:
        if str(b.id) != tab:
            continue
        ystart, yend = date(year, 1, 1), date(year + 1, 1, 1)
        months = [month_status(b, m) for m in _months(min(today, date(year, 12, 1)))
                  if m.year == year]
        companies.append({"business": b, "year": books_service.summarize(b, ystart, yend),
                          "months": list(reversed(months))})
    mailboxes = ReceiptMailbox.query.order_by(ReceiptMailbox.id).all()
    from models import BankConnection, BankTransaction
    sources = (BankConnection.query.filter_by(provider="statement")
               .order_by(BankConnection.id).all())
    for src in sources:
        src.line_count = BankTransaction.query.filter_by(connection_id=src.id).count()
        last = (db.session.query(db.func.max(BankTransaction.occurred_on))
                .filter(BankTransaction.connection_id == src.id).scalar())
        src.through = last
    waiting = Receipt.query.filter_by(status="unmatched").count()
    return render_template("pm/books/index.html", companies=companies, year=year,
                           mailboxes=mailboxes, waiting=waiting, today=today,
                           reading=receipts_service.reading, sources=sources,
                           tab=tab, tabs=tabs,
                           business_options=[(b.id, b.name) for b in _companies()])


@books_bp.route("/admin/books/<int:id>/year/<int:year>")
@ceo_required
def year_report(id, year):
    business = db.session.get(Business, id) or abort(404)
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    # Schedule C numbers only for a company known to have exactly one owner;
    # with none on file it may be a partnership, as EntertainHQ is.
    single = len(business.owners) == 1
    return render_template("pm/books/year.html", business=business, year=year, s=s,
                           single=single, category_labels=dict(EXPENSE_CATEGORY_CHOICES))


@books_bp.route("/admin/books/<int:id>/year/<int:year>.csv")
@ceo_required
def year_csv(id, year):
    business = db.session.get(Business, id) or abort(404)
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1))
    labels = dict(EXPENSE_CATEGORY_CHOICES)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Kind", "Date", "Description", "Category", "Tax line", "Amount", "Company",
                "Client", "Project", "Receipt", "Source"])
    dba_rows = {(w_, a, lbl): name for w_, a, lbl, name in
                books_service.dba_income_between(business, date(year, 1, 1), date(year + 1, 1, 1))}
    for when, amount, label in s["income"]:
        dba = dba_rows.get((when, amount, label))
        w.writerow(["Income", when.isoformat(), label, "", "", f"{amount:.2f}",
                    f"{business.name} d/b/a {dba}" if dba else business.name, "", "", "",
                    "bank" if dba or business.sales_source != "board" else "invoices"])
    for e in s["expenses"]:
        line, number = books_service.tax_line(e.category)
        w.writerow(["Expense", e.date.isoformat(),
                    " ".join(p for p in (e.description, e.sales_tax_note and f"({e.sales_tax_note})") if p),
                    labels.get(e.category, e.category or ""), f"{line} ({number})",
                    f"{e.amount:.2f}", e.business.name if e.business else "",
                    e.client.name if e.client else "", e.project.name if e.project else "",
                    "yes" if e.receipt_filename else "no", books_service.source_of(e)])
    for who, money in s["owner_money"].items():
        if money["in"]:
            w.writerow(["Owner put in", "", who, "", "", f"{money['in']:.2f}", business.name])
        if money["out"]:
            w.writerow(["Owner took out", "", who, "", "", f"{money['out']:.2f}", business.name])
    name = f"{business.short_name or business.name} books {year}.csv".replace("/", "-")
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@books_bp.route("/admin/books/<int:id>/month/<ym>")
@ceo_required
def month_page(id, ym):
    business = db.session.get(Business, id) or abort(404)
    status = month_status(business, _month(ym))
    return render_template("pm/books/month.html", business=business, st=status,
                           s=status["summary"], bank=books_service.bank_check(business, date.today()),
                           category_labels=dict(EXPENSE_CATEGORY_CHOICES))


@books_bp.route("/admin/books/<int:id>/month/<ym>/close", methods=["POST"])
@ceo_required
def close_month(id, ym):
    business = db.session.get(Business, id) or abort(404)
    start = _month(ym)
    st = month_status(business, start)
    if not st["finished"]:
        flash("A month can close once it has ended.", "warning")
        return redirect(url_for("books.month_page", id=id, ym=ym))
    row = MonthClose.query.filter_by(business_id=id, month=start).first() or MonthClose(
        business_id=id, month=start)
    row.expenses_total = st["summary"]["expense_total"]
    row.income_total = st["summary"]["income_total"]
    row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.note = (request.form.get("note") or "")[:300]
    db.session.add(row)
    db.session.commit()
    flash(f"{start:%B %Y} is closed.", "success")
    return redirect(url_for("books.month_page", id=id, ym=ym))


@books_bp.route("/admin/books/<int:id>/month/<ym>/reopen", methods=["POST"])
@ceo_required
def reopen_month(id, ym):
    row = MonthClose.query.filter_by(business_id=id, month=_month(ym)).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Reopened.", "success")
    return redirect(url_for("books.month_page", id=id, ym=ym))


@books_bp.route("/admin/books/owners", methods=["POST"])
@ceo_required
def owner_add():
    business = db.session.get(Business, request.form.get("business_id", type=int) or 0) or abort(404)
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        flash("Name the owner.", "warning")
        return redirect(url_for("books.index", tab=business.id))
    share = request.form.get("share_percent", type=float)
    db.session.add(BusinessOwner(business_id=business.id, name=name, share_percent=share))
    db.session.commit()
    total = sum(o.share_percent or 0 for o in business.owners)
    flash(f"{name} added." + ("" if abs(total - 100) < 0.01 else f" Shares add up to {total:g}%."),
          "success")
    return redirect(url_for("books.index", tab=business.id))


@books_bp.route("/admin/books/owners/<int:oid>/delete", methods=["POST"])
@ceo_required
def owner_delete(oid):
    owner = db.session.get(BusinessOwner, oid) or abort(404)
    bid = owner.business_id
    db.session.delete(owner)
    db.session.commit()
    flash("Removed.", "success")
    return redirect(url_for("books.index", tab=bid))


@books_bp.route("/admin/books/mailboxes", methods=["POST"])
@ceo_required
def mailbox_add():
    address = (request.form.get("address") or "").strip().lower()[:200]
    password = (request.form.get("password") or "").replace(" ", "").strip()
    if "@" not in address or not password:
        flash("Give the address and its app password.", "warning")
        return redirect(url_for("books.index", tab="connections"))
    box = ReceiptMailbox.query.filter_by(address=address).first() or ReceiptMailbox(address=address)
    box.password = password
    box.business_id = request.form.get("business_id", type=int) or None
    box.imap_host = (request.form.get("imap_host") or "imap.gmail.com").strip()[:120]
    try:
        box.read_from = date.fromisoformat(request.form.get("read_from") or "")
    except ValueError:
        box.read_from = BOOKS_START
    box.last_ok = None
    db.session.add(box)
    db.session.commit()
    _read(box)
    return redirect(url_for("books.index", tab="connections"))


def _read(box):
    """Start reading a mailbox in the background and say so."""
    if receipts_service.sync_in_background(current_app._get_current_object(), box.id):
        flash(f"Reading {box.address}. Receipts appear here as it goes.", "success")
    else:
        flash(f"Already reading {box.address}.", "success")


@books_bp.route("/admin/books/mailboxes/<int:mid>/sync", methods=["POST"])
@ceo_required
def mailbox_sync(mid):
    box = db.session.get(ReceiptMailbox, mid) or abort(404)
    _read(box)
    return redirect(url_for("books.index", tab="connections"))


@books_bp.route("/admin/books/mailboxes/<int:mid>/delete", methods=["POST"])
@ceo_required
def mailbox_delete(mid):
    box = db.session.get(ReceiptMailbox, mid) or abort(404)
    db.session.delete(box)
    db.session.commit()
    flash("Disconnected. Receipts already attached stay on their expenses.", "success")
    return redirect(url_for("books.index", tab="connections"))


@books_bp.route("/admin/books/receipts")
@ceo_required
def receipts():
    """Two lists: the expenses still without a receipt (Missing, first,
    because that is the job), and the mail receipts that matched no charge."""
    from models import Expense
    import receipts_service
    view = request.args.get("view", "missing")
    rows = (Receipt.query.filter_by(status="unmatched")
            .order_by(Receipt.received_on.desc(), Receipt.id.desc()).limit(300).all())
    missing = (Expense.query.filter(Expense.receipt_filename.is_(None), Expense.time_entry_id.is_(None),
                                    Expense.amount > 0, Expense.date >= receipts_service.BOOKS_START)
               .order_by(Expense.date.desc(), Expense.id.desc()).all())
    statement_only = (Expense.query.filter(
        Expense.receipt_original_name.like(receipts_service.STATEMENT_PROOF + "%"),
        Expense.time_entry_id.is_(None))
        .order_by(Expense.date.desc(), Expense.id.desc()).all())
    names = {b.id: (b.short_name or b.name) for b in Business.query.all()}
    return render_template("pm/books/receipts.html", rows=rows, missing=missing, view=view,
                           statement_only=statement_only, business_names=names)


@books_bp.route("/admin/books/receipts/<int:rid>/file")
@ceo_required
def receipt_file(rid):
    r = db.session.get(Receipt, rid) or abort(404)
    if not r.filename:
        abort(404)
    resp = send_from_directory(os.path.join(current_app.config["UPLOAD_FOLDER"], "receipts"),
                               r.filename, download_name=r.original_name or r.filename)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # A receipt saved as HTML is somebody else's markup: it never runs here.
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src * data:; style-src 'unsafe-inline'"
    return resp


@books_bp.route("/admin/books/receipts/<int:rid>/ignore", methods=["POST"])
@ceo_required
def receipt_ignore(rid):
    r = db.session.get(Receipt, rid) or abort(404)
    r.status = "ignored"
    db.session.commit()
    flash("Set aside.", "success")
    return redirect(url_for("books.receipts"))


# ── The hub: a company's own app reads its books ─────────


@books_bp.route("/api/hub/books", methods=["POST"])
def hub_books():
    """A company's books for its own app to show, read only.

    Signed with the company's hub secret like every hub call. The app may
    send its own sales ({"sales": [{date, total, ref}]}) and they are the
    income; without them the income is what its bank received. The board
    never calls back into the app from inside this request.
    """
    from pm.business_routes import _hub_business, _hub_json
    business, refused = _hub_business()
    if refused:
        return refused
    data = _hub_json()
    year = int(data.get("year") or date.today().year)
    sales = None
    if isinstance(data.get("sales"), list):
        sales = []
        for s in data["sales"]:
            try:
                sales.append({"date": date.fromisoformat(str(s["date"])[:10]),
                              "total": float(s["total"]), "ref": str(s.get("ref") or "")[:120]})
            except (KeyError, TypeError, ValueError):
                continue
    s = books_service.summarize(business, date(year, 1, 1), date(year + 1, 1, 1), sales)
    labels = dict(EXPENSE_CATEGORY_CHOICES)
    closes = {m.month.strftime("%Y-%m"): m.closed_at.isoformat() if m.closed_at else None
              for m in MonthClose.query.filter_by(business_id=business.id).all()}
    return jsonify({
        "business": business.name, "year": year,
        "income_total": s["income_total"], "expense_total": s["expense_total"], "net": s["net"],
        "by_month": [{"month": k, **v, "closed_at": closes.get(k)} for k, v in s["by_month"].items()],
        "by_line": [{"label": r["label"], "total": r["total"], "count": r["count"]}
                    for r in s["tax_lines"]],
        "expenses": [{"date": e.date.isoformat(), "description": e.description or "",
                      "category": labels.get(e.category, e.category or ""), "amount": e.amount,
                      "receipt": bool(e.receipt_filename)} for e in s["expenses"]],
        "income": [{"date": d.isoformat(), "amount": a, "description": l} for d, a, l in s["income"]],
        "owners": [{"name": o.name, "share_percent": o.share_percent,
                    "put_in": s["owner_money"].get(o.name, {}).get("in", 0.0),
                    "took_out": s["owner_money"].get(o.name, {}).get("out", 0.0)}
                   for o in business.owners],
        "unsorted_bank_lines": s["unsorted"],
    })


# ── A company's own Stripe ────────────────────────────────


@books_bp.route("/admin/books/<int:id>/stripe", methods=["POST"])
@ceo_required
def stripe_connect(id):
    import stripe_books
    business = db.session.get(Business, id) or abort(404)
    back = url_for("businesses.detail", id=id) + "#stripe"
    key = (request.form.get("key") or "").strip()
    if not key:
        flash("Paste the restricted key from Stripe.", "warning")
        return redirect(back)
    try:
        stripe_books.check_key(key)
    except stripe_books.StripeKeyError as err:
        flash(str(err), "warning")
        return redirect(back)
    business.stripe_key = key
    business.stripe_ok = None
    business.stripe_synced_at = None
    db.session.commit()
    result = stripe_books.sync(business)
    flash(result.get("error") or f"Connected. {business.stripe_note}.",
          "warning" if result.get("error") else "success")
    return redirect(back)


@books_bp.route("/admin/books/<int:id>/stripe/sync", methods=["POST"])
@ceo_required
def stripe_sync(id):
    import stripe_books
    business = db.session.get(Business, id) or abort(404)
    if not business.stripe_key:
        abort(404)
    result = stripe_books.sync(business)
    flash(result.get("error") or f"{business.stripe_note}.",
          "warning" if result.get("error") else "success")
    return redirect(url_for("businesses.detail", id=id) + "#stripe")


@books_bp.route("/admin/books/<int:id>/stripe/disconnect", methods=["POST"])
@ceo_required
def stripe_disconnect(id):
    business = db.session.get(Business, id) or abort(404)
    business.stripe_key = None
    business.stripe_ok = None
    business.stripe_note = ""
    db.session.commit()
    flash("Disconnected. What it read stays in the books.", "success")
    return redirect(url_for("businesses.detail", id=id) + "#stripe")


# ── Cards and accounts with no feed: their statements ─────


@books_bp.route("/admin/books/statements", methods=["POST"])
@ceo_required
def statement_source_add():
    from models import BankConnection
    business = db.session.get(Business, request.form.get("business_id", type=int) or 0) or abort(404)
    label = (request.form.get("label") or "").strip()[:120]
    if not label:
        flash("Name the card or account.", "warning")
        return redirect(url_for("books.index", tab="connections"))
    kind = "personal" if request.form.get("kind") == "personal" else "business"
    conn = BankConnection(business_id=business.id, provider="statement", label=label, token="",
                          kind=kind, owner_name=(request.form.get("owner_name") or "").strip()[:120],
                          charges_positive=request.form.get("charges_positive") == "1")
    db.session.add(conn)
    db.session.commit()
    flash(f"{label} added. Upload its statements below.", "success")
    return redirect(url_for("books.index", tab="connections"))


@books_bp.route("/admin/books/statements/<int:cid>/upload", methods=["POST"])
@ceo_required
def statement_upload(cid):
    import statements
    from models import BankConnection
    conn = db.session.get(BankConnection, cid) or abort(404)
    if conn.provider != "statement":
        abort(404)
    files = [f for f in request.files.getlist("statement") if f and f.filename]
    if not files:
        flash("Choose the statement file you downloaded.", "warning")
        return redirect(url_for("books.index", tab="connections"))
    total = {"read": 0, "new": 0}
    for f in files:
        raw = f.read(5 * 1024 * 1024)
        try:
            rows = statements.parse(raw.decode("utf-8-sig", "replace"), conn.charges_positive)
        except statements.StatementError as err:
            flash(f"{f.filename}: {err}", "warning")
            return redirect(url_for("books.index", tab="connections"))
        got = statements.import_rows(conn, rows)
        total["read"] += got["read"]
        total["new"] += got["new"]
    # The charges just arrived, so go and look for their receipts now rather
    # than tonight. On its own thread, because a big statement outlives the page.
    import receipts_service
    from models import ReceiptMailbox
    for box in ReceiptMailbox.query.all():
        receipts_service.sync_in_background(current_app._get_current_object(), box.id)
    waiting = got.get("review", 0)
    flash(f"{conn.label}: {total['new']:,} new line{'' if total['new'] == 1 else 's'} of "
          f"{total['read']:,} read, {waiting:,} to sort.", "success")
    return redirect(url_for("bank.review") if waiting else url_for("books.index", tab="connections"))


@books_bp.route("/admin/books/statements/<int:cid>/delete", methods=["POST"])
@ceo_required
def statement_source_delete(cid):
    from models import BankConnection
    conn = db.session.get(BankConnection, cid) or abort(404)
    if conn.provider != "statement":
        abort(404)
    db.session.delete(conn)
    db.session.commit()
    flash("Removed. The expenses it booked are still in the books.", "success")
    return redirect(url_for("books.index", tab="connections"))
