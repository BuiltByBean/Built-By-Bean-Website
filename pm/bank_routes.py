"""The bank feed's presses: connect a business's bank, and settle what it reads.

The review list itself is each company's Bank tab in Books since 2026-11-04
(pm/books_routes.bank, docs/finances_plan.md item 2); `/admin/bank/` sends
there. Every bank line nobody has a rule for yet, newest first, each with
the board's own suggestion filled in so the usual answer is one press, and
"remember" on so the same vendor never asks again. The list is meant to
empty itself: after the first month of answers almost every line arrives
already settled by a rule (bank_feed.py says what each disposition means).

Connecting a bank is on the company's Connections tab in Books: its owner
makes a read only token in Mercury and pastes it there. The board checks it
against Mercury before keeping it and never displays it again. Nothing here
calls a paid model: the "Ask Claude" press went on 2026-11-04, and the
/bank skill does that reading on Michael's plan.
"""
import json
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import bank_feed
from forms import EXPENSE_CATEGORY_CHOICES
from models import db, BankConnection, BankTransaction, Business, Project, VendorRule
from pm.users_routes import ceo_required

bank_bp = Blueprint("bank", __name__, url_prefix="/admin/bank")

DISPOSITIONS = [("expense", "Business expense"), ("personal", "Personal"),
                ("contribution", "Money an owner put in"), ("draw", "Money an owner took out"),
                ("transfer", "Transfer between the company's accounts"), ("income", "Money in")]
CATEGORIES = [(k, v) for k, v in EXPENSE_CATEGORY_CHOICES if k != "billable_time"]


@bank_bp.app_template_global("bank_review_count")
def bank_review_count():
    try:
        return BankTransaction.query.filter_by(disposition="review").count()
    except Exception:  # noqa: BLE001 - a badge never takes a page down
        return 0


@bank_bp.app_template_global("bank_connections_for")
def bank_connections_for(business):
    return (BankConnection.query.filter_by(business_id=business.id, provider="mercury")
            .order_by(BankConnection.id).all())


def _first_owner(business_id):
    from models import BusinessOwner
    row = (BusinessOwner.query.filter_by(business_id=business_id)
           .order_by(BusinessOwner.share_percent.desc().nullslast(), BusinessOwner.id).first())
    return row.name if row else ""


def _back():
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return url_for("books.index")


def _int(name):
    try:
        return int(request.form.get(name) or 0) or None
    except ValueError:
        return None


@bank_bp.route("/")
@ceo_required
def review():
    """The list moved into each company's Bank tab."""
    from pm.books_routes import _home
    business = db.session.get(Business, request.args.get("business_id", type=int) or 0) or _home()
    view = request.args.get("view")
    return redirect(url_for("books.bank", id=business.parent_id or business.id,
                            **({"view": view} if view else {})), 301)


@bank_bp.route("/lines/<int:id>/decide", methods=["POST"])
@ceo_required
def decide(id):
    line = db.session.get(BankTransaction, id) or abort(404)
    disposition = request.form.get("disposition") or "expense"
    if disposition not in dict(DISPOSITIONS):
        abort(400)
    project_id = _int("project_id")
    project = db.session.get(Project, project_id) if project_id else None
    settled = bank_feed.decide(
        line, disposition,
        business_id=_int("business_id") or line.business_id,
        category=request.form.get("category") or "misc",
        project_id=project_id, client_id=project.client_id if project else None,
        vendor=(request.form.get("vendor") or "").strip()[:120],
        pattern=(request.form.get("pattern") or "").strip(),
        keep=request.form.get("keep") == "1",
        owner_name=(request.form.get("owner_name") or "").strip()[:120])
    bank_feed.fold_duplicates()
    flash(f"Settled, and {settled:,} more like it." if settled else "Settled.", "success")
    return redirect(_back())


@bank_bp.route("/accept-suggested", methods=["POST"])
@ceo_required
def accept_suggested():
    """Every waiting line that carries a suggestion, settled as suggested and
    remembered, so the next charge from each vendor needs nobody."""
    done = 0
    q = (BankTransaction.query.filter_by(disposition="review")
         .filter(BankTransaction.suggestion_json.isnot(None)))
    business = db.session.get(Business, _int("business_id") or 0)
    if business is not None:
        import books_service
        q = q.filter(BankTransaction.business_id.in_(books_service.family_ids(business)))
    for line in q.all():
        if line.disposition != "review":
            continue  # settled already by a rule an earlier one in this loop wrote
        s = line.suggestion or {}
        project = db.session.get(Project, s.get("project_id")) if s.get("project_id") else None
        bank_feed.decide(line, s.get("disposition") or "expense",
                         business_id=s.get("business_id") or line.business_id,
                         category=s.get("category") or "misc",
                         project_id=project.id if project else None,
                         client_id=project.client_id if project else None,
                         vendor=s.get("vendor") or "", pattern=s.get("pattern") or "",
                         keep=bool(s.get("pattern")),
                         owner_name=_first_owner(line.business_id)
                         if s.get("disposition") in ("contribution", "draw") else "")
        done += 1
    bank_feed.fold_duplicates()
    flash(f"Accepted {done:,} suggestion{'' if done == 1 else 's'}.", "success")
    return redirect(_back())


@bank_bp.route("/connections", methods=["POST"])
@ceo_required
def connect():
    business = db.session.get(Business, _int("business_id") or 0) or abort(404)
    token = (request.form.get("token") or "").strip()
    back = url_for("books.connections", id=business.parent_id or business.id)
    if not token:
        flash("Paste the read only token from Mercury.", "warning")
        return redirect(back)
    try:
        accounts = bank_feed.mercury_accounts(token)
    except bank_feed.BankError as err:
        flash(str(err), "warning")
        return redirect(back)
    try:
        start = date.fromisoformat(request.form.get("synced_from") or "")
    except ValueError:
        start = bank_feed.BOOKS_START
    conn = BankConnection(business_id=business.id, provider="mercury",
                          label=(request.form.get("label") or "Mercury").strip()[:120],
                          token=token, synced_from=start, accounts_json=json.dumps(accounts))
    db.session.add(conn)
    db.session.commit()
    result = bank_feed.sync_connection(conn, accounts=accounts)
    if result.get("error"):
        flash(f"Connected, but the first read failed: {result['error']}", "warning")
    else:
        flash(f"Connected {len(accounts)} account{'' if len(accounts) == 1 else 's'}. "
              f"{conn.last_note}.", "success")
    return redirect(back)


@bank_bp.route("/connections/<int:id>/sync", methods=["POST"])
@ceo_required
def sync(id):
    conn = db.session.get(BankConnection, id) or abort(404)
    if conn.provider != "mercury":
        abort(404)
    result = bank_feed.sync_connection(conn)
    folded = bank_feed.fold_duplicates()
    note = result.get("error") or f"{conn.last_note}." + (f" {folded:,} charges booked twice folded into one." if folded else "")
    flash(note, "warning" if result.get("error") else "success")
    return redirect(_back())


@bank_bp.route("/connections/<int:id>/delete", methods=["POST"])
@ceo_required
def disconnect(id):
    conn = db.session.get(BankConnection, id) or abort(404)
    business_id = conn.business_id
    # The lines go with it; the expenses they made stay, because they are
    # money that really left and the books keep it.
    db.session.delete(conn)
    db.session.commit()
    flash("Disconnected. The expenses it booked are still in the books.", "success")
    return redirect(_back() if request.form.get("next") else url_for("books.index", tab=business_id))
