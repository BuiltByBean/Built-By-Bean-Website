"""Needs attention: everything the board has noticed that is waiting on
Michael, on one page, worst first.

Every other page is where work happens. Several of them had learned to
notice something on their own - a hosting fee under the floor, a rewrite
waiting in the catalogue inbox, a contract a client declined - and each
said so in its own corner, with its own badge. This is the one place they
say it together, so the day starts here rather than with a tour.

Each signal is a question the data can answer without a human: a
contract the client sent back, a fee no longer clearing the floor, an
invoice open past its due date, a proposal waiting on a yes, a ticket
nobody has triaged or one flagged to come back to, a build past its
promised date with no go-live recorded. Every row carries the one press
that resolves it, so this is a list of things to do, not a report.

What is NOT here, on purpose: contracts merely out with a client (waiting
on them, not him), recurring expenses (they generate themselves), and
anything a session could resolve without him.
"""
from datetime import date

from flask import Blueprint, render_template, url_for, current_app
from flask_login import login_required

from models import (db, CatalogueProposal, SignatureRequest, Invoice, Ticket,
                    Project, Message)
from pm import mail_service
from pm.hosting_routes import increases_due, increases_due_count, increase_url
from pm.inbox_routes import _decorate

attention_bp = Blueprint("attention", __name__, url_prefix="/admin/attention")


def _declined():
    return (SignatureRequest.query.filter_by(status="declined")
            .order_by(SignatureRequest.created_at.desc()))


def _unanswered():
    # A person is waiting: a client's mail, or a lead through the site's
    # form, with no reply from here yet.
    return (Message.query.filter_by(direction="in", status="new")
            .order_by(Message.received_at.desc()))


def _overdue_invoices(today):
    return (Invoice.query
            .filter(Invoice.status == "open")
            .filter(Invoice.due_date.isnot(None), Invoice.due_date < today)
            .filter(Invoice.amount_due > 0)
            .order_by(Invoice.due_date))


def _pending_proposals():
    return (CatalogueProposal.query.filter_by(status="pending")
            .order_by(CatalogueProposal.created_at.desc()))


def _tickets():
    # New is untriaged. Flagged is "come back to this", and it is allowed on
    # a resolved ticket - that is the whole reason it is a flag and not a
    # status - so the flag is not narrowed by status here.
    return (Ticket.query
            .filter(db.or_(Ticket.status == "new",
                           Ticket.followup_flagged.is_(True)))
            .order_by(Ticket.id.desc()))


def _late_projects(today):
    return (Project.query
            .filter(Project.status == "active")
            .filter(Project.mvp_date.isnot(None), Project.mvp_date < today)
            .filter(Project.go_live_date.is_(None))
            .order_by(Project.mvp_date))


def attention_counts():
    """Cheap counts for the sidebar badge. The hosting share is already
    cached for ten minutes by the hosting page."""
    today = date.today()
    counts = {
        "contracts": _declined().count(),
        "messages": _unanswered().count(),
        "hosting": increases_due_count(),
        "invoices": _overdue_invoices(today).count(),
        "proposals": _pending_proposals().count(),
        "tickets": _tickets().count(),
        "projects": _late_projects(today).count(),
    }
    counts["total"] = sum(counts.values())
    return counts


@attention_bp.route("/")
@login_required
def index():
    today = date.today()
    # New mail is fetched in the background while this renders; the next
    # look has it. Never on the request itself - IMAP takes seconds.
    mail_service.kick(current_app._get_current_object())
    sections = {
        "contracts": _declined().all(),
        "messages": _unanswered().all(),
        # The link is built here, in the request, from the cached ingredients.
        "hosting": [dict(r, url=increase_url(r)) for r in increases_due()],
        "invoices": _overdue_invoices(today).all(),
        "proposals": _decorate(_pending_proposals().all()),
        "tickets": _tickets().all(),
        "projects": _late_projects(today).all(),
    }
    total = sum(len(v) for v in sections.values())
    return render_template("pm/attention/index.html", s=sections, total=total,
                           today=today, here=url_for("attention.index"))
