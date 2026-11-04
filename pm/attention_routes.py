"""Needs attention: the mail that is waiting on Michael, on one page.

Plus, since 2026-11-04, one row when the nightly job broke or did not run
(night_log.py), because a broken night is otherwise silent until a number
looks wrong, and nothing else on the board would say so.

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
import json
import time
from datetime import date, timedelta

from flask import Blueprint, render_template, url_for, current_app
from flask_login import login_required

from models import (db, Message, ServiceProvider, ServiceCostEntry,
                    ProviderInvoice)
from pm import mail_service
from pm.hosting_routes import increases_due_count

attention_bp = Blueprint("attention", __name__, url_prefix="/admin/attention")

# The bill check walks a handful of providers and a couple of dozen months.
# That is nothing on its own and it would run on EVERY page in the board,
# because the sidebar badge is built in the context processor. Cached for the
# same ten minutes the hosting badge uses.
_BILLS_CACHE = {"at": 0.0, "value": None}
_BILLS_TTL = 600


def _months_between(first, stop):
    """Every month start from `first` up to but not including `stop`."""
    out, m = [], first.replace(day=1)
    while m < stop:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def _bills_to_enter(force=False):
    """Vendors whose invoice for a FINISHED month has not been recorded.

    A month is asked for once it is over, which is the whole point of asking:
    on the first, last month's bill exists and the usage screen still has the
    figures on it. Nothing is ever asked for the month in progress.

    Only vendors whose money this board already tracks: a provider with no
    cost entry and no invoice has never cost anything here, and nagging about
    it would make this list noise rather than a list to clear.

    And only vendors that MUST be typed in. Railway was, until its bills
    turned out to be readable with an account token (2026-11-01); a Railway
    account that names its workspace now pulls them, and is given a month's
    grace below. Hand typing is why its ledger could once hold two
    populations at once and double count. Cloudflare and Twilio read their own billing history and usage
    records straight from the vendor, so there is nothing for anybody to
    enter, and asking would be inventing a monthly chore for the two vendors
    that already do it themselves.
    """
    from pm.service_costs_routes import MANUAL_MONTHLY_PROVIDERS
    now = time.time()
    if not force and _BILLS_CACHE["value"] is not None and now - _BILLS_CACHE["at"] < _BILLS_TTL:
        return _BILLS_CACHE["value"]

    this_month = date.today().replace(day=1)
    out = []
    try:
        providers = (ServiceProvider.query.filter_by(is_active=True)
                     .order_by(ServiceProvider.display_name).all())
        for p in providers:
            if p.name not in MANUAL_MONTHLY_PROVIDERS:
                continue
            first_entry = (db.session.query(db.func.min(ServiceCostEntry.period_start))
                           .filter(ServiceCostEntry.provider_id == p.id).scalar())
            first_invoice = (db.session.query(db.func.min(ProviderInvoice.period_month))
                             .filter(ProviderInvoice.provider_id == p.id).scalar())
            starts = [d for d in (first_entry, first_invoice) if d]
            if not starts:
                continue
            have = {r.period_month for r in
                    ProviderInvoice.query.filter_by(provider_id=p.id).all()}
            # A Railway account that names its workspace pulls its own bills
            # (service_costs_service._sync_railway), and its billing month
            # need not start on the 1st: EntertainHQ's runs 16th to 16th, so
            # its October bill does not exist until November 16. Ask about
            # those only once a whole further month has passed, which is
            # when a missing one means the pull has stopped working.
            stop = this_month
            try:
                if json.loads(p.credentials_json or "{}").get("workspace_id"):
                    stop = (this_month - timedelta(days=1)).replace(day=1)
            except ValueError:
                pass
            missing = [m for m in _months_between(min(starts), stop)
                       if m not in have]
            if missing:
                out.append({"provider": p, "missing": missing,
                            "latest": missing[-1], "count": len(missing)})
    except Exception:
        # A table that does not exist yet must not take the whole board down.
        db.session.rollback()
        out = []

    _BILLS_CACHE["at"] = now
    _BILLS_CACHE["value"] = out
    return out


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


# The night job is meant to finish once a day (13:00 UTC). A day and two
# hours without a finished run means it did not run, which is as much a
# failure as a step that broke.
NIGHT_GRACE_HOURS = 26


def _night_problem():
    """None, or the one thing wrong with the nightly job: a step that failed
    in the newest run, or no run finished in NIGHT_GRACE_HOURS. One row, not
    one per step: the night page has the detail."""
    from datetime import datetime, timezone
    from models import NightRun
    try:
        latest = NightRun.query.order_by(NightRun.started_at.desc(), NightRun.id.desc()).first()
        done = (NightRun.query.filter(NightRun.finished_at.isnot(None))
                .order_by(NightRun.finished_at.desc()).first())
    except Exception:  # noqa: BLE001 - the table may not exist yet
        db.session.rollback()
        return None
    if latest is None:
        return None  # never run since this shipped: nothing to say yet
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if done is None or (now - done.finished_at.replace(tzinfo=None)).total_seconds() > NIGHT_GRACE_HOURS * 3600:
        return {"kind": "missing", "run": done or latest}
    if done.failed_steps:
        return {"kind": "failed", "run": done, "steps": done.failed_steps}
    return None


def attention_counts():
    """The sidebar's badges.

    `total` is what the attention badge wears, and it is the mail alone
    because mail is all the page shows. `hosting` rides along because the
    Hosting badge reads it from here rather than asking twice; it is not a
    row on this page. Already cached for ten minutes by the hosting page.
    """
    messages = _unanswered().count()
    bills = len(_bills_to_enter())
    # Mail and bills both, because both are things only he can do and neither
    # has anywhere else to be answered. Hosting rides along for its own badge
    # and is not a row here.
    night = 1 if _night_problem() else 0
    return {"messages": messages, "bills": bills, "night": night,
            "hosting": increases_due_count(),
            "total": messages + bills + night}


@attention_bp.route("/")
@login_required
def index():
    # New mail is fetched in the background while this renders; the next
    # look has it. Never on the request itself - IMAP takes seconds.
    mail_service.kick(current_app._get_current_object())
    messages = _unanswered().all()
    # force: the page itself must never show a ten minute old answer about
    # something the reader may have just entered.
    bills = _bills_to_enter(force=True)
    night = _night_problem()
    return render_template("pm/attention/index.html", messages=messages,
                           bills=bills, night=night,
                           total=len(messages) + len(bills) + (1 if night else 0),
                           here=url_for("attention.index"))


@attention_bp.route("/nights")
@login_required
def nights():
    """The last fortnight of nightly runs, each step with how it went."""
    from models import NightRun
    runs = NightRun.query.order_by(NightRun.started_at.desc(), NightRun.id.desc()).limit(14).all()
    return render_template("pm/attention/nights.html", runs=runs)
