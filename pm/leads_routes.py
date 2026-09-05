"""Every business in the trade area, and what has been tried on each.

One page. The list answers "who is left to ring", a row opens to what the
public record knows, and the press that logs an attempt is on the row
rather than behind a detail page, because a hundred calls a week does not
survive a round trip per call.

Nothing here is officer-only: this is the marketing seat's page, and the
CMO is who lives in it.
"""
from datetime import date, datetime, timezone

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import case, func, or_

from models import (db, Lead, LeadPerson, LeadTouch, Client,
                    CLIENT_STAGE_CHOICES, CONTACT_CHANNEL_CHOICES,
                    LEAD_OUTCOME_CHOICES, LEAD_OUTCOMES_REACHED,
                    LEAD_WENT_CHOICES)

leads_bp = Blueprint("leads", __name__, url_prefix="/admin/leads")

PER_PAGE = 25

# The whole point of the list is deciding who to ring next, so the default
# order puts the untouched first and, within those, the ones the public
# record says are most worth a call: no website, then longest trading.
SORTS = [
    ("best", "Best bets"),
    ("name", "Name"),
    ("city", "City"),
    ("oldest", "Longest trading"),
    ("touched", "Recently tried"),
]


def _clean(value, limit):
    return (value or "").strip()[:limit]


@leads_bp.route("/")
@login_required
def index():
    search = _clean(request.args.get("q"), 120)
    city = _clean(request.args.get("city"), 80)
    stage = _clean(request.args.get("stage"), 30)
    industry = _clean(request.args.get("industry"), 120)
    website = _clean(request.args.get("website"), 10)
    untried = request.args.get("untried") == "1"
    sort = _clean(request.args.get("sort"), 20) or "best"
    page = max(1, request.args.get("page", type=int) or 1)

    query = Lead.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Lead.name.ilike(like), Lead.legal_name.ilike(like),
                                 Lead.owner_name.ilike(like), Lead.address.ilike(like),
                                 Lead.industry.ilike(like), Lead.phone.ilike(like)))
    if city:
        query = query.filter(Lead.city == city)
    if stage:
        query = query.filter(Lead.stage == stage)
    if industry:
        query = query.filter(Lead.industry == industry)
    if website == "no":
        query = query.filter(or_(Lead.website.is_(None), Lead.website == ""))
    elif website == "yes":
        query = query.filter(Lead.website.isnot(None), Lead.website != "")
    if untried:
        # Nobody has logged anything against it yet.
        query = query.filter(~Lead.touches.any())

    # case() rather than a bare comparison: a NULL website sorts unpredictably
    # otherwise, and "no website" is the whole point of the default order.
    no_site = case((or_(Lead.website.is_(None), Lead.website == ""), 0), else_=1)
    no_start = case((Lead.started_on.is_(None), 1), else_=0)

    if sort == "name":
        query = query.order_by(Lead.name)
    elif sort == "city":
        query = query.order_by(Lead.city, Lead.name)
    elif sort == "oldest":
        query = query.order_by(no_start, Lead.started_on, Lead.name)
    elif sort == "touched":
        query = query.order_by(Lead.updated_at.desc())
    else:
        # Best bets: never tried, then no website, then trading longest.
        query = query.order_by(Lead.touches.any(), no_site, no_start,
                               Lead.started_on, Lead.name)

    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)

    cities = [row[0] for row in db.session.query(Lead.city)
              .filter(Lead.city != "").group_by(Lead.city)
              .order_by(func.count(Lead.id).desc()).limit(40).all()]
    industries = [row[0] for row in db.session.query(Lead.industry)
                  .filter(Lead.industry != "").group_by(Lead.industry)
                  .order_by(func.count(Lead.id).desc()).limit(60).all()]

    counts = {
        "total": Lead.query.count(),
        "untried": Lead.query.filter(~Lead.touches.any()).count(),
        "no_website": Lead.query.filter(or_(Lead.website.is_(None), Lead.website == "")).count(),
        "talking": Lead.query.filter(Lead.stage.in_(("contacted", "in_conversation", "proposal_sent"))).count(),
        "clients": Lead.query.filter(Lead.client_id.isnot(None)).count(),
    }

    return render_template(
        "pm/leads/index.html",
        leads=pagination.items, pagination=pagination, counts=counts,
        cities=cities, industries=industries, sorts=SORTS,
        stage_choices=CLIENT_STAGE_CHOICES, channel_choices=CONTACT_CHANNEL_CHOICES,
        outcome_choices=LEAD_OUTCOME_CHOICES, went_choices=LEAD_WENT_CHOICES,
        reached_outcomes=list(LEAD_OUTCOMES_REACHED),
        filters={"q": search, "city": city, "stage": stage, "industry": industry,
                 "website": website, "untried": untried, "sort": sort})


def _back(lead_id=None):
    """Back to the list exactly as she left it, on the row she pressed.

    The filters ride in the row forms as f_* fields. The prefix is load
    bearing: the stage form posts `stage` as the new stage, and reading an
    unprefixed field of that name would file it as the filter and change
    the list under her.
    """
    args = {}
    for key in ("q", "city", "stage", "industry", "website", "untried", "sort", "page"):
        value = request.form.get("f_" + key) or request.args.get(key)
        if value:
            args[key] = value
    target = url_for("leads.index", **args)
    return target + (f"#lead-{lead_id}" if lead_id else "")


@leads_bp.route("/<int:id>/touch", methods=["POST"])
@login_required
def touch(id):
    lead = db.session.get(Lead, id) or abort(404)
    channel = request.form.get("channel", "phone")
    outcome = request.form.get("outcome", "no_answer")
    if channel not in dict(CONTACT_CHANNEL_CHOICES):
        channel = "phone"
    if outcome not in dict(LEAD_OUTCOME_CHOICES):
        outcome = "no_answer"
    went = request.form.get("went", "")
    if went not in dict(LEAD_WENT_CHOICES) or outcome not in LEAD_OUTCOMES_REACHED:
        # "How did it go" only means anything when somebody was reached.
        went = ""
    db.session.add(LeadTouch(
        lead_id=lead.id, user_id=current_user.id, channel=channel, outcome=outcome,
        went=went, occurred_on=date.today(), note=_clean(request.form.get("note"), 2000)))

    # The stage follows the outcome unless she has already moved it further
    # along by hand. Logging a call should not undo "proposal sent".
    now = datetime.now(timezone.utc)
    if outcome == "no":
        lead.stage, lead.stage_changed_at = "not_interested", now
    elif outcome == "not_now":
        lead.stage, lead.stage_changed_at = "follow_up", now
    elif outcome in ("spoke", "meeting") and lead.stage in ("lead", "contacted"):
        lead.stage, lead.stage_changed_at = "in_conversation", now
    elif lead.stage == "lead":
        lead.stage, lead.stage_changed_at = "contacted", now
    lead.updated_at = now
    db.session.commit()
    return redirect(_back(lead.id))


@leads_bp.route("/<int:id>/stage", methods=["POST"])
@login_required
def stage(id):
    lead = db.session.get(Lead, id) or abort(404)
    picked = request.form.get("stage", "")
    if picked in dict(CLIENT_STAGE_CHOICES):
        lead.stage = picked
        lead.stage_changed_at = datetime.now(timezone.utc)
        db.session.commit()
    return redirect(_back(lead.id))


@leads_bp.route("/<int:id>/note", methods=["POST"])
@login_required
def note(id):
    lead = db.session.get(Lead, id) or abort(404)
    lead.notes = _clean(request.form.get("notes"), 4000)
    db.session.commit()
    return redirect(_back(lead.id))


@leads_bp.route("/<int:id>/convert", methods=["POST"])
@login_required
def convert(id):
    lead = db.session.get(Lead, id) or abort(404)
    if lead.client_id:
        flash(f"{lead.name} is already a client.", "warning")
        return redirect(_back(lead.id))

    person = lead.primary_person
    client = Client(
        name=lead.owner_name or (person.name if person else lead.name),
        company=lead.name,
        email=lead.email or (person.email if person else ""),
        phone=lead.phone or (person.phone if person else ""),
        address=", ".join(part for part in (lead.address, lead.city, lead.state, lead.zip_code) if part),
        # Everything the public record gave, carried over rather than retyped.
        notes="\n".join(part for part in (
            f"From the leads list. {lead.industry}" if lead.industry else "From the leads list.",
            f"Trading since {lead.started_on.year}." if lead.started_on else "",
            f"Website: {lead.website}" if lead.website else "No website.",
            lead.notes or "",
        ) if part),
        stage="in_conversation",
    )
    db.session.add(client)
    db.session.flush()
    lead.client_id = client.id
    lead.converted_at = datetime.now(timezone.utc)
    lead.stage = "in_conversation"
    lead.stage_changed_at = lead.converted_at
    db.session.commit()
    flash(f"{lead.name} is a client now.", "success")
    return redirect(url_for("pm.client_detail", id=client.id))


@leads_bp.route("/<int:id>/person", methods=["POST"])
@login_required
def add_person(id):
    lead = db.session.get(Lead, id) or abort(404)
    name = _clean(request.form.get("name"), 160)
    if name:
        db.session.add(LeadPerson(
            lead_id=lead.id, name=name, role=_clean(request.form.get("role"), 120),
            email=_clean(request.form.get("email"), 200).lower(),
            phone=_clean(request.form.get("phone"), 40), source="typed",
            sort_order=len(lead.people) + 1))
        db.session.commit()
    return redirect(_back(lead.id))
