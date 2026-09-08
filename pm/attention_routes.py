"""Needs attention: the mail that is waiting on Michael, on one page.

This page used to carry seven signals - declined contracts, hosting fees under
the floor, overdue invoices, catalogue rewrites, untriaged tickets, late builds
and mail. Every one of them already had a home on the page that owns it, and a
list of seven kinds of thing is a page you skim rather than clear. Mail was the
only one with nowhere else to be answered, so mail is what is left. The other
signals still exist where the work does: hosting keeps its own sidebar badge,
read from the count below.

A row is here because a person is waiting: a client's mail, or a lead through
the site's form, with no reply from here yet. Two presses clear it - answer it,
or dismiss it - and dismissing is archiving the whole inbound thread, which is
a fact about the mail rather than about this page, so it holds however the row
was reached and whatever the next sync brings.
"""
from flask import Blueprint, render_template, url_for, current_app
from flask_login import login_required

from models import db, Message
from pm import mail_service
from pm.hosting_routes import increases_due_count

attention_bp = Blueprint("attention", __name__, url_prefix="/admin/attention")


def _unanswered():
    # A person is waiting: a client's mail, or a lead through the site's
    # form, with no reply from here yet. Archived rows are dismissed ones
    # and never come back, because the sync only ever inserts.
    #
    # Never his own address. The sync stops bringing those in, but rows
    # already written stay written, so the page has to filter as well or the
    # ones already sitting there would need dismissing one at a time.
    q = Message.query.filter_by(direction="in", status="new")
    own = mail_service.own_addresses()
    if own:
        q = q.filter(db.func.lower(db.func.coalesce(Message.from_email, ""))
                     .notin_(list(own)))
    return q.order_by(Message.received_at.desc())


def attention_counts():
    """The sidebar's badges.

    `total` is what the attention badge wears, and it is the mail alone
    because mail is all the page shows. `hosting` rides along because the
    Hosting badge reads it from here rather than asking twice; it is not a
    row on this page. Already cached for ten minutes by the hosting page.
    """
    messages = _unanswered().count()
    return {"messages": messages, "hosting": increases_due_count(),
            "total": messages}


@attention_bp.route("/")
@login_required
def index():
    # New mail is fetched in the background while this renders; the next
    # look has it. Never on the request itself - IMAP takes seconds.
    mail_service.kick(current_app._get_current_object())
    messages = _unanswered().all()
    return render_template("pm/attention/index.html", messages=messages,
                           total=len(messages), here=url_for("attention.index"))
