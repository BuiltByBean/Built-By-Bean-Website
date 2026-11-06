import re
from datetime import datetime, timezone, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from secret_box import SealedText
from sqlalchemy.orm import Session as _OrmSession
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(100), default="")
    last_name = db.Column(db.String(100), default="")
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), default="")
    # Titles. The CEO runs the board and its people; CTO, CMO and member
    # are titles with every other door. "owner" and "admin" are the values
    # accounts carried before there were titles, and they read as CEO so
    # nothing that existed loses a door.
    role = db.Column(db.String(20), default="member")
    must_change_password = db.Column(db.Boolean, default=False)
    # Switched off rather than deleted: a person who has left still owns
    # the time they logged and the timer rows that point at them.
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    ROLES = (("ceo", "CEO"), ("cto", "CTO"), ("cmo", "CMO"), ("member", "Member"))
    LEGACY_CEO_ROLES = ("owner", "admin")

    @property
    def is_ceo(self):
        return self.role == "ceo" or self.role in self.LEGACY_CEO_ROLES

    @property
    def role_label(self):
        if self.role in self.LEGACY_CEO_ROLES:
            return "CEO"
        return dict(self.ROLES).get(self.role, "Member")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def has_password(self):
        return bool(self.password_hash)

    @property
    def full_name(self):
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.username

    def __repr__(self):
        return f"<User {self.username}>"


# How far along a business is, from a name on a list to somebody paying.
#
# The two closed stages earn their place: without "Not interested" the only
# record of a no is that nobody wrote anything down, and a business that has
# already turned you down gets called again six weeks later. "Follow up later"
# is the other half of that - a no for now is not a no.
CLIENT_STAGE_CHOICES = [
    ("lead", "Lead"),
    ("contacted", "Contacted"),
    ("in_conversation", "In conversation"),
    ("proposal_sent", "Proposal sent"),
    ("contracted", "Contracted"),
    ("active_client", "Active client"),
    ("follow_up", "Follow up later"),
    ("not_interested", "Not interested"),
]

# Stages that mean nobody should be ringing this business again - one because
# they said no, one because they are already paying.
CLIENT_STAGES_CLOSED = ("not_interested", "active_client")

# How you reached them. This order is the order they render in.
CONTACT_CHANNEL_CHOICES = [
    ("phone", "Phone"),
    ("email", "Email"),
    ("text", "Text"),
    ("in_person", "In person"),
    ("other", "Other"),
]

# What came of one attempt. A channel alone says somebody was rung; this
# says whether anyone picked up, which is the only thing that decides
# whether to ring again on Monday or leave them alone until spring.
LEAD_OUTCOME_CHOICES = [
    ("no_answer", "No answer"),
    ("left_message", "Left a message"),
    ("no_reply", "No reply yet"),
    ("spoke", "Spoke to them"),
    ("meeting", "Meeting booked"),
    ("not_now", "Not right now"),
    ("no", "Not interested"),
    ("bad_number", "Wrong number"),
]

# Outcomes that mean a person was actually on the other end. Only these
# make "how did it go" worth asking.
LEAD_OUTCOMES_REACHED = ("spoke", "meeting", "not_now", "no")

# How it went, asked only when somebody was reached. Three words, because
# the fourth would be a paragraph and that is what the note is for.
LEAD_WENT_CHOICES = [
    ("", "Not said"),
    ("good", "Went well"),
    ("mixed", "Mixed"),
    ("poor", "Went badly"),
]



class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), default="")
    phone = db.Column(db.String(50), default="")
    company = db.Column(db.String(200), default="")
    address = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    stripe_customer_id = db.Column(db.String(100), nullable=True, unique=True)
    # Which app this client's tickets arrive from, and the shared secret that
    # signs them. One secret per client, so a leak is one client's problem and
    # is rotated without touching anybody else.
    #
    # Nullable rather than "" and unique: a client with no app of their own is
    # the normal case, and several of those would collide on a unique empty
    # string. Null does not collide with null.
    origin_slug = db.Column(db.String(40), nullable=True, unique=True)
    ingest_secret = db.Column(SealedText(), default="")
    # Where my replies get pushed back to, e.g. https://kuperplumbing.com.
    # Empty means their app cannot receive them, so a reply stays here and is
    # visible as undelivered rather than being silently dropped.
    origin_base_url = db.Column(db.String(300), default="")
    # When this board last ASKED their app for tickets, and what came back.
    # Tickets used to arrive only when their outbox chose to run, so an app
    # whose sender thread never started was indistinguishable from an app with
    # nothing to say. These two columns are what makes silence readable: a
    # stamp that stops moving is a pipe that stopped, and the note says which
    # end refused. Null means never asked.
    hub_pulled_at = db.Column(db.DateTime, nullable=True)
    hub_pull_note = db.Column(db.String(300), default="")

    # Texas sales tax is owed on what is sold TO them, so whether it applies
    # is a fact about the buyer: out of state, a resale or exemption
    # certificate on file, or Built by Bean's own row. False is the default
    # because every client so far is in Texas and a missed exemption costs a
    # refund, while a missed charge costs the tax out of pocket.
    sales_tax_exempt = db.Column(db.Boolean, nullable=False, default=False,
                                 server_default=db.false())
    sales_tax_exempt_reason = db.Column(db.String(200), default="")

    stage = db.Column(db.String(30), default="lead")
    contract_revenue = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    projects = db.relationship("Project", back_populates="client", cascade="all, delete-orphan", lazy="dynamic")
    # Every ticket belongs to a client, project or no project, because the board
    # is grouped by who asked rather than by what it is filed under.
    tickets = db.relationship("Ticket", back_populates="client",
                              cascade="all, delete-orphan", lazy="dynamic")
    time_entries = db.relationship("TimeEntry", backref="client", lazy="dynamic")
    # The old hand-typed contact log. Nothing writes it any more (mail is the
    # record of contact now, see last_message); kept so its rows go with a
    # deleted client rather than blocking the delete.
    contacts = db.relationship("ClientContact", back_populates="client",
                               cascade="all, delete-orphan",
                               order_by="ClientContact.occurred_on.desc(),"
                                        " ClientContact.id.desc()")

    @property
    def last_message(self):
        """The newest mail either way between us, or None.

        Contact is mail now. The hand-typed log it replaced held no rows on
        any client in seven months, while every client's mail was already
        here, filed to them by mail_service.
        """
        return (Message.query.filter_by(client_id=self.id)
                .order_by(Message.received_at.desc(), Message.id.desc()).first())

    @staticmethod
    def last_messages(client_ids):
        """{client_id: newest Message} for many clients in two queries, for
        a list that would otherwise ask once per row."""
        if not client_ids:
            return {}
        newest = (db.session.query(Message.client_id,
                                   db.func.max(Message.received_at).label("at"))
                  .filter(Message.client_id.in_(client_ids))
                  .group_by(Message.client_id).subquery())
        rows = (Message.query.join(newest, db.and_(
                    Message.client_id == newest.c.client_id,
                    Message.received_at == newest.c.at))
                .order_by(Message.id.desc()).all())
        out = {}
        for row in rows:
            out.setdefault(row.client_id, row)
        return out

    @property
    def active_projects_count(self):
        return self.projects.filter_by(status="active").count()

    @property
    def total_invoiced(self):
        """Everything raised against them, paid included.

        Void excluded, because a voided invoice was cancelled and was never
        money. The same rule the invoices page uses for its Total Billed tile,
        copied rather than reinvented so the two cannot disagree.
        """
        return sum(inv.total or 0.0 for inv in self.invoices
                   if (inv.status or "") != "void")

    @property
    def total_revenue(self):
        """Earned from this client: each paid invoice less its sales tax and
        its refunds, and nothing from a catch-up invoice, which bills back tax.
        The same reading as the dashboard's Total Revenue
        (stripe_service.get_stripe_invoice_totals)."""
        return sum(inv.earned for inv in self.invoices)

    # No total_profit here on purpose. Client.total_expenses and the sum of
    # the projects' expenses are not the same number, so a profit property on
    # the model and a profit tile on the page would disagree the moment an
    # expense was booked against the client rather than a project. The page
    # subtracts the expense figure it is itself showing.

    @property
    def total_hours(self):
        total = 0
        for entry in self.time_entries:
            total += entry.hours
        return total

    def __repr__(self):
        return f"<Client {self.name}>"


class ClientContact(db.Model):
    """One attempt to reach a business.

    Cold calling a town means the only thing standing between you and ringing
    somebody for the second time is a written record. A flag saying "phoned"
    would answer that for about a fortnight; what you actually need three
    months later is the date and the sentence - "left a voicemail", "spoke to
    the owner, call back in September" - which is why this is a row per
    attempt and not a column per channel.
    """

    __tablename__ = "client_contacts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, default="phone")
    # A date, not a timestamp: nobody logging a call remembers the minute, and
    # a date is what "have we called them this week" is answered with.
    occurred_on = db.Column(db.Date, nullable=False, default=lambda: date.today())
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", back_populates="contacts")

    @property
    def channel_label(self):
        return dict(CONTACT_CHANNEL_CHOICES).get(self.channel, self.channel)

    def __repr__(self):
        return f"<ClientContact {self.channel} {self.occurred_on}>"


# A product's life (Michael's pick, 2026-11-04). Live is the end state; nothing
# about contracts or free maintenance, which are a client build's.
PRODUCT_STAGES = (("idea", "Idea"), ("building", "Building"), ("beta", "Beta"), ("live", "Live"))


def client_is_own(client):
    """Whether a client row is Michael's own: its address is one of his, or
    its name is a CEO's name. The same two tests session_time uses, without
    its tile rule (a client build moved to Personal projects on My Apps is
    still a client build)."""
    if client is None:
        return True
    # Asked once per client per request: a list of cards asks for every one.
    try:
        from flask import g, has_request_context
        memo = g.setdefault("_own_clients", {}) if has_request_context() else {}
    except Exception:  # noqa: BLE001
        memo = {}
    if client.id in memo:
        return memo[client.id]
    memo[client.id] = answer = _client_is_own(client)
    return answer


def _client_is_own(client):
    try:
        from flask import current_app, has_app_context
        if has_app_context():
            from pm.mail_service import own_addresses
            if (client.email or "").strip().lower() in own_addresses(current_app):
                return True
    except Exception:  # noqa: BLE001 - a missing mail setting is not an answer
        pass
    flat = re.sub(r"[^a-z0-9]", "", (client.name or "").lower())
    if not flat:
        return False
    for user in User.query.filter(User.role.in_(("ceo", "owner", "admin"))).all():
        if flat == re.sub(r"[^a-z0-9]", "", f"{user.first_name or ''}{user.last_name or ''}".lower()):
            return True
    return False


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    # Nothing is signed when a project is put on the board; a signed SOW is
    # what moves it to Contracted (contract_effects).
    phase = db.Column(db.String(30), default="not_contracted")
    budget = db.Column(db.Float, nullable=True)
    # What the contract promised, and what actually happened. The first
    # comes from the SOW; the second is set when it goes live, and is what
    # the free-maintenance clock runs from.
    mvp_date = db.Column(db.Date, nullable=True)
    go_live_date = db.Column(db.Date, nullable=True)
    maintenance_days = db.Column(db.Integer, default=30)
    # What the client pays to stay online, as agreed in the contract that set
    # it. Nullable with no default: 0 means "hosted for free" and None means
    # "nobody has set this", and only the second one is a thing to go and fix.
    hosting_fee = db.Column(db.Float, nullable=True)
    hosting_cycle = db.Column(db.String(20), nullable=True)
    # The GitHub repository, as owner/name, so the nightly audit can hold
    # this build's code against the catalogue's rules. Nullable: an app
    # taken over without a repo is still a project.
    repo = db.Column(db.String(200), nullable=True, index=True)
    # Set the moment a phase is changed by hand. mvp_date is a promise,
    # not a fact - a build running late would otherwise be marched to
    # Delivered by its own contract date and marched back every reload.
    phase_locked = db.Column(db.Boolean, default=False, nullable=False)
    # What the board read for itself (project_autofill, nightly): the day of
    # the first commit after the contract, which is when it moved Contracted
    # to MVP, and where a go-live date it filled in came from, so the page can
    # say so. Both only ever written into empty fields.
    build_started_on = db.Column(db.Date, nullable=True)
    go_live_source = db.Column(db.String(200), nullable=True)
    # The last night the board looked for this build's live site and found
    # none. Go-live is filled only when a site answers AFTER a night like that,
    # because a site already answering the first night it was looked at went
    # live on a day nobody saw: stamping that night gave Kuper Plumbing and
    # Talent Booker a fresh free maintenance window months after go-live.
    not_live_on = db.Column(db.Date, nullable=True)
    # What kind of project it is (Michael, 2026-11-04: "EntertainHQ, Ideas,
    # Piped those are my products they wouldnt even follow the same phases").
    # "client" is a build for a client and walks PHASE_CHOICES; "product" is
    # one of his own and walks PRODUCT_STAGES; "personal" is his own and off
    # the Workspace's work list (Lets Cook). NULL follows the client: his own
    # client row means product, anyone else's means client (`kind_effective`).
    kind = db.Column(db.String(20), nullable=True)
    # A product's stage; a client build's is `phase`. Kept apart because the
    # phase moves itself off contract dates, and a product has none.
    stage = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), default="active")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", back_populates="projects")
    tickets = db.relationship("Ticket", back_populates="project", lazy="dynamic")
    # Deleted with the project rather than disowned by it. time_entries
    # .project_id is NOT NULL, so the default of nulling the key on delete
    # cannot succeed - deleting a project that had any logged time failed
    # outright. No passive_deletes: SQLite runs with foreign_keys off, so
    # leaving it to the database would cascade in Postgres and quietly
    # orphan rows here.
    time_entries = db.relationship("TimeEntry", backref="project", lazy="dynamic",
                                   cascade="all, delete-orphan")

    # A quarterly or annual fee compared against a monthly cost reads as a
    # fat margin for two months and a disaster on the third. Everything on the
    # hosting page is per month, so the divisor lives here rather than in the
    # page doing the comparing.
    HOSTING_CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "annually": 12}

    KINDS = (("client", "Client build"), ("product", "My product"),
              ("personal", "Personal project"))

    @property
    def kind_effective(self):
        """The kind as set, or as the client says: Michael's own client row
        is his own product, anybody else's is a client build."""
        if self.kind in dict(self.KINDS):
            return self.kind
        return "product" if client_is_own(self.client) else "client"

    @property
    def is_client_build(self):
        return self.kind_effective == "client"

    @property
    def stage_effective(self):
        """A product's stage, or where its dates put it when none was set."""
        if self.stage in dict(PRODUCT_STAGES):
            return self.stage
        if self.go_live_date or self.phase in ("delivered", "free_maintenance", "in_production"):
            return "live"
        return "building" if self.phase == "mvp" else "idea"

    @property
    def monthly_hosting_fee(self):
        """The hosting fee expressed per month, or None if none is set."""
        if self.hosting_fee is None:
            return None
        return self.hosting_fee / self.HOSTING_CYCLE_MONTHS.get(self.hosting_cycle or "monthly", 1)

    @property
    def maintenance_anchor(self):
        """The day the free window starts counting from.

        Go-live, falling back to the delivery date for the projects that
        predate go_live_date - without the fallback every one of them would
        have no window at all, and every past hour would turn billable.
        """
        return self.go_live_date or self.mvp_date

    @property
    def free_maintenance_end(self):
        anchor = self.maintenance_anchor
        if anchor:
            return anchor + timedelta(days=self.maintenance_days or 30)
        return None

    @property
    def total_hours(self):
        total = 0
        for entry in self.time_entries:
            total += entry.hours
        return total

    @property
    def total_revenue(self):
        total = 0
        for entry in self.time_entries:
            total += entry.cost
        return total

    @property
    def total_expenses(self):
        """Material expenses only - excludes auto-generated billable time expenses."""
        return sum(
            e.amount for e in Expense.query.filter(
                Expense.project_id == self.id,
                Expense.time_entry_id == None  # noqa: E711
            ).all()
        )

    @property
    def budget_remaining(self):
        if self.budget:
            return self.budget - self.total_revenue - self.total_expenses
        return None

    def __repr__(self):
        return f"<Project {self.name}>"


# ---------------------------------------------------------------- tickets
#
# What used to be Task. A task was a thing I wrote down for myself; a ticket is
# a thing a client asked for, and most of them arrive through that client's own
# app rather than being typed here. The money model hangs off it either way, so
# the columns Task carried for expenses, time and documents carry over
# unchanged.
#
# Subtasks go with it. A ticket has no parent and no children: the boards this
# one is modelled on have never needed them, and a nested board is a second way
# of saying "these are related" alongside the project a ticket already belongs
# to. Existing subtasks are flattened into ordinary tickets by the migration
# rather than deleted, so nothing anybody wrote down is lost.
#
# The vocabulary is Talent Booker's, copied rather than reinvented, because
# that board has already made and fixed the mistakes this one would make.

# What kind of work it is.
TICKET_CATEGORIES = ("bug", "feature", "enhancement", "other")
TICKET_CATEGORY_LABELS = {
    "bug": "Bug", "feature": "Feature", "enhancement": "Enhancement", "other": "Other",
}

# Where the work has got to, and nothing else. Out of scope and follow-up are
# NOT in here: see the flags on the model for why.
TICKET_STATUSES = ("new", "in-progress", "resolved", "dismissed")
TICKET_STATUS_LABELS = {
    "new": "New", "in-progress": "In progress", "resolved": "Resolved",
    "dismissed": "Dismissed",
}
# One tuple, so the board filter, the open filter and the header counts cannot
# end up with three opinions about what "still open" means.
TICKET_CLOSED_STATUSES = ("resolved", "dismissed")

# How badly the person who raised it needs it. Their voice, not my triage call.
# Ordered most urgent first, and that order IS the sort order.
TICKET_PRIORITIES = ("urgent", "soon", "normal", "backlog")
TICKET_PRIORITY_LABELS = {
    "urgent": "Urgent", "soon": "Soon", "normal": "Normal", "backlog": "Backlog",
}

# What the work costs. Blank is not a fourth bucket: an unclassified ticket has
# to stay distinguishable from a free one, or undecided work reads as free on
# an invoice.
TICKET_BILLING_BUCKETS = ("free", "maintenance", "new")
TICKET_BILLING_LABELS = {
    "free": "Free fix", "maintenance": "Maintenance", "new": "New development",
}
TICKET_BILLING_RATES = {"free": 0, "maintenance": 100, "new": 200}


class Ticket(db.Model):
    """One thing a client has asked for, on one board across every client.

    Four facts about a ticket are true at the same time and therefore live in
    four columns: `category` is what kind of work it is, `status` is where the
    work has got to, `priority` is how badly the person who raised it needs it,
    and `followup_flagged` is "come back to this".

    `out_of_scope` is a fifth. Both flags are flags rather than statuses for the
    same reason, which is the single mistake this family of boards keeps making:
    wanting to revisit something and having finished it are both allowed to be
    true, and so are being mid-repair and being outside what an app is for.
    Talent Booker shipped follow-up as a status and flagging a resolved ticket
    silently un-resolved it. Kuper then shipped out-of-scope as a status and did
    the same thing one column along. Neither may share a column with status.
    """
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    # The aggregation key, and the reason this table exists. Every ticket
    # belongs to a client whether or not it belongs to a project: a bug report
    # from a live app is not project work until I decide it is.
    #
    # Nullable since 2026-11-04, when the board became the support board for
    # every business Michael owns: a ticket from EntertainHQ's or Data
    # Dungeon's own desk was raised by THAT business's customer, who is no
    # client of this board. Such a ticket carries `business_id` instead. A
    # ticket with neither is the board company's (Built by Bean's).
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"),
                           nullable=True, index=True)
    business_id = db.Column(db.Integer,
                            db.ForeignKey("businesses.id", ondelete="CASCADE",
                                          name="fk_tickets_business_id"),
                            nullable=True, index=True)

    # Where it came from. `origin` is the app's own slug ("kuper", "talent-booker"),
    # `origin_ticket_id` is its id over there, and the pair is unique so the same
    # ticket arriving twice updates rather than duplicates. A ticket raised here
    # by hand carries origin "local" and no origin id.
    origin = db.Column(db.String(40), nullable=False, default="local", index=True)
    origin_ticket_id = db.Column(db.Integer, nullable=True)
    origin_url = db.Column(db.String(500), default="")
    # A ticket read from a business's own support desk (support_service.py) is
    # keyed by the desk's own name for it, "<company>:<id>", because the desk
    # holds one numbering per company and an integer alone collides. Null for
    # a hub ticket, so the hub's drains can tell the two apart: the desk owns
    # its tickets, and nothing on the hub's queues may ever send one.
    origin_ref = db.Column(db.String(80), nullable=True)
    # The desk's own updated_at the last time its whole thread was read, so a
    # pull only asks again for the tickets that moved.
    origin_updated_at = db.Column(db.DateTime, nullable=True)

    # Who has to speak next: "you" (the customer spoke last, or nobody has
    # answered yet), "them" (the last word was ours), or "" once it is closed.
    # Stored rather than worked out on render so the sidebar badge and the
    # Waiting on you tab are one cheap query and always the same number.
    waiting_on = db.Column(db.String(10), nullable=False, default="", server_default="")
    waiting_since = db.Column(db.DateTime, nullable=True)
    # What the health tiles are made of. Each is stamped when it is SEEN to
    # happen (or read from a desk that saw it), never backdated by a guess: a
    # ticket that arrived already resolved has no resolved_at, because "now"
    # would make every imported fix look instant.
    first_reply_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    reopen_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    verify_requested_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    # The customer's own answer to "Did this solve it?", when their app asks.
    # Null is "not asked or not answered", never "no".
    said_solved = db.Column(db.Boolean, nullable=True)

    # Denormalised on purpose: there is no user row here for Cason or Kenali and
    # there should not be. They do not log into this app.
    reporter_name = db.Column(db.String(200), default="")
    reporter_email = db.Column(db.String(200), default="")

    title = db.Column(db.String(300), nullable=False, default="")
    description = db.Column(db.Text, default="")
    detailed_notes = db.Column(db.Text, default="")
    # The screen they were standing on, captured rather than typed.
    source_label = db.Column(db.String(200), default="")
    source_path = db.Column(db.String(500), default="")

    category = db.Column(db.String(20), nullable=False, default="bug")
    status = db.Column(db.String(20), nullable=False, default="new", index=True)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    followup_flagged = db.Column(db.Boolean, nullable=False, default=False,
                                 server_default=db.false())
    out_of_scope = db.Column(db.Boolean, nullable=False, default=False,
                             server_default=db.false())

    # The status this client's app was last told about. The drain pushes
    # whenever it disagrees with `status`, so marking a ticket resolved here
    # reaches them without my having to type a reply as well.
    #
    # It is also the echo guard: a status arriving FROM their app sets both
    # columns at once, so it never reads as a change of mine and never gets
    # sent straight back. Without that the two sides tell each other the same
    # news forever.
    hub_status_sent = db.Column(db.String(20), nullable=True)

    billing_bucket = db.Column(db.String(20), nullable=False, default="",
                               server_default="")
    billed_minutes = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", back_populates="tickets")
    project = db.relationship("Project", back_populates="tickets")
    business = db.relationship("Business")
    # Cascade is required rather than tidy: ticket_id is NOT NULL on the note,
    # so the default on parent-delete is to null the child FK, which raises and
    # 500s the delete.
    notes = db.relationship("TicketNote", back_populates="ticket",
                            cascade="all, delete-orphan",
                            order_by="TicketNote.created_at")
    expenses = db.relationship("Expense", back_populates="ticket",
                               cascade="all, delete-orphan", lazy="dynamic")
    time_entries = db.relationship("TimeEntry", backref="ticket", lazy="dynamic")
    documents = db.relationship("Document", back_populates="ticket",
                                cascade="all, delete-orphan", lazy="dynamic")

    __table_args__ = (
        # Named, because SQLite batch mode cannot drop an unnamed constraint.
        db.UniqueConstraint("origin", "origin_ticket_id", name="uq_ticket_origin"),
        db.UniqueConstraint("origin", "origin_ref", name="uq_ticket_origin_ref"),
    )

    @property
    def from_desk(self):
        """Read from a business's own support desk, which owns it."""
        return bool(self.origin_ref)

    @property
    def desk_external(self):
        """A desk ticket that another app sent to that desk (J&D's Talent
        Booker on EntertainHQ's). The desk resolves those without a notify
        choice, because their own app tells the reporter."""
        return (self.origin_ref or "").startswith("hub.")

    @property
    def who(self):
        """Whose ticket, for a list: the client, else the business."""
        if self.client is not None:
            return self.client.name
        if self.business is not None:
            return self.business.label
        return ""

    @property
    def display_title(self):
        """What to call this on a list.

        Neither app that feeds this board has a title field: Cason and Kenali
        both type one box and press send, which is the right form to give
        somebody reporting a problem. Asking for a subject line would get
        "help" on half of them. So a title is optional here, and a ticket
        without one is named by its own first sentence rather than by "Untitled".
        """
        if self.title:
            return self.title
        text = " ".join((self.description or "").split())
        if not text:
            return f"Ticket #{self.id}"
        return text if len(text) <= 80 else text[:77] + "..."

    @property
    def full_title(self):
        """The same name with nothing trimmed off it.

        A card that opens replaces the shortened name with this rather than
        printing the whole report underneath the cut-off version of itself.
        For a ticket with no title of its own the two are the same sentence,
        and showing both is showing it twice, once broken.
        """
        if self.title:
            return self.title
        text = " ".join((self.description or "").split())
        return text or f"Ticket #{self.id}"

    @property
    def total_expenses(self):
        # Material expenses only - exclude time-entry-linked billable time rows.
        return sum(e.amount for e in self.expenses if e.time_entry_id is None)

    @property
    def total_hours(self):
        return sum(e.hours for e in self.time_entries)

    @property
    def billed_hours(self):
        return (self.billed_minutes or 0) / 60.0

    @property
    def billed_cost(self):
        """What this ticket is worth at its bucket's rate.

        Unclassified is not free, it is undecided, so it earns nothing here and
        is counted separately wherever this is totalled. Returning 0.0 for both
        is what would quietly present undecided work as a no-charge fix.
        """
        rate = TICKET_BILLING_RATES.get(self.billing_bucket)
        if rate is None:
            return None
        return self.billed_hours * rate

    def unread_for_dev(self):
        """Notes from the reporter that I have not read yet."""
        return sum(1 for n in self.notes if n.read_at is None and not n.is_staff_reply)

    def __repr__(self):
        return f"<Ticket {self.id} {self.category} ({self.status}) {self.origin}>"


class TicketNote(db.Model):
    """One message in the back and forth on a ticket.

    Both directions live in the same table on purpose. A reply recorded only as
    an outbound email leaves the person who raised it with nothing to read and
    nothing to reply to, which is not a conversation. Talent Booker shipped it
    that way first and had to come back for it.

    `is_staff_reply` is stored rather than derived from who wrote it, because
    the answer must not change later. It also has to survive arriving from
    another app, where the author is not a row in this database at all.
    """
    __tablename__ = "ticket_notes"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    author_name = db.Column(db.String(200), default="")
    body = db.Column(db.Text, default="")
    is_staff_reply = db.Column(db.Boolean, nullable=False, default=False)

    # The note's id in the app it came from, so the same note arriving twice is
    # recognised. Null for a note written here.
    origin_note_id = db.Column(db.Integer, nullable=True)
    # When this was successfully pushed back to the client app. Null on a note
    # written here means it is still owed to them, which is what the outbox
    # drains on. Always null for a note that arrived from them.
    delivered_at = db.Column(db.DateTime, nullable=True)
    # When the recipient saw it, the recipient being whoever did not write it.
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    ticket = db.relationship("Ticket", back_populates="notes")

    __table_args__ = (
        db.UniqueConstraint("ticket_id", "origin_note_id", name="uq_note_origin"),
    )

    def __repr__(self):
        return f"<TicketNote {self.id} on Ticket {self.ticket_id}>"


class SupportApp(db.Model):
    """One app whose tickets reach the support board, and its links.

    Two kinds. A HUB app is a client's app speaking the signed ticket hub
    (hub.py): its credentials stay on its Client row, and this row only adds
    the quick links. A DESK app is one of Michael's own businesses with a
    support desk of its own (EntertainHQ, Data Dungeon): the desk owns its
    tickets, and the board reads them and answers them through the desk's API
    door (support_service.py), exactly as a click on that desk would.

    Rows are made on first sight from the defaults in support_service.DEFAULTS
    and then edited on the support board, never the other way round.
    """

    __tablename__ = "support_apps"

    id = db.Column(db.Integer, primary_key=True)
    # The ticket origin it answers for: a client's origin_slug, or the slug the
    # board files a desk's tickets under.
    origin = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(120), nullable=False, default="")
    kind = db.Column(db.String(10), nullable=False, default="hub", server_default="hub")
    business_id = db.Column(db.Integer,
                            db.ForeignKey("businesses.id", ondelete="SET NULL",
                                          name="fk_support_apps_business_id"),
                            nullable=True, index=True)
    support_url = db.Column(db.String(300), default="")
    admin_url = db.Column(db.String(300), default="")
    site_url = db.Column(db.String(300), default="")
    status_url = db.Column(db.String(300), default="")
    # The desk's API door: where it answers, the bearer key (typed here once
    # and never shown again), and the desk login a call acts for.
    desk_url = db.Column(db.String(300), default="")
    desk_key = db.Column(SealedText(), nullable=True)
    desk_acting_for = db.Column(db.String(200), default="")
    # An app whose tickets now arrive through another app's desk (J&D's Talent
    # Booker sends to EntertainHQ's since 2026-11-01). The board stops asking
    # it directly, so each ticket is shown once.
    moved_to = db.Column(db.String(40), default="")
    # Whether Michael supports this app at all. An app wired to the hub during
    # a build that was never contracted (Robinson & Co., 2026-11-04: "there
    # would also be no tickets even possible on Robinson and Co") is not a
    # support target: no tile, no count, its rows kept but off the board.
    supported = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    pulled_at = db.Column(db.DateTime, nullable=True)
    pull_note = db.Column(db.String(300), default="")
    sort_order = db.Column(db.Integer, nullable=False, default=100, server_default="100")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business")

    __table_args__ = (
        db.UniqueConstraint("origin", name="uq_support_apps_origin"),
    )

    @property
    def is_desk(self):
        return self.kind == "desk"

    @property
    def on_board(self):
        """A tile, counts and rows: supported, and not moved to another desk."""
        return bool(self.supported) and not self.moved_to

    @property
    def desk_secret(self):
        """The key typed on the board, else a variable on the service named
        DESK_KEY_<ORIGIN> (DESK_KEY_ENTERTAINHQ), so connecting a desk never
        waits on somebody pasting a key."""
        import os
        if self.desk_key:
            return self.desk_key
        return os.environ.get("DESK_KEY_" + (self.origin or "").upper().replace("-", "_"), "")

    @property
    def desk_ready(self):
        return bool(self.is_desk and self.desk_url and self.desk_secret and self.desk_acting_for)

    @property
    def links(self):
        """The quick links, in the order the tile shows them, only those set."""
        out = []
        for key, label in (("support_url", "Support desk"), ("admin_url", "Admin"),
                           ("site_url", "Live site"), ("status_url", "Status page")):
            url = getattr(self, key) or ""
            if url:
                out.append((key, label, url))
        return out

    def __repr__(self):
        return f"<SupportApp {self.origin} ({self.kind})>"


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    time_entry_id = db.Column(db.Integer, db.ForeignKey("time_entries.id", ondelete="CASCADE"), nullable=True, unique=True)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, default="")
    category = db.Column(db.String(50), default="misc")
    date = db.Column(db.Date, nullable=False, default=lambda: date.today())
    receipt_filename = db.Column(db.String(300), nullable=True)
    receipt_original_name = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Recurring expense fields
    is_recurring = db.Column(db.Boolean, default=False)
    frequency = db.Column(db.String(20), nullable=True)  # weekly, biweekly, monthly, quarterly, yearly
    recurring_end_date = db.Column(db.Date, nullable=True)
    next_due_date = db.Column(db.Date, nullable=True)
    parent_expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    # Whose books it is in. Michael, 2026-11-03: two companies' expenses on
    # one board, "so that way I'm not accidentally double counting". Null is
    # never written: the before_insert listener below fills in the business
    # the board bills from, so every path that makes an expense (a form, a
    # sync, the guidance door, a recurring child) lands in somebody's books.
    # A division (a DBA) may be named here; its tax is its parent's.
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="SET NULL", name="fk_expenses_business_id"),
        nullable=True, index=True)
    # An owner who paid it out of their own pocket, by name. The company's
    # books carry the expense AND the same amount as that owner putting money
    # in, because that is what it was: EntertainHQ's first $599.86 (its LLC
    # filing, Claude, Twilio, Google Play) went on Michael's own card.
    paid_by = db.Column(db.String(120), nullable=True)
    # The part of this charge that was the state's money and not a cost.
    # `amount` is always the expense, so every total in the app is right
    # without knowing this exists; `charged` is what left the bank, and only
    # the things that match a charge against a bank line or a receipt read it.
    # Set by books_service.settle_sales_tax and nowhere else.
    sales_tax_remitted = db.Column(db.Float, nullable=False, default=0.0, server_default="0")
    sales_tax_filing_id = db.Column(db.Integer, db.ForeignKey(
        "sales_tax_filings.id", ondelete="SET NULL", name="fk_expenses_sales_tax_filing_id"),
        nullable=True, index=True)
    # The bank line this expense is part of. Only the bank makes an expense
    # (docs/finances_plan.md item 5, 2026-11-04): a line from a vendor whose
    # report splits its bill across projects (Railway, Cloudflare) books one
    # row per share, every one carrying the line, and the shares add up to
    # what left the bank. `cost_entry_id` is the vendor row the share follows.
    # No relationship on either on purpose: expenses and bank lines already
    # point at each other through bank_transactions.expense_id, and a second
    # pair of relationships makes the flush order a cycle.
    bank_line_id = db.Column(db.Integer, db.ForeignKey(
        "bank_transactions.id", ondelete="SET NULL", name="fk_expenses_bank_line_id",
        use_alter=True), nullable=True, index=True)
    cost_entry_id = db.Column(db.Integer, db.ForeignKey(
        "service_cost_entries.id", ondelete="SET NULL", name="fk_expenses_cost_entry_id",
        use_alter=True), nullable=True, index=True)

    business = db.relationship("Business", foreign_keys=[business_id])
    sales_tax_filing = db.relationship("SalesTaxFiling", foreign_keys=[sales_tax_filing_id])
    client = db.relationship("Client", backref="expenses")
    project = db.relationship("Project", backref="expenses")
    ticket = db.relationship("Ticket", back_populates="expenses")
    time_entry = db.relationship("TimeEntry", backref=db.backref(
        "expense", uselist=False, cascade="all, delete-orphan"))
    children = db.relationship("Expense", backref=db.backref("parent_expense", remote_side="Expense.id"), lazy="dynamic")

    @property
    def charged(self):
        """What actually left the bank for this: the expense plus any sales
        tax it carried to the state. A bank line and a receipt both state
        this figure, so matching reads this and never `amount`."""
        return round((self.amount or 0.0) + (self.sales_tax_remitted or 0.0), 2)

    @property
    def sales_tax_note(self):
        """How a sales tax payment breaks down, for the row that shows only
        what it cost. The accountant reads this off the export."""
        remitted = self.sales_tax_remitted or 0.0
        if not remitted:
            return ""
        parts = [f"${remitted:,.2f} sales tax"]
        paid = (self.sales_tax_filing.amount_paid or 0.0) if self.sales_tax_filing else self.charged
        penalties, card = round(paid - remitted, 2), round(self.charged - paid, 2)
        if penalties > 0:
            parts.append(f"${penalties:,.2f} penalties and interest")
        if card > 0:
            parts.append(f"${card:,.2f} card fee")
        return f"${self.charged:,.2f} charged: " + ", ".join(parts)

    @property
    def is_auto_generated(self):
        return self.time_entry_id is not None

    @property
    def is_recurring_child(self):
        return self.parent_expense_id is not None

    @property
    def frequency_label(self):
        labels = {"weekly": "Weekly", "biweekly": "Bi-weekly", "monthly": "Monthly", "quarterly": "Quarterly", "yearly": "Yearly"}
        return labels.get(self.frequency, "")

    def __repr__(self):
        return f"<Expense ${self.amount} - {self.description}>"


def home_business_id():
    """The business this board bills from: Built by Bean. None before one is
    on file, which only a fresh test database ever is."""
    row = (Business.query.filter_by(sales_source="board", parent_id=None)
           .order_by(Business.id).first())
    if row is None:
        row = Business.query.filter_by(parent_id=None).order_by(Business.id).first()
    return row.id if row else None


@db.event.listens_for(_OrmSession, "before_flush")
def _converted_lead_follows_its_client(session, flush_context, instances):
    """A lead that became a client shows the client's stage, whatever moved it.

    It was pinned at In conversation for good once converted, while the client
    went on to Contracted and Active client. Every path that moves a client
    (the stage picker, a payment, a reply, a contract) ends in a flush, so the
    lead is moved here rather than in each of them.
    """
    for obj in list(session.dirty):
        if not isinstance(obj, Client):
            continue
        history = db.inspect(obj).attrs.stage.history
        if not history.has_changes():
            continue
        with session.no_autoflush:
            for lead in Lead.query.filter_by(client_id=obj.id).all():
                if lead.stage != obj.stage:
                    lead.stage = obj.stage
                    lead.stage_changed_at = datetime.now(timezone.utc)


@db.event.listens_for(Expense, "before_insert")
def _expense_has_a_business(mapper, connection, target):
    if target.business_id is None and target.parent_expense_id is not None:
        parent = connection.execute(
            db.text("SELECT business_id FROM expenses WHERE id = :i"),
            {"i": target.parent_expense_id}).scalar()
        target.business_id = parent
    if target.business_id is None:
        row = connection.execute(db.text(
            "SELECT id FROM businesses WHERE sales_source = 'board' AND parent_id IS NULL "
            "ORDER BY id LIMIT 1")).scalar()
        if row is None:
            row = connection.execute(db.text(
                "SELECT id FROM businesses WHERE parent_id IS NULL ORDER BY id LIMIT 1")).scalar()
        target.business_id = row


class BankConnection(db.Model):
    """One business's bank, read nightly. Mercury first.

    Michael, 2026-11-03: "I need my expense tracking automated to like the
    highest degree ... broken out specifically by business ... so that way
    I'm not accidentally double counting." Most vendors have no billing API,
    but every dollar a business spends leaves its bank, so the bank is what
    the books are built on: one row per money movement, and nothing else
    may book that money a second time.

    A Mercury token opens one organisation, which is one company, so the
    connection's business IS the attribution for everything it reads. The
    token is read only; it is typed into the business's page by its owner
    and never by anybody on his behalf. `synced_from` is where history
    starts (the books begin in April 2026).
    """

    __tablename__ = "bank_connections"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_bank_connections_business_id"),
        nullable=False, index=True)
    # mercury: read nightly with a token. statement: a card or account with
    # no feed, whose downloaded CSV statements are uploaded (statements.py).
    provider = db.Column(db.String(20), nullable=False, default="mercury")
    label = db.Column(db.String(120), default="")
    # business: the company's own account. personal: an owner's own card,
    # on which only business charges count, each one that owner's money put
    # in; personal purchases are set aside and never reach the books.
    kind = db.Column(db.String(12), nullable=False, default="business", server_default="business")
    owner_name = db.Column(db.String(120), default="")
    # Some card exports show a purchase as a positive number; flipped on
    # import so money out is negative everywhere.
    charges_positive = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    token = db.Column(SealedText(), default="")
    synced_from = db.Column(db.Date, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_ok = db.Column(db.Boolean, nullable=True)
    last_note = db.Column(db.String(300), default="")
    accounts_json = db.Column(db.Text, default="{}")
    # {account id: current balance} as Mercury last reported it, for the
    # monthly close to hold the books against.
    balances_json = db.Column(db.Text, default="{}")
    # A statement source's own reconciliation (statements.py). A checking
    # export carries the balance after every row, so an upload leaves the
    # balance on its newest day and the balance before its oldest row; the
    # lines in between have to add up to the difference, or a statement is
    # missing. A card export carries no balance and these stay empty.
    balance = db.Column(db.Float, nullable=True)
    balance_on = db.Column(db.Date, nullable=True)
    opening_balance = db.Column(db.Float, nullable=True)
    opening_on = db.Column(db.Date, nullable=True)
    # The card or account's last four digits, as the bank's alert emails
    # name it ("(...1234)"). Learned from the first alert whose charge is
    # already on exactly one source, or typed.
    last_four = db.Column(db.String(8), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "bank_connections", cascade="all, delete-orphan"))

    @property
    def balances(self):
        import json
        try:
            return json.loads(self.balances_json or "{}") or {}
        except ValueError:
            return {}

    @property
    def accounts(self):
        """{Mercury account id: its name}, as last read."""
        import json
        try:
            return json.loads(self.accounts_json or "{}") or {}
        except ValueError:
            return {}

    def __repr__(self):
        return f"<BankConnection {self.provider} for business {self.business_id}>"


class VendorRule(db.Model):
    """What a counterparty on a bank line is, learned once and applied for good.

    Written when Michael (or the curator of the review list) settles a line
    and keeps "remember" on. `pattern` is matched against the normalised
    counterparty and bank description; the longest matching pattern wins, so
    "GOOGLE WORKSPACE" beats "GOOGLE". `business_id` is whose expense it is,
    which can differ from whose card paid it: that difference is money one
    company lent the other, and the reports say so. `disposition`:
      expense   an expense in its business's books
      split     an expense split across projects and clients by the
                vendor's own report (Railway, Cloudflare, Claude). It was
                "covered" until 2026-11-04, when the vendor sync wrote the
                expense and the bank line was only evidence
      transfer  money moving between the owner's own accounts
      income    money in
      personal  not a business cost at all
    """

    __tablename__ = "vendor_rules"

    id = db.Column(db.Integer, primary_key=True)
    pattern = db.Column(db.String(120), nullable=False, unique=True)
    vendor = db.Column(db.String(120), default="")
    disposition = db.Column(db.String(12), nullable=False, default="expense")
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="SET NULL", name="fk_vendor_rules_business_id"), nullable=True)
    category = db.Column(db.String(50), default="misc")
    client_id = db.Column(db.Integer, db.ForeignKey(
        "clients.id", ondelete="SET NULL", name="fk_vendor_rules_client_id"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey(
        "projects.id", ondelete="SET NULL", name="fk_vendor_rules_project_id"), nullable=True)
    provider_id = db.Column(db.Integer, db.ForeignKey(
        "service_providers.id", ondelete="SET NULL", name="fk_vendor_rules_provider_id"), nullable=True)
    # For contribution and draw: which owner's money it was, by name, so one
    # rule ("CHASE" is Michael's own account) serves every company he owns.
    owner_name = db.Column(db.String(120), default="")
    # "personal" for a rule learned on an owner's personal card that a
    # purchase is personal: it must never mark the same shop personal on a
    # company card, where the same counterparty can be a business cost.
    applies_to = db.Column(db.String(12), nullable=False, default="all", server_default="all")
    note = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business")
    client = db.relationship("Client")
    project = db.relationship("Project")
    provider = db.relationship("ServiceProvider")

    DISPOSITIONS = (("expense", "Business expense"), ("split", "Split by the vendor's report"),
                    ("contribution", "Money an owner put in"), ("draw", "Money an owner took out"),
                    ("transfer", "Transfer between the company's accounts"), ("income", "Money in"),
                    ("personal", "Personal, not the business"))
    DISPOSITION_LABELS = dict(DISPOSITIONS)

    def __repr__(self):
        return f"<VendorRule {self.pattern} -> {self.disposition}>"


class BankTransaction(db.Model):
    """One line off a business's bank, exactly as the bank reported it.

    Upserted on (connection, external id), because a card charge starts
    pending, changes amount when it settles, and can be cancelled. The
    expense it makes (`expense_id`) is written only once the line has
    settled, rewritten if the bank changes it, and removed if the bank
    voids it. `amount` keeps the bank's sign: negative is money out.
    `disposition` is what it turned out to be (VendorRule's words, plus
    `review` while nobody knows and `void` when the bank cancelled it).
    """

    __tablename__ = "bank_transactions"
    __table_args__ = (
        db.UniqueConstraint("connection_id", "external_id", name="uq_bank_transactions_connection_external"),
    )

    id = db.Column(db.Integer, primary_key=True)
    connection_id = db.Column(db.Integer, db.ForeignKey(
        "bank_connections.id", ondelete="CASCADE", name="fk_bank_transactions_connection_id"),
        nullable=False, index=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_bank_transactions_business_id"),
        nullable=False, index=True)
    external_id = db.Column(db.String(80), nullable=False)
    account_id = db.Column(db.String(80), default="")
    account_name = db.Column(db.String(120), default="")
    status = db.Column(db.String(12), default="")
    kind = db.Column(db.String(40), default="")
    amount = db.Column(db.Float, nullable=False)
    occurred_on = db.Column(db.Date, nullable=False, index=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    counterparty = db.Column(db.String(200), default="")
    description = db.Column(db.String(300), default="")
    note = db.Column(db.Text, default="")
    merchant_category = db.Column(db.String(80), default="")
    bank_category = db.Column(db.String(60), default="")
    card_id = db.Column(db.String(60), default="")
    link = db.Column(db.String(300), default="")
    disposition = db.Column(db.String(12), nullable=False, default="review", index=True)
    rule_id = db.Column(db.Integer, db.ForeignKey(
        "vendor_rules.id", ondelete="SET NULL", name="fk_bank_transactions_rule_id"), nullable=True)
    owner_name = db.Column(db.String(120), default="")
    expense_id = db.Column(db.Integer, db.ForeignKey(
        "expenses.id", ondelete="SET NULL", name="fk_bank_transactions_expense_id"), nullable=True)
    suggestion_json = db.Column(db.Text, nullable=True)
    raw_json = db.Column(db.Text, default="{}")
    decided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    connection = db.relationship("BankConnection", backref=db.backref(
        "transactions", lazy="dynamic", cascade="all, delete-orphan"))
    business = db.relationship("Business")
    rule = db.relationship("VendorRule")
    expense = db.relationship("Expense", foreign_keys=[expense_id],
                              backref=db.backref("bank_lines", lazy="dynamic",
                                                 foreign_keys="BankTransaction.expense_id"))

    @property
    def suggestion(self):
        import json
        try:
            return json.loads(self.suggestion_json) if self.suggestion_json else None
        except ValueError:
            return None

    def __repr__(self):
        return f"<BankTransaction {self.occurred_on} {self.amount} {self.counterparty}>"


class CardAlert(db.Model):
    """One per-transaction alert email from the bank (Chase's "a card
    transaction higher than $0.00"), read out of a receipt mailbox.

    It becomes a provisional bank line on the statement source whose last
    four digits it names, so the books are current the day the card is
    used; the downloaded statement later folds over it by date and amount
    (statements.py). One whose card is not known yet waits here until a
    source learns its last four.
    """

    __tablename__ = "card_alerts"
    __table_args__ = (
        db.UniqueConstraint("mailbox_id", "message_key", name="uq_card_alerts_mailbox_message"),
    )

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer, db.ForeignKey(
        "receipt_mailboxes.id", ondelete="CASCADE", name="fk_card_alerts_mailbox_id"),
        nullable=False, index=True)
    message_key = db.Column(db.String(200), nullable=False)
    last_four = db.Column(db.String(8), default="")
    occurred_on = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)  # the bank's sign: money out is negative
    merchant = db.Column(db.String(200), default="")
    subject = db.Column(db.String(300), default="")
    line_id = db.Column(db.Integer, db.ForeignKey(
        "bank_transactions.id", ondelete="SET NULL", name="fk_card_alerts_line_id"),
        nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ExpenseTag(db.Model):
    """What a session knows about a charge before the bank does.

    `log_expense` on the door wrote an Expense until 2026-11-04; now only the
    bank line makes one (docs/finances_plan.md item 8), so a session leaves
    this instead: the amount, the vendor, and the client and project it was
    for. The bank line for that charge takes it when it arrives (same amount
    to the cent, within `bank_feed.TAG_DAYS`), and its expense lands on the
    right project with nothing typed. One no line has taken in ten days is a
    Needs attention row: the charge went on a card the board cannot see, or
    never happened.
    """

    __tablename__ = "expense_tags"

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    occurred_on = db.Column(db.Date, nullable=False, index=True)
    vendor = db.Column(db.String(200), default="")
    description = db.Column(db.String(500), default="")
    category = db.Column(db.String(50), default="misc")
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="SET NULL", name="fk_expense_tags_business_id"),
        nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey(
        "clients.id", ondelete="SET NULL", name="fk_expense_tags_client_id"), nullable=True, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey(
        "projects.id", ondelete="SET NULL", name="fk_expense_tags_project_id"), nullable=True, index=True)
    paid_by = db.Column(db.String(120), nullable=True)
    source = db.Column(db.String(120), default="")
    line_id = db.Column(db.Integer, db.ForeignKey(
        "bank_transactions.id", ondelete="SET NULL", name="fk_expense_tags_line_id"),
        nullable=True, index=True)
    taken_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business")
    client = db.relationship("Client")
    project = db.relationship("Project")
    line = db.relationship("BankTransaction")

    def __repr__(self):
        return f"<ExpenseTag {self.occurred_on} {self.amount} {self.vendor}>"


class BooksFlag(db.Model):
    """One thing the books need from Michael, worked out by the nightly run
    (books_upkeep.py) and shown as one Needs attention row.

    Kept rather than computed on the page, because the sidebar badge is
    built on every page the board draws, and a month's books read Stripe
    live: a check that costs seconds belongs to the night. `kind` is what
    it is (month, receipt_no_line, recurring_unclaimed), `key` makes it one
    row per company or month, and `items_json` is the detail the books'
    checks page lists.
    """

    __tablename__ = "books_flags"
    __table_args__ = (
        db.UniqueConstraint("kind", "key", name="uq_books_flags_kind_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False)
    key = db.Column(db.String(80), nullable=False, default="")
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_books_flags_business_id"),
        nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default="")
    detail = db.Column(db.String(300), default="")
    link = db.Column(db.String(300), default="")
    count = db.Column(db.Integer, nullable=False, default=0)
    items_json = db.Column(db.Text, default="[]")
    checked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business")

    @property
    def items(self):
        import json
        try:
            return json.loads(self.items_json or "[]") or []
        except ValueError:
            return []


class BusinessOwner(db.Model):
    """Who owns a company, and how much of it.

    A single-member LLC (Built by Bean) is reported on its owner's own
    return; a multi-member one (EntertainHQ, three members) files a
    partnership return and gives each member a K-1, so the books have to say
    what each member put in and took out. The shares are typed on the
    business's page from the company's own paperwork, never guessed.
    """

    __tablename__ = "business_owners"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_business_owners_business_id"),
        nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    share_percent = db.Column(db.Float, nullable=True)
    note = db.Column(db.String(300), default="")
    # The person on the business's org this owner is (org_service links them
    # by name). Null for an owner nobody has put on the org yet.
    person_id = db.Column(db.Integer, db.ForeignKey(
        "org_people.id", ondelete="SET NULL", name="fk_business_owners_person_id"),
        nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "owners", cascade="all, delete-orphan", order_by="BusinessOwner.id"))

    def __repr__(self):
        return f"<BusinessOwner {self.name} {self.share_percent}%>"


# ── Org: the people of each business ───────────────────────
#
# Michael, 2026-11-04: Team becomes Org, "a place where I can see all my orgs
# for each business ... ensure that org pages communicate properly between
# apps". The board is the ONE store for every business's org (his pick), the
# way it is for sales tax: EntertainHQ's admin Organization page reads and
# saves these rows over the hub (org_service.py, /api/hub/org*), so the two
# never hold two copies. Every row carries `version`; a save names the version
# it read and is refused if the row moved since, so neither side ever writes
# over an edit it did not see. `app_ref` is the row's id in the app it came
# from ("entertainhq:12"), so the one-time import is keyed on ids that do not
# move.

org_person_depts = db.Table(
    "org_person_depts",
    db.Column("person_id", db.Integer, db.ForeignKey(
        "org_people.id", ondelete="CASCADE", name="fk_org_person_depts_person_id"), primary_key=True),
    db.Column("dept_id", db.Integer, db.ForeignKey(
        "org_departments.id", ondelete="CASCADE", name="fk_org_person_depts_dept_id"),
        primary_key=True, index=True),
)


class OrgPerson(db.Model):
    __tablename__ = "org_people"
    __table_args__ = (
        db.UniqueConstraint("business_id", "app_ref", name="uq_org_people_business_app_ref"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_org_people_business_id"),
        nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default="")
    title = db.Column(db.String(120), default="")
    email = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    supervisor_id = db.Column(db.Integer, db.ForeignKey(
        "org_people.id", ondelete="SET NULL", name="fk_org_people_supervisor_id"),
        nullable=True, index=True)
    app_ref = db.Column(db.String(60), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "org_people", cascade="all, delete-orphan", order_by="OrgPerson.name"))
    supervisor = db.relationship("OrgPerson", remote_side=[id], backref="reports")
    departments = db.relationship("OrgDepartment", secondary=org_person_depts,
                                  order_by="OrgDepartment.sort", backref="people")

    @property
    def initials(self):
        words = [w for w in (self.name or "").split() if w][:2]
        return "".join(w[0] for w in words).upper() or "?"


class OrgDepartment(db.Model):
    __tablename__ = "org_departments"
    __table_args__ = (
        db.UniqueConstraint("business_id", "app_ref", name="uq_org_departments_business_app_ref"),
    )

    TONES = ("gold", "blue", "sky", "teal", "green", "amber", "red", "gray")

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_org_departments_business_id"),
        nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    tone = db.Column(db.String(12), nullable=False, default="gold")
    sort = db.Column(db.Integer, nullable=False, default=0)
    app_ref = db.Column(db.String(60), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    business = db.relationship("Business", backref=db.backref(
        "org_departments", cascade="all, delete-orphan",
        order_by="(OrgDepartment.sort, OrgDepartment.id)"))


class OrgResponsibility(db.Model):
    """A standing duty, not a task with a due date: whose it is, and the one
    department it belongs to. Unassigned is an owner of null."""

    __tablename__ = "org_responsibilities"
    __table_args__ = (
        db.UniqueConstraint("business_id", "app_ref", name="uq_org_responsibilities_business_app_ref"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_org_responsibilities_business_id"),
        nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, default="")
    owner_id = db.Column(db.Integer, db.ForeignKey(
        "org_people.id", ondelete="SET NULL", name="fk_org_responsibilities_owner_id"),
        nullable=True, index=True)
    dept_id = db.Column(db.Integer, db.ForeignKey(
        "org_departments.id", ondelete="SET NULL", name="fk_org_responsibilities_dept_id"),
        nullable=True, index=True)
    sort = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.String(200), default="")
    app_ref = db.Column(db.String(60), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "org_responsibilities", cascade="all, delete-orphan",
        order_by="(OrgResponsibility.sort, OrgResponsibility.id)"))
    owner = db.relationship("OrgPerson", backref="responsibilities")
    department = db.relationship("OrgDepartment", backref="responsibilities")


class OrgState(db.Model):
    """What the board knows about one business's org beyond its rows: the
    logins its own app last reported (each app's logins are its own truth),
    when, and when the org was last imported and last edited, which is what
    keeps a late import from writing over an edit made since."""

    __tablename__ = "org_state"

    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_org_state_business_id"), primary_key=True)
    app_logins_json = db.Column(db.Text, default="[]")
    reported_at = db.Column(db.DateTime, nullable=True)
    imported_at = db.Column(db.DateTime, nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)


class StripeActivity(db.Model):
    """One line of a company's Stripe balance, exactly as Stripe reported it.

    A charge is a sale on the day the customer paid, gross; a refund takes
    one back; `fee` is what Stripe kept; a payout is the company's own money
    leaving Stripe for its bank. Upserted on Stripe's id so a read can be
    repeated (stripe_books.py).
    """

    __tablename__ = "stripe_activity"
    __table_args__ = (
        db.UniqueConstraint("business_id", "external_id", name="uq_stripe_activity_business_external"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_stripe_activity_business_id"),
        nullable=False, index=True)
    external_id = db.Column(db.String(80), nullable=False)
    created_on = db.Column(db.Date, nullable=False, index=True)
    category = db.Column(db.String(40), default="")
    kind = db.Column(db.String(40), default="")
    amount = db.Column(db.Float, nullable=False, default=0.0)
    fee = db.Column(db.Float, nullable=False, default=0.0)
    net = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(8), default="usd")
    description = db.Column(db.String(300), default="")


class MonthClose(db.Model):
    """A month of one company's books, declared finished.

    Pressed on the monthly close page once every bank line is sorted, every
    expense has its receipt and the bank's balance agrees; the figures it
    was closed on are kept, so a change to a closed month afterwards shows
    as a difference rather than silently moving a number the accountant
    already has.
    """

    __tablename__ = "month_closes"
    __table_args__ = (
        db.UniqueConstraint("business_id", "month", name="uq_month_closes_business_month"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_month_closes_business_id"),
        nullable=False, index=True)
    month = db.Column(db.Date, nullable=False)  # the first of the month
    expenses_total = db.Column(db.Float, nullable=False, default=0.0)
    income_total = db.Column(db.Float, nullable=False, default=0.0)
    closed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    note = db.Column(db.String(300), default="")

    business = db.relationship("Business")


class ReceiptMailbox(db.Model):
    """A mailbox the board reads for receipts.

    Michael's receipts land in three inboxes (his own Gmail, EntertainHQ's
    and Built by Bean's), and none of them is tidy. Each is opened read only
    over IMAP with an app password its owner made and typed on the Books
    page, and only mail that looks like a receipt or invoice is read.
    `business_id` is the company whose receipts usually arrive there; a
    receipt still attaches to whichever company's expense it matches.
    """

    __tablename__ = "receipt_mailboxes"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="SET NULL", name="fk_receipt_mailboxes_business_id"), nullable=True)
    address = db.Column(db.String(200), nullable=False, unique=True)
    imap_host = db.Column(db.String(120), nullable=False, default="imap.gmail.com")
    password = db.Column(SealedText(), default="")
    read_from = db.Column(db.Date, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_ok = db.Column(db.Boolean, nullable=True)
    last_note = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business")


class Receipt(db.Model):
    """One receipt or invoice email, and the expense it is proof of.

    Matched on the amount to the cent within a few days of the charge; the
    file (the PDF it carried, or the message itself as HTML) is copied onto
    the expense as its receipt. A receipt that matches nothing waits, because
    it may be a charge on a card whose history is not in yet, or a personal
    purchase that never belonged in the books.
    """

    __tablename__ = "receipts"
    __table_args__ = (
        db.UniqueConstraint("mailbox_id", "message_key", name="uq_receipts_mailbox_message"),
    )

    id = db.Column(db.Integer, primary_key=True)
    mailbox_id = db.Column(db.Integer, db.ForeignKey(
        "receipt_mailboxes.id", ondelete="CASCADE", name="fk_receipts_mailbox_id"),
        nullable=False, index=True)
    message_key = db.Column(db.String(200), nullable=False)
    sender = db.Column(db.String(200), default="")
    vendor = db.Column(db.String(120), default="")
    subject = db.Column(db.String(300), default="")
    received_on = db.Column(db.Date, nullable=True, index=True)
    amount = db.Column(db.Float, nullable=True)
    filename = db.Column(db.String(300), nullable=True)
    original_name = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(12), nullable=False, default="unmatched", index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey(
        "expenses.id", ondelete="SET NULL", name="fk_receipts_expense_id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    mailbox = db.relationship("ReceiptMailbox", backref=db.backref(
        "receipts", lazy="dynamic", cascade="all, delete-orphan"))
    expense = db.relationship("Expense")


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    date = db.Column(db.Date, nullable=False, default=lambda: date.today())
    hours = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, default="")
    rate_type = db.Column(db.String(20), nullable=False, default="maintenance")
    # The Claude Code session a SessionEnd hook measured this entry from,
    # 2026-11-04 to 11-05, and the stretches it counted. Nothing writes either
    # now: Claude never logs time, and the hook and the door it posted to are
    # gone. Kept because they are how an entry a session made is told apart
    # from one a person tracked.
    session_ref = db.Column(db.String(80), nullable=True, unique=True,
                            index=True)
    spans_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def rate(self):
        rates = {"maintenance": 100.0, "new_feature": 200.0, "mvp_build": 0.0}
        return rates.get(self.rate_type, 0.0)

    @property
    def is_free_maintenance(self):
        if self.rate_type == "maintenance" and self.project:
            end = self.project.free_maintenance_end
            if end and self.date <= end:
                return True
        return False

    @property
    def cost(self):
        if self.rate_type == "mvp_build":
            return 0.0
        if self.is_free_maintenance:
            return 0.0
        return self.hours * self.rate

    def __repr__(self):
        return f"<TimeEntry {self.hours}h @ {self.rate_type}>"


class TimerSession(db.Model):
    """A live start/stop working-session timer. At most one active timer per user.

    Elapsed time accumulates across pause/resume: while running, elapsed is
    ``accumulated_seconds`` plus the time since ``last_resumed_at``; while paused,
    elapsed is frozen at ``accumulated_seconds``. Stopping converts elapsed time
    into a TimeEntry.
    """
    __tablename__ = "timer_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, unique=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    rate_type = db.Column(db.String(20), nullable=False, default="maintenance")
    description = db.Column(db.Text, default="")
    accumulated_seconds = db.Column(db.Integer, default=0, nullable=False)
    is_paused = db.Column(db.Boolean, default=False, nullable=False)
    last_resumed_at = db.Column(db.DateTime, nullable=True)  # UTC; set while running
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref(
        "timer_session", uselist=False, cascade="all, delete-orphan"))
    project = db.relationship("Project", backref=db.backref(
        "timer_sessions", cascade="all, delete-orphan"))

    @property
    def elapsed_seconds(self):
        secs = float(self.accumulated_seconds or 0)
        if not self.is_paused and self.last_resumed_at:
            resumed = self.last_resumed_at
            if resumed.tzinfo is None:
                resumed = resumed.replace(tzinfo=timezone.utc)
            secs += (datetime.now(timezone.utc) - resumed).total_seconds()
        return max(0.0, secs)

    def __repr__(self):
        return f"<TimerSession user={self.user_id} {self.elapsed_seconds:.0f}s>"


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    filename = db.Column(db.String(300), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    ticket = db.relationship("Ticket", back_populates="documents")
    client = db.relationship("Client", backref=db.backref("documents", lazy="dynamic", cascade="all, delete-orphan"))
    project = db.relationship("Project", backref=db.backref("documents", lazy="dynamic", cascade="all, delete-orphan"))

    @property
    def size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def __repr__(self):
        return f"<Document {self.original_name}>"


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    stripe_invoice_id = db.Column(db.String(100), nullable=True, unique=True)
    stripe_invoice_url = db.Column(db.String(500), nullable=True)
    stripe_pdf_url = db.Column(db.String(500), nullable=True)
    invoice_number = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(30), default="draft")
    subtotal = db.Column(db.Float, default=0.0)
    tax = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)
    # Stripe leaves a refunded invoice "paid" with amount_paid untouched, so
    # the money that went back has to be carried beside it.
    amount_refunded = db.Column(db.Float, nullable=False, default=0.0, server_default="0")
    amount_due = db.Column(db.Float, default=0.0)
    due_date = db.Column(db.Date, nullable=True)
    period_start = db.Column(db.Date, nullable=True)
    period_end = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, default="")
    sent_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    # The day the sale happened as far as the state is concerned: when Stripe
    # finalised it, or created it for a draft. created_at is when THIS row was
    # written, which for an invoice imported from Stripe is the day of the
    # import and says nothing about which quarter's return it belongs on.
    issued_on = db.Column(db.Date, nullable=True)
    # An invoice that bills sales tax missed on earlier invoices. It is tax,
    # not a sale, so nothing is owed ON it, and paying it is what clears the
    # client's balance. Mirrored from the Stripe metadata the board writes,
    # so an invoice made here and imported again keeps the flag.
    sales_tax_catchup = db.Column(db.Boolean, nullable=False, default=False,
                                  server_default=db.false())
    # One invoice that the accountant says is not a taxable sale, on a client
    # who otherwise is. Board-owned: an import never touches it.
    sales_tax_exempt = db.Column(db.Boolean, nullable=False, default=False,
                                 server_default=db.false())
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Deleting a client takes its invoices, because invoices.client_id is
    # NOT NULL and there is nowhere for an invoice with no client to sit.
    client = db.relationship("Client", backref=db.backref(
        "invoices", cascade="all, delete-orphan"))
    project = db.relationship("Project", backref="invoices")
    line_items = db.relationship("InvoiceLineItem", back_populates="invoice",
                                 cascade="all, delete-orphan", lazy="dynamic")

    @property
    def earned(self):
        """Earned on this invoice: paid, less its sales tax, less its refunds,
        and nothing from a catch-up invoice. The local reading of
        stripe_service.invoice_earned, so the client page and the dashboard
        cannot disagree."""
        paid = self.amount_paid or 0.0
        if self.status != "paid" or self.sales_tax_catchup or paid <= 0:
            return 0.0
        kept = max(0.0, paid - (self.amount_refunded or 0.0))
        return round(kept * (paid - (self.tax or 0.0)) / paid, 2)

    def __repr__(self):
        return f"<Invoice {self.invoice_number or self.id} - {self.status}>"


class InvoiceLineItem(db.Model):
    __tablename__ = "invoice_line_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    time_entry_id = db.Column(db.Integer, db.ForeignKey("time_entries.id", ondelete="SET NULL"), nullable=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    stripe_line_item_id = db.Column(db.String(100), nullable=True)
    description = db.Column(db.String(500), default="")
    quantity = db.Column(db.Float, default=1.0)
    unit_amount = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    item_type = db.Column(db.String(20), default="time")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    invoice = db.relationship("Invoice", back_populates="line_items")
    time_entry = db.relationship("TimeEntry", backref="invoice_line_items")
    expense = db.relationship("Expense", backref="invoice_line_items")

    def __repr__(self):
        return f"<InvoiceLineItem {self.description} - ${self.total}>"


class StripeWebhookLog(db.Model):
    __tablename__ = "stripe_webhook_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(100), unique=True, nullable=False)
    event_type = db.Column(db.String(100), nullable=False)
    processed = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<StripeWebhookLog {self.event_type}>"


class ServiceProvider(db.Model):
    __tablename__ = "service_providers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    credentials_json = db.Column(db.Text, nullable=True)
    # For a vendor whose API will not report spend: a figure set here once.
    # Never Railway's: its usage is in units, but its bills are readable with
    # an account token and its months are pulled or typed per project.
    monthly_cost = db.Column(db.Float, nullable=True)
    # Day of the month the charge lands, for a flat provider. A vendor whose
    # API reports real charges carries their dates already and leaves this null.
    billing_day = db.Column(db.Integer, nullable=True)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    sync_error = db.Column(db.Text, nullable=True)

    # WHOSE account these credentials open. Null is Built by Bean's own, which
    # is every provider that existed before this column.
    #
    # A vendor account can belong to a CLIENT and sit on the client's card.
    # Twilio is the case it was built for: the runbook says to get onto the
    # client's account and make a key on it, and that the account SID "names
    # whose account is billed". The board read one such account nightly and
    # booked every dollar of it as money this business had spent. It had spent
    # none of it.
    #
    # What changes when this is set: the cost is still recorded and still
    # attributed, because what it costs to run a client's app is worth knowing
    # and is the number a hosting conversation needs. No Expense is written,
    # because an expense is money that left this business.
    account_client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="SET NULL",
                      name="fk_service_providers_account_client_id"),
        nullable=True, index=True)
    # What the vendor itself calls that account, read back from their API on a
    # sync. A SID is not an answer to "whose is this" and nobody can read one.
    account_label = db.Column(db.String(200), nullable=True)

    # Or another of Michael's own businesses. EntertainHQ LLC pays for its own
    # Railway Pro workspace since 2026-09-16 (Michael, 2026-11-01: "a separate
    # pro account for entertainhq specifically"), so its bill is EntertainHQ's
    # money, not Built by Bean's: recorded and attributed like a client's
    # account, never an Expense on this ledger.
    account_business_id = db.Column(
        db.Integer,
        db.ForeignKey("businesses.id", ondelete="SET NULL",
                      name="fk_service_providers_account_business_id"),
        nullable=True, index=True)

    # Which vendor this account is with, as the Vendors page groups it: one
    # tile per vendor, its accounts under it (Michael, 2026-11-05: three
    # Twilio accounts, his own, Kenali's and Cason's). `name` is how the
    # account syncs ("flat" for Claude), never who the vendor is.
    vendor = db.Column(db.String(100), nullable=True)
    # Where the night found it, for an account nobody typed in: "bank: OPENAI"
    # (a business charge a bank rule names) or "code: owner/repo" (a vendor's
    # signature in an app's code). Such an account is `name` "bank" or "code":
    # it never syncs and never books money, the bank line does that.
    discovered_from = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # The types the night writes: nothing to sync, the money is the bank's.
    FOUND_TYPES = ("bank", "code")

    @property
    def vendor_name(self):
        """The vendor as the page groups it: what was set, else the display
        name without its account in brackets ("Railway (EntertainHQ)")."""
        if (self.vendor or "").strip():
            return self.vendor.strip()
        import re as _re
        return _re.sub(r"\s*\(.*\)\s*$", "", self.display_name or "").strip() or self.name

    @property
    def syncs(self):
        return self.name not in self.FOUND_TYPES

    mappings = db.relationship("ServiceMapping", back_populates="provider",
                               cascade="all, delete-orphan", lazy="dynamic")
    cost_entries = db.relationship("ServiceCostEntry", back_populates="provider",
                                   cascade="all, delete-orphan", lazy="dynamic")
    account_client = db.relationship("Client", foreign_keys=[account_client_id])
    account_business = db.relationship("Business", foreign_keys=[account_business_id])

    @property
    def is_ours(self):
        """Whether money spent here is this business's money: not a client's
        account, and not one another of Michael's businesses pays for."""
        return self.account_client_id is None and self.account_business_id is None

    def __repr__(self):
        return f"<ServiceProvider {self.display_name}>"


class ExpenseCorrection(db.Model):
    """A row taken off the books, added to them or changed on them, and why.
    Michael reviews these one by one and an accountant may ask about any of
    them, so nothing is erased: what was removed is kept whole here and the
    migration that did it can put it back to the cent."""
    __tablename__ = "expense_corrections"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(12), nullable=False)  # removed, added, changed
    expense_id = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    reason = db.Column(db.String(300), nullable=False, default="")
    snapshot_json = db.Column(db.Text, nullable=False, default="{}")
    corrected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ServiceMapping(db.Model):
    __tablename__ = "service_mappings"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("service_providers.id", ondelete="CASCADE"), nullable=False)
    resource_identifier = db.Column(db.String(300), nullable=False)
    resource_label = db.Column(db.String(300), default="")
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    split_percentage = db.Column(db.Float, default=100.0)
    monthly_cost = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    provider = db.relationship("ServiceProvider", back_populates="mappings")
    client = db.relationship("Client", backref="service_mappings")
    project = db.relationship("Project", backref="service_mappings")

    def __repr__(self):
        return f"<ServiceMapping {self.resource_identifier} -> {self.client_id}>"


class ServiceCostEntry(db.Model):
    __tablename__ = "service_cost_entries"
    __table_args__ = (
        # mapping_id is in the key so one resource split across two clients
        # writes one row per allocation instead of violating the constraint
        # and killing the sync.
        db.UniqueConstraint("provider_id", "resource_identifier", "period_start", "period_end",
                            "mapping_id", name="uq_service_cost_entry_alloc"),
    )

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("service_providers.id", ondelete="CASCADE"), nullable=False)
    mapping_id = db.Column(db.Integer, db.ForeignKey("service_mappings.id", ondelete="SET NULL"), nullable=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    resource_identifier = db.Column(db.String(300), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    raw_amount = db.Column(db.Float, nullable=False)
    allocated_amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default="USD")
    description = db.Column(db.String(500), default="")
    raw_data_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    provider = db.relationship("ServiceProvider", back_populates="cost_entries")
    mapping = db.relationship("ServiceMapping", backref="cost_entries")
    expense = db.relationship("Expense", foreign_keys=[expense_id],
                              backref=db.backref("service_cost_entry", uselist=False,
                                                 foreign_keys="ServiceCostEntry.expense_id"))

    def __repr__(self):
        return f"<ServiceCostEntry {self.resource_identifier} ${self.allocated_amount}>"


class Playbook(db.Model):
    """The operational runbook for one third party vendor.

    Deliberately not columns on ServiceProvider. A ServiceProvider row exists
    only for a vendor being cost-synced: it carries credentials_json and sync
    state, and it cascade-deletes. Stripe is not even in that list. Editorial
    content that outlives a sync integration does not belong on it, and losing
    a runbook because somebody removed a cost sync would be the wrong outcome.

    The five markdown fields are fixed columns rather than rows in a sections
    table. The consistent shape across every vendor is the entire value of
    this, and fixed columns enforce it without anybody having to build, or
    police, a section editor.
    """

    __tablename__ = "playbooks"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    logo_path = db.Column(db.String(300), default="")
    vendor_url = db.Column(db.String(300), default="")
    # The vendor's own mark, fetched off vendor_url the way an app tile gets
    # its icon (app_icon_service). The seeded runbooks carry hand-picked SVGs
    # in logo_path; one written through the door carries none and never could,
    # because the door takes JSON and a picture is not JSON, so every runbook
    # a session filed was a monogram forever. logo_path still wins where
    # somebody chose a mark: a chosen one beats a scraped favicon. Null means
    # none found or none fetched yet.
    icon_file = db.Column(db.String(120), nullable=True)
    icon_source = db.Column(db.String(500), nullable=True)
    icon_fetched_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    # Applied to every new project without being asked for. GitHub and Railway
    # are on every build, so making somebody tick them each time is a step
    # that only ever has one answer.
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    # What kind of thing this is, which decides how much of it is somebody
    # else's problem. See CATEGORIES.
    category = db.Column(db.String(20), nullable=False, default="service", index=True)
    sort_order = db.Column(db.Integer, default=0)
    one_liner = db.Column(db.String(300), default="")

    client_only_md = db.Column(db.Text, default="")
    access_grant_md = db.Column(db.Text, default="")
    your_steps_md = db.Column(db.Text, default="")
    traps_md = db.Column(db.Text, default="")
    verify_md = db.Column(db.Text, default="")

    # Nullable, and SET NULL rather than CASCADE, so Railway and Twilio can
    # point at their cost-sync rows while Stripe, which has none, still gets a
    # playbook, and deleting a provider takes its costs and not its runbook.
    service_provider_id = db.Column(
        db.Integer,
        db.ForeignKey("service_providers.id", ondelete="SET NULL", name="fk_playbooks_service_provider_id"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # What this vendor looks like in a codebase: the Product.presence_*
    # mechanism, reused (audit_repos.compile_signature). A line matching
    # presence_pattern in a file matching presence_globs means the repo uses
    # the vendor, and the nightly map check files a gap when a business's
    # map has no node for it (map_checks.py). presence_fixture is a line the
    # pattern MUST match, or the signature is skipped as broken.
    presence_pattern = db.Column(db.Text, nullable=True)
    presence_globs = db.Column(db.String(300), nullable=True)
    presence_exclude = db.Column(db.String(300), nullable=True)
    presence_fixture = db.Column(db.Text, nullable=True)

    service_provider = db.relationship("ServiceProvider", backref="playbooks")

    # The three shapes a third party comes in, in the order you meet them on a
    # build. One list, so the index, the edit form and the sort cannot disagree
    # about what the categories are or which comes first.
    #
    # The axis is how much of it is somebody else's to do. Twilio is an account
    # in the client's name with a carrier approving it; the YouTube API is a
    # key and a quota. Sorting those together buried the fact that one of them
    # takes a fortnight.
    CATEGORIES = (
        ("service", "Services",
         "An account in someone else's name, usually the client's, with money "
         "or a legal identity attached. The slow ones: there is a person, and "
         "often an approval, between you and working software."),
        ("infrastructure", "Infrastructure",
         "Where the code lives, runs and gets watched. Yours to drive, and "
         "largely invisible to the client until it breaks."),
        ("api", "APIs",
         "A key and a quota. Bounded, quick, and no relationship to manage."),
    )

    @property
    def category_label(self):
        for value, label, _ in self.CATEGORIES:
            if value == self.category:
                return label
        return self.CATEGORIES[0][1]

    @property
    def category_rank(self):
        """Position in CATEGORIES, for sorting. Unknown values sort last."""
        for i, (value, _, _) in enumerate(self.CATEGORIES):
            if value == self.category:
                return i
        return len(self.CATEGORIES)

    # Heading and column, in reading order. One list, so the detail page, the
    # edit form and any future export cannot disagree about what the five
    # sections are or which order they come in.
    SECTIONS = (
        ("client_only_md", "What only the client can do"),
        ("access_grant_md", "The access grant that ends the back and forth"),
        ("your_steps_md", "What I do once I have access"),
        ("traps_md", "Traps"),
        ("verify_md", "How to verify"),
    )

    @property
    def sections(self):
        """One entry per section, in reading order.

        Carries the field name as well as the heading so a template can key an
        icon off it. Picking one by loop position instead is a silent mismatch
        the day somebody reorders SECTIONS.
        """
        return [
            {"field": field, "heading": heading, "body": getattr(self, field) or ""}
            for field, heading in self.SECTIONS
        ]

    @property
    def initials(self):
        """The monogram shown when there is no logo yet.

        A vendor is usable the moment it is created, rather than waiting on
        somebody to find an SVG for it.
        """
        parts = [p for p in (self.display_name or self.slug or "?").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    @property
    def has_mark(self):
        """Whether there is a picture to show in place of the monogram."""
        return bool(self.logo_path or self.icon_file)

    @property
    def mark_domain(self):
        """The domain to ask for this vendor's mark, or None.

        The console URL when there is one. Otherwise the display name flattened
        to letters and digits with .com after it, which is right for GoDaddy,
        RevenueCat and Mydoma Studio and is only ever used to ask for a picture.
        It is never written back to vendor_url: a guessed address is fine to
        request an icon from and not fine to put on the page as a link.
        """
        url = (self.vendor_url or "").strip()
        if url:
            host = url.split("//", 1)[-1].split("/", 1)[0].split("@")[-1]
            host = host.split(":")[0].strip().lower()
            if "." in host:
                return host
        flat = "".join(c for c in (self.display_name or "") if c.isalnum()).lower()
        return flat + ".com" if flat else None

    @property
    def wants_mark(self):
        """Whether going and looking for one is worth a network call.

        No mark, somewhere to ask, and not asked recently: a vendor that
        publishes nothing must not be re-asked on every press.

        This used to require vendor_url, which meant a runbook filed through
        the door without one was not merely unfetched, it was not even counted
        as missing: the button never offered it and it stayed a monogram with
        nothing on the page saying why.
        """
        if self.has_mark or not self.mark_domain:
            return False
        if self.icon_fetched_at is None:
            return True
        asked = self.icon_fetched_at
        if asked.tzinfo is None:
            asked = asked.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - asked) > timedelta(days=7)

    def __repr__(self):
        return f"<Playbook {self.slug}>"


class TaxSetting(db.Model):
    """What the tax estimate needs to know, as facts rather than as rates.

    Asking for an effective tax rate asks somebody to do the hard part
    themselves. It also goes stale: profit stacked on a salary can straddle a
    bracket, so the rate moves whenever either number does. These are the
    things a person actually knows, and tax_engine derives the rest.
    """

    __tablename__ = "tax_settings"

    id = db.Column(db.Integer, primary_key=True)

    # How the return is filed, which sets the brackets and the deduction.
    filing_status = db.Column(db.String(10), nullable=False, default="single")
    # Salaries already earning elsewhere. Business profit stacks on top of
    # these, so they decide which bracket it lands in.
    your_wages = db.Column(db.Float, nullable=False, default=0.0)
    spouse_wages = db.Column(db.Float, nullable=False, default=0.0)
    other_income = db.Column(db.Float, nullable=False, default=0.0)
    # Federal tax already taken from those salaries. Turns a liability into
    # the thing people actually want to know, which is what is still owed.
    federal_withheld = db.Column(db.Float, nullable=False, default=0.0)

    # A flat rate, correct for Texas at zero and a simplification anywhere
    # with brackets of its own.
    state_tax_rate = db.Column(db.Float, nullable=False, default=0.0)
    # The separate "put this much of every payment away" habit. Sits on gross
    # receipts, so it deliberately over-collects against the real estimate.
    set_aside_rate = db.Column(db.Float, nullable=False, default=30.0)

    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get(cls):
        """The single row, created with defaults the first time it is asked for."""
        row = cls.query.first()
        if row is None:
            row = cls()
            db.session.add(row)
            db.session.commit()
        return row

    @property
    def household_income(self):
        return (self.your_wages or 0) + (self.spouse_wages or 0) + (self.other_income or 0)

    def __repr__(self):
        return f"<TaxSetting {self.filing_status} wages={self.household_income}>"


class SalesTaxSetting(db.Model):
    """The two numbers Texas sales tax on this business comes down to.

    Software sold as a service is a data processing service in Texas, and 20%
    of a data processing charge is exempt, so the tax is the local rate on 80%
    of the bill: 8.25% x 80% = 6.6% of every dollar. Kept as the two facts
    rather than the 6.6, because the rate is the one that changes (a client in
    a city with a different local rate, or the state moving it) and the
    product of the two is not something anybody can check by eye.

    The Stripe tax rate is remembered with the percentage it was made at.
    Stripe will not edit a tax rate's percentage, so a change here makes a new
    one and retires the old, rather than charging the old figure forever.
    """

    __tablename__ = "sales_tax_settings"

    id = db.Column(db.Integer, primary_key=True)
    rate_percent = db.Column(db.Float, nullable=False, default=8.25)
    taxable_share = db.Column(db.Float, nullable=False, default=80.0)
    # Sales before this day are not counted. Null counts everything, which is
    # the honest default: the obligation began with the first sale, whether
    # or not anybody was tracking it.
    count_from = db.Column(db.Date, nullable=True)
    stripe_tax_rate_id = db.Column(db.String(100), nullable=True)
    stripe_tax_rate_percent = db.Column(db.Float, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get(cls):
        row = cls.query.first()
        if row is None:
            row = cls()
            db.session.add(row)
            db.session.commit()
        return row

    @property
    def effective_percent(self):
        """Tax per dollar billed, as a percent. 6.6 at the defaults.

        Rounded to four places because it becomes a Stripe tax rate, and
        8.25 x 0.8 in floating point is 6.6000000000000005.
        """
        return round((self.rate_percent or 0) * (self.taxable_share or 0) / 100.0, 4)

    def __repr__(self):
        return f"<SalesTaxSetting {self.effective_percent}%>"


class Business(db.Model):
    """A company Michael owns, and what the state knows it by.

    The board began as Built by Bean's and is now the command center over
    every business he runs: EntertainHQ LLC is the second, and a partner in
    one of them still works in that business's own admin site. So the facts a
    filing needs live here once, and a business's own app asks for them over
    the hub rather than keeping a copy that drifts.

    The two WebFile numbers are not interchangeable. Sales tax is RT plus six
    digits, franchise tax XT plus six, and eSystems "Assign Tax/Fees" asks for
    the one that matches the tax being linked. On 2026-10-30 the sales tax
    account would not link with anything else, and for a new registration
    the number arrives by mail weeks later, or from 800-252-8880 the same day.

    `sales_source` says where a quarter's sales come from: "board" is the
    invoices on this board (Built by Bean's own), "hub" is the business's app
    answering /api/hub/tax/sales, and "manual" is nothing to compute, so the
    figures are typed when the return is recorded.
    """

    __tablename__ = "businesses"

    SALES_SOURCES = (
        ("board", "This board's invoices"),
        ("hub", "Its own app"),
        ("manual", "Typed in"),
    )
    FREQUENCIES = (("quarterly", "Quarterly"), ("monthly", "Monthly"), ("yearly", "Yearly"))

    id = db.Column(db.Integer, primary_key=True)
    # The legal name, exactly as the Comptroller prints it on a return.
    name = db.Column(db.String(200), nullable=False)
    short_name = db.Column(db.String(80), default="")
    slug = db.Column(db.String(40), nullable=False, unique=True)
    texas_taxpayer_number = db.Column(db.String(11), default="")
    sos_file_number = db.Column(db.String(20), default="")
    # Three dates, three different facts (Michael, 2026-11-02): when it was
    # first an idea, when the LLC was filed with the state, and when it opened
    # for business. A division has no filing of its own, so no formed_on.
    conceived_on = db.Column(db.Date, nullable=True)
    formed_on = db.Column(db.Date, nullable=True)
    launched_on = db.Column(db.Date, nullable=True)
    franchise_tax_webfile = db.Column(db.String(20), default="")

    sales_tax_webfile = db.Column(db.String(20), default="")
    sales_tax_registered_on = db.Column(db.Date, nullable=True)
    # The obligation began with the first taxable sale, whether or not the
    # permit existed yet, so the returns owed are counted from here.
    sales_tax_first_sale = db.Column(db.Date, nullable=True)
    sales_tax_frequency = db.Column(db.String(12), nullable=False, default="quarterly",
                                    server_default="quarterly")
    # Share of a sale that is taxable. 80 for software sold as a service,
    # which Texas taxes as a data processing service with 20% exempt.
    taxable_share = db.Column(db.Float, nullable=False, default=80.0, server_default="80")
    naics_code = db.Column(db.String(10), default="")
    sales_source = db.Column(db.String(12), nullable=False, default="manual",
                             server_default="manual")

    # What the Comptroller's franchise tax search says, read nightly
    # (comptroller.py). Theirs, not typed: a change is flagged
    # (ComptrollerFlag) and the column takes the new value. `franchise_status`
    # is rightToTransactTX, ACTIVE or FORFEITED, and anything but ACTIVE is a
    # loud row on Needs attention. `franchise_report_year` is the last report
    # on file, so this year's May 15 report is done once it catches up.
    ein = db.Column(db.String(12), default="")
    franchise_status = db.Column(db.String(30), default="")
    sos_status = db.Column(db.String(30), default="")
    registered_agent = db.Column(db.String(200), default="")
    registered_office = db.Column(db.String(300), default="")
    mailing_address = db.Column(db.String(300), default="")
    franchise_report_year = db.Column(db.Integer, nullable=True)
    comptroller_checked_at = db.Column(db.DateTime, nullable=True)
    comptroller_note = db.Column(db.String(300), default="")
    # Whether the state's list of active sales tax permits (jrea-zgmq) has
    # this taxpayer number: "found", "none", or blank before the first read.
    # Built by Bean's number found none on 2026-11-04 while it was filing
    # returns, so the board says so in words rather than reading as fine.
    permit_status = db.Column(db.String(10), default="")
    permit_checked_at = db.Column(db.DateTime, nullable=True)
    # A DBA's Assumed Name Certificate runs up to ten years from filing, and
    # the renewal is a deadline (deadlines.py).
    assumed_name_filed_on = db.Column(db.Date, nullable=True)

    # Its own admin site, where a partner in it works.
    admin_url = db.Column(db.String(300), default="")
    # The hub, as Client has it: who it says it is, where it answers, and the
    # secret both ends sign with. Nullable and unique for the same reason as
    # Client.origin_slug: most businesses have no app, and null never collides.
    hub_slug = db.Column(db.String(40), nullable=True, unique=True)
    hub_base_url = db.Column(db.String(300), default="")
    hub_secret = db.Column(SealedText(), default="")
    hub_pulled_at = db.Column(db.DateTime, nullable=True)
    hub_pull_note = db.Column(db.String(300), default="")

    notes = db.Column(db.Text, default="")
    # Its own Stripe account, read into its books (stripe_books.py): a
    # restricted key with read access to the balance, typed by its owner on
    # this business's page and never shown again. Built by Bean's Stripe is
    # read through the app's own key and needs nothing here.
    stripe_key = db.Column(SealedText(), nullable=True)
    stripe_synced_at = db.Column(db.DateTime, nullable=True)
    stripe_ok = db.Column(db.Boolean, nullable=True)
    stripe_note = db.Column(db.String(300), default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # The company this one is a division of, or null for a company of its
    # own. Data Dungeon is the first (Michael, 2026-11-02): it trades under
    # Built by Bean LLC, so it has no taxpayer number, permit or return of its
    # own and its taxable sales go on Built by Bean's return, but it is run as
    # a business and may be spun out one day. So it is a tile of its own on
    # Businesses and is never a row on the returns pages, where a second set
    # of returns for the same LLC would file the same sales twice. One level
    # only: a division has no divisions. SET NULL, so removing the parent
    # leaves the division standing as a company rather than deleting it.
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("businesses.id", ondelete="SET NULL", name="fk_businesses_parent_id"),
        nullable=True,
        index=True,
    )
    parent = db.relationship("Business", remote_side=[id], backref=db.backref(
        "divisions", order_by="Business.name"))

    # Its logo: an image uploaded for it, or the icon of one of its apps on My
    # Apps, which is already fetched and kept (a business is often an app).
    # One or the other: choosing an app's icon removes an uploaded image.
    logo_file = db.Column(db.String(120), nullable=True)
    logo_app_id = db.Column(
        db.Integer,
        db.ForeignKey("app_links.id", ondelete="SET NULL", name="fk_businesses_logo_app_id"),
        nullable=True,
    )
    logo_app = db.relationship("AppLink")
    # For a business whose sales come over the hub: what its app last said
    # it has sold, all time, before tax. The list of businesses shows this
    # rather than wait on somebody else's server; the business's own page
    # asks again when it is old.
    revenue_total = db.Column(db.Float, nullable=True)
    revenue_as_of = db.Column(db.DateTime, nullable=True)

    locations = db.relationship("BusinessLocation", back_populates="business",
                                cascade="all, delete-orphan",
                                order_by="BusinessLocation.opened_on")
    filings = db.relationship("SalesTaxFiling", back_populates="business",
                              cascade="all, delete-orphan")
    documents = db.relationship("BusinessDocument", back_populates="business",
                                cascade="all, delete-orphan",
                                order_by="BusinessDocument.kind, BusinessDocument.id")

    @property
    def label(self):
        return self.short_name or self.name

    @property
    def is_division(self):
        return self.parent_id is not None

    @property
    def map_mark(self):
        """The logo for the middle of its map: uploaded, else its app's icon."""
        from flask import url_for
        if self.logo_file:
            return url_for("businesses.logo", id=self.id)
        if self.logo_app is not None and self.logo_app.icon_file:
            return url_for("apps.icon", id=self.logo_app_id)
        return None

    @property
    def milestone(self):
        """(label, day) for the date the tile leads with, or None.

        Launched is the business's age; before launch it is in the works,
        counted from the idea; formed is the fallback for a company whose
        launch nobody has typed yet. The label always names the date shown,
        so a formation date never reads as a launch.
        """
        if self.launched_on:
            return ("Launched", self.launched_on)
        if self.formed_on and not self.is_division:
            return ("Formed", self.formed_on)
        if self.conceived_on:
            return ("Conceived", self.conceived_on)
        return None

    @property
    def initials(self):
        """Two letters for a business with no logo yet."""
        parts = [p for p in (self.label or "?").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    def location_on(self, day):
        """The place a sale on `day` was made from, or None.

        A return is filed per location, and a sale belongs to the place the
        business was trading from that day: Built by Bean sold from Fort Worth
        until 2026-09-17 and from Paris from the 18th, so September's sales
        split across two lines of the same return.
        """
        for loc in self.locations:
            if loc.opened_on and day < loc.opened_on:
                continue
            if loc.closed_on and day > loc.closed_on:
                continue
            return loc
        return None

    def filing_for(self, year, quarter):
        for f in self.filings:
            if f.year == year and f.quarter == quarter:
                return f
        return None

    def __repr__(self):
        return f"<Business {self.slug}>"


class BusinessLocation(db.Model):
    """One place a business sells from, as its sales tax permit lists it.

    `webfile_number` is the five digit location number WebFile prints beside
    each address on the Taxable Sales page (00001, 00002). It is the Comptroller's
    number, not ours: Paris came out 00001 and Fort Worth 00002 although Fort
    Worth opened first. A location the business has left keeps its row with
    `closed_on`, because the returns that cover its last days still need it;
    `closure_filed` is whether the Comptroller has been told, which is a
    separate step and until it is done WebFile keeps asking for a line for it.
    """

    __tablename__ = "business_locations"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    webfile_number = db.Column(db.String(5), default="")
    label = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(300), default="")
    county = db.Column(db.String(60), default="")
    # Everything above the state's 6.25%: county, city, transit and special
    # districts together. 2.0 for both of Built by Bean's so far.
    local_rate = db.Column(db.Float, nullable=False, default=2.0, server_default="2")
    opened_on = db.Column(db.Date, nullable=True)
    closed_on = db.Column(db.Date, nullable=True)
    closure_filed = db.Column(db.Boolean, nullable=False, default=False,
                              server_default=db.false())
    # From the state's permit list (jrea-zgmq), nightly: the outlet's town,
    # whether it is inside that town's limits (the city rate file only holds
    # towns), and whether the outlet was on the list at the last read. True
    # then False is an outlet that dropped off, which is flagged.
    city = db.Column(db.String(80), default="")
    inside_city_limits = db.Column(db.Boolean, nullable=True)
    permit_listed = db.Column(db.Boolean, nullable=True)
    permit_seen_at = db.Column(db.DateTime, nullable=True)
    # Where `local_rate` came from: blank is the 2.0 every location started
    # with, "typed" is a rate changed by hand (left alone from then on), and
    # "Comptroller Oct26" is that quarter's city rate file (comptroller.read_rates).
    rate_source = db.Column(db.String(40), default="")
    rate_note = db.Column(db.String(200), default="")

    business = db.relationship("Business", back_populates="locations")

    @property
    def total_rate(self):
        return round(6.25 + (self.local_rate or 0), 4)

    def __repr__(self):
        return f"<BusinessLocation {self.webfile_number} {self.label}>"


class BusinessNeed(db.Model):
    """One thing a business has to have: the business playbook, one row each.

    Michael, 2026-11-02: "if I want to create me a new business, I want to be
    able to just have it start to finish every little thing that I need to set
    up." A need is that thing, in the layer a business gets built in (LAYERS
    in business_map), marked essential when every business needs it and
    optional when it is a pathway some take. `fills_with` names the runbooks
    that can fill it, so a hole on a map can say what would fill it.

    Catalogue, not per business: every business's map reads the same list, so
    the holes are counted against one standard and a new business starts from
    the whole of it.
    """

    __tablename__ = "business_needs"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    layer = db.Column(db.String(20), nullable=False, default="operations", index=True)
    essential = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # The business's own thing rather than a vendor's: the app itself, the
    # board it is run from. Nothing to buy, so no runbook to be missing.
    in_house = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    description = db.Column(db.String(400), default="")
    # Runbook slugs, comma separated, in the order to suggest them.
    fills_with = db.Column(db.String(300), default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    @property
    def fill_slugs(self):
        return [s.strip() for s in (self.fills_with or "").split(",") if s.strip()]

    @property
    def suggestions(self):
        """The runbooks that could fill this, by name, where the board has them."""
        if not self.fill_slugs:
            return []
        rows = Playbook.query.filter(Playbook.slug.in_(self.fill_slugs)).all()
        by_slug = {p.slug: p for p in rows}
        return [{"slug": s, "name": by_slug[s].display_name if s in by_slug else s.replace("-", " ").title()}
                for s in self.fill_slugs]

    def __repr__(self):
        return f"<BusinessNeed {self.slug}>"


class BusinessNeedLink(db.Model):
    """A connection that follows once two needs are both filled, and why.

    Payments pay out to the bank; the domain's DNS points at the hosting. The
    why is written once here, so every business whose map has both ends gets
    the line and its explanation without anybody typing it per business.
    """

    __tablename__ = "business_need_links"
    __table_args__ = (
        db.UniqueConstraint("from_need_id", "to_need_id", name="uq_business_need_link"),
    )

    id = db.Column(db.Integer, primary_key=True)
    from_need_id = db.Column(
        db.Integer,
        db.ForeignKey("business_needs.id", ondelete="CASCADE", name="fk_business_need_links_from"),
        nullable=False, index=True)
    to_need_id = db.Column(
        db.Integer,
        db.ForeignKey("business_needs.id", ondelete="CASCADE", name="fk_business_need_links_to"),
        nullable=False, index=True)
    why = db.Column(db.String(300), default="")


class BusinessNode(db.Model):
    """One thing on a business's map: a person, a surface, a service, an outcome.

    Michael, 2026-11-02, after two maps that were vendor inventories: the map
    is "a network of everything that's making this product run", end to end.
    So every kind of thing is a node on one table and every line is an edge
    with its why, and the layout is radial: the business in the middle, the
    SURFACES people touch around it (the marketing site, the app, the
    portals, the phone apps, the status site, the admin board), the SERVICES
    that power each surface behind it, the AUDIENCES who use it on the
    outside, and the OUTCOMES a partner asks about sitting on the lines
    between a person and what answers them.

    `need_id` and `playbook_id` are a service's: the need it fills on the
    business playbook, and its runbook. A surface or a service with a URL
    and no runbook gets its own mark fetched off that URL.
    """

    __tablename__ = "business_nodes"

    KINDS = (
        ("audience", "People"),
        ("surface", "What they use"),
        ("service", "What powers it"),
        ("outcome", "What it delivers"),
    )
    STATUSES = {
        "audience": (),
        "surface": (("live", "Live"), ("down", "Unreachable"), ("building", "Building"), ("planned", "Planned")),
        "service": (("running", "Running"), ("setting_up", "Setting up"), ("planned", "Planned")),
        "outcome": (("delivered", "Delivered"), ("in_progress", "In progress"), ("missing", "Missing")),
    }
    # What a surface is, which picks its glyph when it has no mark of its own.
    SURFACE_KINDS = (
        ("site", "Website"), ("app", "App"), ("portal", "Portal"), ("phone", "Phone app"),
        ("status", "Status site"), ("admin", "Admin"), ("inbox", "Inbox"), ("other", "Other"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("businesses.id", ondelete="CASCADE", name="fk_business_nodes_business_id"),
        nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default="service", server_default="service", index=True)
    name = db.Column(db.String(120), nullable=False, default="")
    # What it is doing for this business, in a sentence: the hover.
    role = db.Column(db.String(400), default="")
    status = db.Column(db.String(12), default="")
    url = db.Column(db.String(300), default="")
    # A surface's shape; empty for the other kinds.
    surface_kind = db.Column(db.String(12), default="")
    need_id = db.Column(
        db.Integer,
        db.ForeignKey("business_needs.id", ondelete="SET NULL", name="fk_business_nodes_need_id"),
        nullable=True, index=True)
    playbook_id = db.Column(
        db.Integer,
        db.ForeignKey("playbooks.id", ondelete="SET NULL", name="fk_business_nodes_playbook_id"),
        nullable=True, index=True)
    icon_file = db.Column(db.String(120), nullable=True)
    icon_source = db.Column(db.String(500), nullable=True)
    icon_fetched_at = db.Column(db.DateTime, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "nodes", cascade="all, delete-orphan", order_by="BusinessNode.sort_order, BusinessNode.id"))
    need = db.relationship("BusinessNeed")
    playbook = db.relationship("Playbook")

    @property
    def display_name(self):
        if self.name:
            return self.name
        if self.playbook is not None:
            return self.playbook.display_name
        return self.need.name if self.need is not None else "?"

    @property
    def initials(self):
        parts = [p for p in (self.display_name or "?").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    @property
    def kind_label(self):
        return dict(self.KINDS).get(self.kind, self.kind)

    @property
    def status_label(self):
        return dict(self.STATUSES.get(self.kind, ())).get(self.status, "")

    @property
    def mark_url(self):
        """Its runbook's mark, else one fetched for this row, else None."""
        from flask import url_for
        pb = self.playbook
        if pb is not None:
            if pb.logo_path:
                return url_for("static", filename=pb.logo_path)
            if pb.icon_file:
                return url_for("playbooks.icon", slug=pb.slug)
        if self.icon_file:
            return url_for("businesses.node_icon", id=self.business_id, nid=self.id)
        return None

    @property
    def wants_mark(self):
        """Worth a network call: no mark, a URL to ask, not asked already."""
        return (self.kind in ("surface", "service") and self.mark_url is None
                and bool((self.url or "").strip()) and self.icon_fetched_at is None)

    @property
    def runbook_url(self):
        from flask import url_for
        return url_for("playbooks.playbook_detail", slug=self.playbook.slug) if self.playbook else ""

    def __repr__(self):
        return f"<BusinessNode {self.kind} {self.display_name!r}>"


class BusinessEdge(db.Model):
    """A line on a business's map, and why it is there."""

    __tablename__ = "business_edges"
    __table_args__ = (
        db.UniqueConstraint("from_node_id", "to_node_id", name="uq_business_edge"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("businesses.id", ondelete="CASCADE", name="fk_business_edges_business_id"),
        nullable=False, index=True)
    from_node_id = db.Column(
        db.Integer,
        db.ForeignKey("business_nodes.id", ondelete="CASCADE", name="fk_business_edges_from"),
        nullable=False, index=True)
    to_node_id = db.Column(
        db.Integer,
        db.ForeignKey("business_nodes.id", ondelete="CASCADE", name="fk_business_edges_to"),
        nullable=False, index=True)
    why = db.Column(db.String(300), default="")

    business = db.relationship("Business", backref=db.backref(
        "edges", cascade="all, delete-orphan", order_by="BusinessEdge.id"))
    from_node = db.relationship("BusinessNode", foreign_keys=[from_node_id])
    to_node = db.relationship("BusinessNode", foreign_keys=[to_node_id])


class SalesTaxFiling(db.Model):
    """One return as it was filed and paid, with WebFile's own numbers.

    Written from the confirmation page, never worked out: the tax, penalty,
    late filing penalty and interest are what the state charged, and the
    figures per location are what was typed. `processing_fee` is the card
    portal's charge on top, which an electronic check does not have ($9.86
    and $16.89 on the first two returns, both paid by card).

    One per business per period. An amended return is filed in WebFile
    against the same period and recorded by editing this row, so the board
    holds what was finally reported.
    """

    __tablename__ = "sales_tax_filings"
    __table_args__ = (
        db.UniqueConstraint("business_id", "year", "quarter", name="uq_sales_tax_filings_period"),
    )

    METHODS = (
        ("electronic check", "Electronic check"),
        ("credit card", "Credit card"),
        ("none", "Filed, not paid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.Integer, nullable=False)
    # As WebFile printed it, which is Central time. A return's date is the
    # day the state says it was filed, not the server's idea of that moment.
    filed_at = db.Column(db.DateTime, nullable=True)
    reference_number = db.Column(db.String(40), default="")
    payment_reference = db.Column(db.String(40), default="")
    trace_number = db.Column(db.String(40), default="")
    payment_method = db.Column(db.String(20), default="electronic check")

    total_sales = db.Column(db.Float, nullable=False, default=0.0)
    taxable_sales = db.Column(db.Float, nullable=False, default=0.0)
    tax_due = db.Column(db.Float, nullable=False, default=0.0)
    penalty = db.Column(db.Float, nullable=False, default=0.0)
    late_filing_penalty = db.Column(db.Float, nullable=False, default=0.0)
    interest = db.Column(db.Float, nullable=False, default=0.0)
    discount = db.Column(db.Float, nullable=False, default=0.0)
    amount_paid = db.Column(db.Float, nullable=False, default=0.0)
    processing_fee = db.Column(db.Float, nullable=False, default=0.0)
    # What was typed per location: [{"number", "label", "total_sales",
    # "taxable_sales", "state_tax", "local_tax"}].
    locations_json = db.Column(db.Text, default="[]")
    notes = db.Column(db.Text, default="")
    recorded_by = db.Column(db.String(80), default="")
    # A return the board drafted from the Comptroller's charge on the bank
    # (comptroller.draft_filings): everything but the reference number, which
    # is the proof it was filed and is still typed (or read from the mail).
    drafted_from_line_id = db.Column(db.Integer, db.ForeignKey(
        "bank_transactions.id", ondelete="SET NULL", name="fk_sales_tax_filings_drafted_from_line_id"),
        nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", back_populates="filings")
    files = db.relationship("SalesTaxFilingFile", back_populates="filing",
                            cascade="all, delete-orphan",
                            order_by="SalesTaxFilingFile.uploaded_at")

    @property
    def period_code(self):
        import sales_tax
        return sales_tax.period_code(self.year, self.quarter)

    @property
    def is_draft(self):
        return not (self.reference_number or "").strip()

    @property
    def penalties(self):
        return round((self.penalty or 0) + (self.late_filing_penalty or 0)
                     + (self.interest or 0) - (self.discount or 0), 2)

    @property
    def total_charged(self):
        return round((self.amount_paid or 0) + (self.processing_fee or 0), 2)

    @property
    def location_rows(self):
        import json
        try:
            rows = json.loads(self.locations_json or "[]")
        except ValueError:
            return []
        return rows if isinstance(rows, list) else []

    def __repr__(self):
        return f"<SalesTaxFiling {self.business_id} {self.year} {self.quarter}>"


class ComptrollerFlag(db.Model):
    """Something the state's records say that changed, for Michael to see once.

    Written by the nightly read (comptroller.py): the registered agent or
    office moved, the standing left ACTIVE, an outlet dropped off the permit
    list, a location's local rate changed in the quarterly file, or the
    taxpayer number stopped (or started) finding a permit. One row per thing
    seen, shown on Needs attention until it is marked seen. Standing that is
    not ACTIVE is ALSO a row that cannot be dismissed while it lasts
    (deadlines.attention_rows), because a forfeited company cannot trade.
    """

    __tablename__ = "comptroller_flags"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="CASCADE", name="fk_comptroller_flags_business_id"),
        nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey(
        "business_locations.id", ondelete="SET NULL", name="fk_comptroller_flags_location_id"),
        nullable=True, index=True)
    # standing, agent, office, mailing, sos, ein, formed, permit, outlet, rate
    kind = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    old_value = db.Column(db.String(300), default="")
    new_value = db.Column(db.String(300), default="")
    seen_at = db.Column(db.DateTime, nullable=True, index=True)
    seen_by = db.Column(db.String(80), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", backref=db.backref(
        "comptroller_flags", cascade="all, delete-orphan", lazy="dynamic"))
    location = db.relationship("BusinessLocation")

    def __repr__(self):
        return f"<ComptrollerFlag {self.kind} {self.title}>"


class DeadlineDone(db.Model):
    """A deadline Michael said is done, for the ones no record can prove.

    The deadline list (deadlines.py) proves what it can by itself: a sales
    tax return by its filing, the franchise report by the Comptroller's
    report year, an estimate by an IRS line on the bank. A 1065, a 1040 or a
    DBA renewal leaves nothing the board can read, so its Done press writes
    one of these, keyed by the deadline's own key, and Undo takes it away.
    """

    __tablename__ = "deadline_done"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True)
    done_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    done_by = db.Column(db.String(80), default="")

    def __repr__(self):
        return f"<DeadlineDone {self.key}>"


class BusinessDocument(db.Model):
    """A company's own paperwork: what LegalZoom filed and the IRS sent back.

    Michael, 2026-11-02: the LLC documents for each business he actually has
    an LLC for, kept on the board rather than in a LegalZoom login. Stored on
    the volume under UPLOAD_FOLDER/business_documents by a random name and
    served under the name it was uploaded with, the same way a return's
    confirmation is.

    `kind` is what the document IS, from KINDS, so the business page can say
    which papers are on file. Texas calls the articles a Certificate of
    Formation (Form 205), which is the name LegalZoom files them under.
    """

    __tablename__ = "business_documents"

    KINDS = (
        ("formation", "Certificate of Formation"),
        ("operating", "Operating Agreement"),
        # The IRS letter with the EIN: a CP 575 when it was assigned, or a
        # 147C asking for it again (EntertainHQ's is a 147C of 2026-10-28).
        ("ein", "IRS EIN letter"),
        # The Comptroller's Texas Sales and Use Tax Permit. business_papers
        # asks for it from a company that collects Texas sales tax.
        ("sales_permit", "Sales and use tax permit"),
        ("organizer", "Organizer statement"),
        ("resolutions", "Resolutions"),
        ("agent", "Registered agent"),
        # What makes a DBA lawful in Texas: the certificate the LLC files to
        # trade under another name, Data Dungeon's being Built by Bean's.
        ("assumed_name", "Assumed Name Certificate"),
        ("franchise", "Franchise tax report"),
        ("other", "Other"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer,
        db.ForeignKey("businesses.id", ondelete="CASCADE", name="fk_business_documents_business_id"),
        nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default="other", server_default="other")
    title = db.Column(db.String(200), default="")
    stored_name = db.Column(db.String(100), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(100), default="application/pdf")
    size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    business = db.relationship("Business", back_populates="documents")

    @property
    def kind_label(self):
        return dict(self.KINDS).get(self.kind, "Other")

    @property
    def label(self):
        return self.title or self.original_name


class SalesTaxFilingFile(db.Model):
    """A confirmation kept with its return: the page WebFile says to print.

    Stored on the volume under UPLOAD_FOLDER/tax_filings by a random name, and
    served back under the name it was uploaded with.
    """

    __tablename__ = "sales_tax_filing_files"

    id = db.Column(db.Integer, primary_key=True)
    filing_id = db.Column(db.Integer, db.ForeignKey("sales_tax_filings.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    stored_name = db.Column(db.String(100), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(100), default="application/pdf")
    size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    filing = db.relationship("SalesTaxFiling", back_populates="files")


# Statuses come from the portal, which is the only place they are decided.
SIGNATURE_STATUS_LABELS = {
    "draft": "Draft",
    "sent": "Out for signature",
    "completed": "Signed",
    "declined": "Declined",
    "voided": "Voided",
}
# Full class strings rather than a colour name spliced into one. Tailwind is
# scanned for whole class names, and a template that builds `bg-{{ x }}-500`
# is a template whose colours silently stop existing.
SIGNATURE_STATUS_COLORS = {
    "draft": "bg-surface-800 text-surface-300",
    "sent": "bg-amber-900/30 text-amber-400",
    "completed": "bg-emerald-900/30 text-emerald-400",
    "declined": "bg-red-900/30 text-red-400",
    "voided": "bg-surface-800 text-surface-400",
}


class SignatureRequest(db.Model):
    """A contract this board sent to the signing portal, and where it went.

    Deliberately thin. The portal owns the envelope: its status, its audit
    chain, its sealed PDF. What is kept here is the join the portal has no way
    to know - which client this was for, which project, which of our documents
    it came from - plus the last status seen, so a list can be drawn without
    waiting on the network first.

    `status` is therefore a cache and nothing more. It is refreshed from the
    portal whenever these pages are opened, and the portal wins every time.
    """

    __tablename__ = "signature_requests"

    id = db.Column(db.Integer, primary_key=True)

    # The portal's own id. Unique because one envelope is one request; a
    # second row for the same envelope would be two answers to one question.
    envelope_id = db.Column(db.String(64), nullable=False, unique=True, index=True)

    title = db.Column(db.String(200), nullable=False)
    # engagement_letter | sow | document - what produced the PDF, so the list
    # can say what was sent without opening it.
    kind = db.Column(db.String(30), nullable=False, default="document")

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    # The unsigned PDF as filed here when it was generated.
    source_document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # The sealed PDF, filed back against the client once everyone has signed.
    signed_document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)

    signer_name = db.Column(db.String(120), nullable=False)
    signer_email = db.Column(db.String(200), nullable=False)
    # The portal's per-signer id, needed to mint a fresh link for them later.
    signer_ref = db.Column(db.String(64), nullable=True)
    # No longer written or read (migration a6c3e19d4b70 emptied it). A signer's
    # link signs in AS them for fourteen days, so Copy link mints a fresh one
    # from signer_ref at the press instead. Kept as a column only so an older
    # deploy rolled back onto this database still loads.
    signing_url = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="sent")
    # Whether the portal actually emailed them, or only wrote to its outbox.
    mail_mode = db.Column(db.String(10), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    # Tidied off the list without being destroyed. The row stays, the
    # envelope is untouched, and a signed contract is still findable, which
    # is why this is a flag and not a delete: what was signed happened.
    archived_at = db.Column(db.DateTime, nullable=True)

    # What the client said when they would not sign it. The portal collects a
    # reason on decline; without this it lived only in an email, which is the
    # one place a negotiation cannot be picked up from later.
    decline_reason = db.Column(db.Text, nullable=True)
    declined_at = db.Column(db.DateTime, nullable=True)

    # The form that produced the document, so a revision starts from what was
    # actually sent rather than from a blank page and somebody's memory.
    form_json = db.Column(db.Text, nullable=True)

    # What the document changes on the board once it is SIGNED, not sent:
    # the client and package to contracted, the project's fee, budget and
    # dates, the package's products as sales (contract_effects.py). Kept
    # here as the proposal, applied on `completed`, and `undo_json` is what
    # to put back on a decline or a void. A contract nobody signed takes
    # nothing (Michael's decision on audit item 6, 2026-11-04).
    effects_json = db.Column(db.Text, nullable=True)
    undo_json = db.Column(db.Text, nullable=True)
    effects_applied_at = db.Column(db.DateTime, nullable=True)

    # Set when this document replaces one the client asked to change, so the
    # back-and-forth reads as a thread instead of four unrelated envelopes.
    revision_of_id = db.Column(
        db.Integer,
        db.ForeignKey("signature_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_of = db.relationship(
        "SignatureRequest", remote_side="SignatureRequest.id",
        backref=db.backref("revisions", lazy="select"))

    @property
    def needs_attention(self):
        """Waiting on Michael rather than on the client."""
        return self.status == "declined"

    client = db.relationship("Client", backref=db.backref("signature_requests", lazy="dynamic"))
    project = db.relationship("Project", backref=db.backref("signature_requests", lazy="dynamic"))
    source_document = db.relationship("Document", foreign_keys=[source_document_id])
    signed_document = db.relationship("Document", foreign_keys=[signed_document_id])

    @property
    def status_label(self):
        return SIGNATURE_STATUS_LABELS.get(self.status, self.status.title())

    @property
    def status_classes(self):
        return SIGNATURE_STATUS_COLORS.get(self.status, "bg-surface-800 text-surface-400")

    @property
    def is_open(self):
        """Still waiting on somebody. Only these need refreshing."""
        return self.status in ("draft", "sent")

    @property
    def is_archived(self):
        return self.archived_at is not None

    @property
    def can_hide(self):
        """Whether it may be tidied off the list.

        Only when it has stopped moving. Hiding a contract that is out for
        signature leaves a live signing link nobody is watching, so an open
        one is voided first and hidden after.
        """
        return not self.is_open

    @property
    def kind_label(self):
        return {
            "engagement_letter": "Engagement letter",
            "sow": "Statement of work",
            "addon": "Add-on agreement",
            "addendum": "Addendum",
            "hosting": "Hosting agreement",
            "partnership": "Revenue share",
            "profit_share": "Profit share",
        }.get(self.kind, "Document")

    def __repr__(self):
        return f"<SignatureRequest {self.envelope_id} {self.status}>"



class AppLink(db.Model):
    """A tile on the My Apps board.

    The board used to be hardcoded, so adding something meant editing a
    template. These are rows now, added and edited from the page itself.

    The icon is the app's own: its PWA manifest icon, apple-touch-icon or
    favicon, fetched once and kept here. Anything you build already ships a
    logo, so picking one off a stock list would be choosing a worse picture
    than the one already sitting at the other end of the URL. Where a site
    offers none, the tile falls back to initials.

    `url` holds either a full address for something deployed elsewhere, or a
    path beginning with / for a page inside this app, and is rendered as
    given - which is why it is normalised on the way in.
    """

    __tablename__ = "app_links"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, default="")

    # The stored icon file, and where it came from. Null means none was found
    # or none has been fetched yet, and the tile shows initials instead.
    icon_file = db.Column(db.String(120), nullable=True)
    icon_source = db.Column(db.String(500), nullable=True)
    icon_fetched_at = db.Column(db.DateTime, nullable=True)

    # The other two places you go for an app: the deploy that serves it and
    # the code behind it. Both optional - a page inside this app has neither.
    railway_url = db.Column(db.String(500), nullable=True)
    github_url = db.Column(db.String(500), nullable=True)

    # A phone app ships twice, and the two store pages show one product with
    # one version. These are its two store ids and the last answer each
    # PUBLIC store page gave (store_versions_service: no credentials, the
    # same truth a customer sees). Null on the web-only tiles, which is most
    # of the board.
    app_store_bundle_id = db.Column(db.String(200), nullable=True)
    play_package = db.Column(db.String(200), nullable=True)
    store_versions = db.Column(db.Text, nullable=True)
    store_checked_at = db.Column(db.DateTime, nullable=True)
    # Since when the two stores have shown different versions, so a release
    # caught between reviews for an hour is not a row on Needs attention and
    # one stuck for a day is (store_versions_service.refresh).
    store_differ_since = db.Column(db.DateTime, nullable=True)
    # The version written in the repo, per platform, read nightly beside the
    # store ids ({"android": "1.4.0", "ios": "1.4.0"}). The tile said "1.4.0 in
    # the repo, stores on 1.3.2" until 2026-11-05, when Michael took the line
    # off ("doesn't need to exist"); the reading stays for whatever asks next.
    repo_versions = db.Column(db.Text, nullable=True)

    # The engagement this app belongs to, where there is one. Nullable because
    # half the board is mine - Bible Study, Pluralism, Data Dungeon - and those
    # have no client and no project behind them.
    #
    # SET NULL rather than CASCADE: closing out a project does not take the app
    # off the board, because the app is still running and still somewhere I go.
    # The tile outlives the engagement.
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="SET NULL", name="fk_app_links_project_id"),
        nullable=True, index=True,
    )
    project = db.relationship("Project", backref=db.backref(
        "apps", lazy="select", order_by="AppLink.name"))

    # Which half of My Apps the tile sits in, when that is not what the
    # project says: "client" or "mine", NULL to follow the project (attached
    # means client work), which is every tile made before 2026-11-01. The two
    # questions came apart that day: Robinson & Co., Christ Community Church,
    # Lets Cook and Piped have projects and are not current client work, and
    # Data Dungeon has none and is (Michael). A column of its own rather than
    # detaching the project, because the project page still lists its app and
    # register_app re-attaches the project on its next call.
    #
    # "building" is the third section (Michael, 2026-11-05: "the apps I plan
    # to work hard and want to release a version that will make money"). Only
    # a drag puts a tile there; nothing follows into it by default.
    board_group = db.Column(db.String(10), nullable=True)
    BOARD_GROUPS = ("client", "building", "mine")
    # Where the tile sits in its section, from a drag (Michael, 2026-11-05:
    # "move it up a row into the middle to where everything shifts"). NULL is
    # a tile nobody has placed: it follows the placed ones, oldest first.
    position = db.Column(db.Integer, nullable=True)

    # The catalog: the private showcase a prospect opens from a link Michael
    # sends (issue #23, 2026-11-06: "I need a way where I can pick which
    # products I want them to be able to see ... only accessible upon me
    # sending someone a link"). `catalog` is the pick; the name is what the
    # product is called there, which is not always the tile's (Robinson &
    # Co.'s studio app is Vignette); the pitch is one or two sentences in a
    # prospect's words; `catalog_points` is what it does, one per line;
    # `demo_url` is a live demo with no login, once the app has one.
    catalog = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    catalog_name = db.Column(db.String(120), nullable=True)
    catalog_pitch = db.Column(db.Text, nullable=True)
    catalog_points = db.Column(db.Text, nullable=True)
    catalog_position = db.Column(db.Integer, nullable=True)
    demo_url = db.Column(db.String(500), nullable=True)
    # The product's own icon in the catalog, on the volume under catalog/. A
    # tile renamed for the catalog never falls back to the tile's icon, which
    # is the client's (Robinson & Co.'s logo must not sit on Vignette).
    catalog_icon = db.Column(db.String(120), nullable=True)
    # Services the code reading misses (YouTube, a store Michael ships to by
    # hand) and ones it finds that the app no longer uses (EntertainHQ's
    # retired texting), one per line or comma. The night rewrites only
    # services_json, so these stay put.
    catalog_services_extra = db.Column(db.Text, nullable=True)
    # The front of the showcase (Michael, 2026-11-06: "he also has an app that
    # works with 400 talent and staff ... wow"): how big it runs, in his
    # words, and the short list of what is built into it (texting, invoicing,
    # payments), comma between. With no list, it is read from its services.
    catalog_scale = db.Column(db.String(160), nullable=True)
    catalog_highlights = db.Column(db.Text, nullable=True)
    catalog_services_hidden = db.Column(db.Text, nullable=True)
    # The services its code uses, read off the repo by the nightly audit
    # (vendor_discovery.vendors_in_files) or filed through the door
    # (/api/guidance/apps/services): a JSON list of vendor names.
    services_json = db.Column(db.Text, nullable=True)
    services_checked_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def showcase_name(self):
        return (self.catalog_name or "").strip() or self.name

    @property
    def renamed(self):
        return bool((self.catalog_name or "").strip()) and self.catalog_name.strip() != self.name

    @property
    def showcase_initials(self):
        parts = [p for p in self.showcase_name.split() if p[:1].isalnum()]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    @property
    def showcase_has_icon(self):
        return bool(self.catalog_icon or (self.icon_file and not self.renamed))

    @property
    def services(self):
        import json
        try:
            value = json.loads(self.services_json or "[]")
        except (TypeError, ValueError):
            return []
        return [v for v in value if isinstance(v, str)]

    @property
    def section(self):
        """Which section of My Apps: the choice made on the tile, else the
        project (attached is "client", which reads Live and earning)."""
        if self.board_group in self.BOARD_GROUPS:
            return self.board_group
        return "client" if self.project_id is not None else "mine"

    @property
    def is_client_work(self):
        """Whether the tile is in the first section, Live and earning."""
        return self.section == "client"

    @property
    def is_external(self):
        """Whether following this leaves the app, and so wants a new tab."""
        return self.url.startswith("http://") or self.url.startswith("https://")

    @property
    def stores(self):
        """The store rows and the match verdict for the tile, None for a
        tile with no store ids."""
        import store_versions_service  # local: models must not import services at load
        return store_versions_service.summary(self)

    @property
    def host(self):
        """The bit worth showing under the name: the domain, or the path."""
        if not self.is_external:
            return self.url
        return self.url.split("//", 1)[-1].split("/", 1)[0]

    @property
    def initials(self):
        """Two letters for a tile whose site offered no icon."""
        parts = [p for p in (self.name or "?").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (parts[0][:2] if parts else "?").upper()

    def __repr__(self):
        return f"<AppLink {self.name}>"


class CatalogShot(db.Model):
    """One screen of an app's tour in the catalog: a picture on the volume
    (`catalog/`) and what it shows, in the order a prospect pages through."""

    __tablename__ = "catalog_shots"

    id = db.Column(db.Integer, primary_key=True)
    app_link_id = db.Column(
        db.Integer,
        db.ForeignKey("app_links.id", ondelete="CASCADE", name="fk_catalog_shots_app_link_id"),
        nullable=False, index=True)
    file = db.Column(db.String(120), nullable=False)
    caption = db.Column(db.String(200), nullable=False, default="", server_default="")
    position = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    app = db.relationship("AppLink", backref=db.backref(
        "catalog_shots", lazy="select", cascade="all, delete-orphan",
        order_by="(CatalogShot.position, CatalogShot.id)"))


class CatalogLink(db.Model):
    """One prospect's way into the catalog. Nobody reaches the showcase
    without one: the token is the whole key, it expires, and Michael can
    switch it off. `app_ids_json` narrows it to some approved apps; null is
    every approved app."""

    __tablename__ = "catalog_links"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), nullable=False, unique=True, index=True)
    label = db.Column(db.String(120), nullable=False)
    app_ids_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    last_opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL", name="fk_catalog_links_created_by_id"),
        nullable=True, index=True)
    # Who it was emailed to, and when (issue #26): a client on the board, or
    # any name and address typed in. Null sent_at is a link only copied.
    email = db.Column(db.String(200), nullable=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL", name="fk_catalog_links_client_id"),
        nullable=True, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    @property
    def app_ids(self):
        import json
        try:
            value = json.loads(self.app_ids_json) if self.app_ids_json else None
        except (TypeError, ValueError):
            return None
        return [int(v) for v in value if str(v).isdigit()] if isinstance(value, list) else None


class CatalogView(db.Model):
    """A page of the showcase opened from a link: when, and which app."""

    __tablename__ = "catalog_views"

    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(
        db.Integer, db.ForeignKey("catalog_links.id", ondelete="CASCADE", name="fk_catalog_views_link_id"),
        nullable=False, index=True)
    app_link_id = db.Column(
        db.Integer, db.ForeignKey("app_links.id", ondelete="SET NULL", name="fk_catalog_views_app_link_id"),
        nullable=True, index=True)
    at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class PlaybookStep(db.Model):
    """One tickable step of a playbook, and what to send the client at it.

    The playbook's five prose sections explain a vendor. These are the doing:
    an ordered list you work down on a real project, where a step is either
    something you do or something you have to ask somebody else for.

    That second kind is why `client_message_md` exists. The slow steps are
    always the ones waiting on a client, and they are slow because writing the
    ask is a small act of composition nobody wants to do at 9pm. Written once,
    on the step, it becomes a copy button.
    """

    __tablename__ = "playbook_steps"

    id = db.Column(db.Integer, primary_key=True)
    playbook_id = db.Column(db.Integer, db.ForeignKey("playbooks.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(200), nullable=False)
    detail_md = db.Column(db.Text, default="")

    # Blank when the step is yours alone. 'email' or 'text' when it is not.
    client_channel = db.Column(db.String(10), nullable=True)
    client_message_subject = db.Column(db.String(200), default="")
    client_message_md = db.Column(db.Text, default="")

    # What a machine can see of this step being done, run nightly per project
    # (step_checks.py). A pass ticks the step; nothing ever unticks one,
    # because a check that cannot see something is not proof it was undone.
    #   repo:    check_target is file globs, check_pattern a regex a line must match
    #   railway: check_target is one of step_checks.RAILWAY_FACTS
    #   http:    check_target is a path on the project's site; optional pattern
    check_kind = db.Column(db.String(12), nullable=True)
    check_target = db.Column(db.String(300), nullable=True)
    check_pattern = db.Column(db.Text, nullable=True)
    CHECK_KINDS = ("repo", "railway", "http")

    playbook = db.relationship("Playbook", backref=db.backref(
        "steps", lazy="dynamic", cascade="all, delete-orphan",
        order_by="PlaybookStep.position"))

    # {client}, {project} and friends, filled from the project the checklist is
    # running on. Only lowercase words, so a brace in a code sample is left
    # alone rather than being read as a placeholder and blanked.
    _PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

    @property
    def waits_on_client(self):
        return bool(self.client_message_md)

    def _fill(self, text, project):
        """Substitute what this project knows and leave the rest visible.

        An unknown placeholder stays as `{from_address}` rather than becoming
        an empty gap, because a gap in a message about to be sent to a client
        is not something you notice on the way past.
        """
        if not text:
            return ""
        values = {}
        if project is not None:
            values["project"] = project.name or ""
            client = getattr(project, "client", None)
            if client is not None:
                # First name only. "Hi Michael Bean," is a letter from a bank.
                parts = (client.name or "").split()
                values["client"] = parts[0] if parts else ""
                values["company"] = client.company or client.name or ""
                host = (client.origin_base_url or "").split("//", 1)[-1].strip("/")
                if host:
                    values["domain"] = host.split("/", 1)[0]
        return self._PLACEHOLDER.sub(
            lambda m: values.get(m.group(1)) or m.group(0), text)

    def message_for(self, project=None):
        return self._fill(self.client_message_md, project)

    def subject_for(self, project=None):
        return self._fill(self.client_message_subject, project)

    def __repr__(self):
        return f"<PlaybookStep {self.position} {self.title[:30]}>"


class AppBlueprint(db.Model):
    """A whole app, end to end: what to start a new project of that shape from.

    Michael, 2026-11-04: a playbook is one vendor, and a new project of a
    known shape (multi-tenant, push, the stores, like EntertainHQ) runs the
    same dozen playbooks in the same order. A blueprint is that order and
    everything that joins the pieces: the parts, how they talk, the build
    order, what changes from one project to the next, and the traps that live
    between systems rather than inside one. "Not copy it one to one ... here's
    the idea of everything that we need to get lined up", so the session has
    the end-to-end plan and makes the ten percent of tweaks.

    The screen says Blueprint; the code says AppBlueprint because a Flask
    Blueprint is already a thing in every file that would import this. Written
    by sessions through the door (suggest_update, kind blueprint), never typed
    on a page, the same as playbooks.
    """

    __tablename__ = "app_blueprints"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    one_liner = db.Column(db.String(400), default="")
    # The repos it was read from, "BuiltByBean/EntertainHQ, ...".
    source_repos = db.Column(db.String(400), default="")
    shape_md = db.Column(db.Text, default="")
    parts_md = db.Column(db.Text, default="")
    connections_md = db.Column(db.Text, default="")
    tweaks_md = db.Column(db.Text, default="")
    traps_md = db.Column(db.Text, default="")
    # The tile it came from and the business whose map draws it, when there
    # are ones; matched by name when it is filed.
    app_id = db.Column(db.Integer, db.ForeignKey(
        "app_links.id", ondelete="SET NULL", name="fk_app_blueprints_app_id"),
        nullable=True, index=True)
    business_id = db.Column(db.Integer, db.ForeignKey(
        "businesses.id", ondelete="SET NULL", name="fk_app_blueprints_business_id"),
        nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    app = db.relationship("AppLink")
    business = db.relationship("Business")
    stages = db.relationship("AppBlueprintStage", back_populates="blueprint",
                             cascade="all, delete-orphan", lazy="dynamic",
                             order_by="AppBlueprintStage.position")

    SECTIONS = (
        ("shape_md", "What it is"),
        ("parts_md", "The parts"),
        ("connections_md", "How they talk"),
        ("tweaks_md", "What changes per project"),
        ("traps_md", "Traps between the systems"),
    )

    @property
    def display_name(self):
        return self.name

    @property
    def sections(self):
        return [{"field": f, "heading": h, "body": getattr(self, f) or ""} for f, h in self.SECTIONS]

    @property
    def playbook_slugs(self):
        """Every playbook the stages name, in build order, once each."""
        seen = []
        for stage in self.stages.all():
            for slug in stage.playbook_list:
                if slug not in seen:
                    seen.append(slug)
        return seen

    def __repr__(self):
        return f"<AppBlueprint {self.slug}>"


class AppBlueprintStage(db.Model):
    """One stage of a blueprint's build order: what to stand up, and the
    playbooks and features it leans on, kept as slugs so a renamed entry
    still resolves and a retired one simply drops out."""

    __tablename__ = "app_blueprint_stages"

    id = db.Column(db.Integer, primary_key=True)
    blueprint_id = db.Column(db.Integer, db.ForeignKey(
        "app_blueprints.id", ondelete="CASCADE", name="fk_app_blueprint_stages_blueprint_id"),
        nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String(200), nullable=False)
    detail_md = db.Column(db.Text, default="")
    playbooks_json = db.Column(db.Text, default="[]")
    features_json = db.Column(db.Text, default="[]")

    blueprint = db.relationship("AppBlueprint", back_populates="stages")

    @staticmethod
    def _list(raw):
        import json
        try:
            out = json.loads(raw or "[]")
        except ValueError:
            return []
        return [s for s in out if isinstance(s, str)]

    @property
    def playbook_list(self):
        return self._list(self.playbooks_json)

    @property
    def feature_list(self):
        return self._list(self.features_json)

    def __repr__(self):
        return f"<AppBlueprintStage {self.position} {self.title[:30]}>"


class AppGap(db.Model):
    """Something one app should catch up on, found by comparing it with the
    others (Michael, 2026-11-04: "if we have really done good work and updates
    to another app and another app is falling behind it should have
    recommendations of gaps to close or enhancements").

    Written by the Tend run through the door, one row per (blueprint, key).
    Michael closes a row as done or not wanted, and a closed row is never
    reopened by a later run, so "not wanted" stays said: the run reads the
    closed titles before it suggests anything.
    """

    __tablename__ = "app_gaps"
    __table_args__ = (db.UniqueConstraint("blueprint_id", "key", name="uq_app_gaps_blueprint_key"),)

    id = db.Column(db.Integer, primary_key=True)
    blueprint_id = db.Column(db.Integer, db.ForeignKey(
        "app_blueprints.id", ondelete="CASCADE", name="fk_app_gaps_blueprint_id"),
        nullable=False, index=True)
    key = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    detail_md = db.Column(db.Text, default="")
    # "gap": something a sibling app does that this one should; "enhancement":
    # a step beyond what any of them do yet.
    kind = db.Column(db.String(12), nullable=False, default="gap", server_default="gap")
    # The app that already does it, when there is one.
    source_blueprint_id = db.Column(db.Integer, db.ForeignKey(
        "app_blueprints.id", ondelete="SET NULL", name="fk_app_gaps_source_blueprint_id"),
        nullable=True, index=True)
    status = db.Column(db.String(12), nullable=False, default="open", server_default="open", index=True)
    filed_by = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    decided_at = db.Column(db.DateTime, nullable=True)

    blueprint = db.relationship("AppBlueprint", foreign_keys=[blueprint_id], backref=db.backref(
        "gaps", lazy="dynamic", cascade="all, delete-orphan"))
    source = db.relationship("AppBlueprint", foreign_keys=[source_blueprint_id])

    KINDS = (("gap", "Gap"), ("enhancement", "Enhancement"))
    STATUSES = (("open", "Open"), ("done", "Done"), ("dismissed", "Not wanted"))

    @property
    def kind_label(self):
        return dict(self.KINDS).get(self.kind, self.kind)

    def __repr__(self):
        return f"<AppGap {self.blueprint_id} {self.key}>"


class IconConcept(db.Model):
    """One concept and the one drawing that stands for it, in every project.

    Michael, 2026-11-04: "icons that I like to use for concepts ... you can
    probably find places where I use similar icons for similar things across
    my projects." The Handbook's Icons tab is this table, the board's
    `icon('concept')` macro draws from it, and every build prompt carries it
    as one line per concept. Written through the door (suggest_update, kind
    icon) with Revert in History. Defaults live in code (icon_defaults.py),
    edits here, so a fresh database still draws every icon.

    `svg` is the inner markup only, sanitised to geometry (icon_vocabulary.
    clean_svg): one viewBox (0 0 24 24) and one stroke style are the
    vocabulary's, never an entry's.
    """

    __tablename__ = "icon_concepts"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    # nav (a place), action (a press), status (a state), thing (an object).
    group = db.Column(db.String(12), nullable=False, default="thing", server_default="thing")
    svg = db.Column(db.Text, nullable=False, default="")
    library = db.Column(db.String(80), default="")
    icon_name = db.Column(db.String(80), default="")
    aliases = db.Column(db.String(400), default="")
    used_in_md = db.Column(db.Text, default="")
    never_md = db.Column(db.Text, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    GROUPS = (("nav", "Places"), ("action", "Actions"), ("status", "States"), ("thing", "Things"))

    @property
    def display_name(self):
        return self.name

    @property
    def group_label(self):
        return dict(self.GROUPS).get(self.group, self.group)

    def __repr__(self):
        return f"<IconConcept {self.slug}>"


class ProjectPlaybook(db.Model):
    """A playbook applied to a project: this vendor, on this build.

    The playbook stays the template. This is the copy of it that a particular
    project is working through, and the only thing it adds is which steps are
    done.
    """

    __tablename__ = "project_playbooks"
    __table_args__ = (
        # One project runs a given playbook once. Applying it twice would give
        # two checklists that disagree about what is finished.
        db.UniqueConstraint("project_id", "playbook_id", name="uq_project_playbook"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    playbook_id = db.Column(db.Integer, db.ForeignKey("playbooks.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    project = db.relationship("Project", backref=db.backref(
        "playbooks", lazy="dynamic", cascade="all, delete-orphan"))
    playbook = db.relationship("Playbook")

    @property
    def steps(self):
        return self.playbook.steps.all()

    @property
    def done_ids(self):
        return {p.playbook_step_id for p in self.progress if p.done}

    def note_for(self, step_id):
        """What was written down when the step was ticked, if anything.

        Reads from `progress`, which the template has already loaded for
        done_ids, so this costs nothing extra per step.
        """
        for row in self.progress:
            if row.playbook_step_id == step_id and row.done:
                return row.note or ""
        return ""

    @property
    def total_steps(self):
        return self.playbook.steps.count()

    @property
    def done_count(self):
        return len(self.done_ids)

    @property
    def percent(self):
        total = self.total_steps
        return int(round(self.done_count / total * 100)) if total else 0

    @property
    def is_complete(self):
        total = self.total_steps
        return total > 0 and self.done_count == total

    def __repr__(self):
        return f"<ProjectPlaybook p{self.project_id} b{self.playbook_id}>"


class ProjectPlaybookStep(db.Model):
    """Whether one step of one applied playbook is done, and any note on it.

    A row appears the first time a step is touched rather than being written
    out for every step when a playbook is applied. Editing a playbook's steps
    afterwards then changes what everybody sees next, instead of leaving old
    projects working from a frozen copy nobody can find to fix.
    """

    __tablename__ = "project_playbook_steps"
    __table_args__ = (
        db.UniqueConstraint("project_playbook_id", "playbook_step_id",
                            name="uq_project_playbook_step"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_playbook_id = db.Column(
        db.Integer, db.ForeignKey("project_playbooks.id", ondelete="CASCADE"),
        nullable=False, index=True)
    playbook_step_id = db.Column(
        db.Integer, db.ForeignKey("playbook_steps.id", ondelete="CASCADE"),
        nullable=False, index=True)

    done = db.Column(db.Boolean, nullable=False, default=False)
    done_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, default="")

    applied = db.relationship("ProjectPlaybook", backref=db.backref(
        "progress", lazy="select", cascade="all, delete-orphan"))
    step = db.relationship("PlaybookStep")

    def __repr__(self):
        return f"<ProjectPlaybookStep {self.playbook_step_id} done={self.done}>"


# ── What I sell ──────────────────────────────────────────────


class Product(db.Model):
    """One thing that can be bought on its own, at its own price.

    The prose that goes into an add-on contract already lives in
    `contract_docs.PRODUCTS`, keyed by the same slug: what it includes, what
    the client has to provide, the lead time, whose platform it touches. That
    stays there, because it is the wording of an agreement and belongs beside
    the document builder.

    What lives here is everything that changes without a deploy - the price,
    whether it is still offered, the order it reads in - and the two joins the
    contract layer has no opinion about: which runbook to apply when it sells,
    and who has bought it.

    A null price means one that is quoted per client rather than listed. The
    custom build is the case: it is the largest thing sold here and the only
    one with no standard number.
    """

    __tablename__ = "products"

    # Ordered the way a sale is discussed: the build itself, getting paid,
    # reaching people, the paperwork, running the day, and their own site
    # and systems. The products page groups by this.
    CATEGORIES = (
        ("build", "The build"),
        ("money", "Getting paid"),
        ("comms", "Reaching people"),
        ("documents", "Paperwork"),
        ("operations", "Running the day"),
        ("connect", "Their site and their systems"),
    )
    CATEGORY_LABELS = dict(CATEGORIES)

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.Text, default="")
    category = db.Column(db.String(20), nullable=False, default="operations",
                         server_default="operations", index=True)
    price = db.Column(db.Float, nullable=True)
    monthly_price = db.Column(db.Float, nullable=True)
    # The runbook applied to the project when this sells. Held as a slug
    # rather than a foreign key so a product can name a playbook that has not
    # been written yet without failing to save.
    playbook_slug = db.Column(db.String(60), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, default=0)
    # Whether selling this puts something on my infrastructure, and so brings
    # the monthly hosting and storage fee with it. Most do. Routing somebody's
    # mail through their own domain does not - that is DNS records on a domain
    # they own, with nothing of mine running anywhere - and charging rent for
    # it would be charging for nothing.
    #
    # A default, not a rule. The sell form asks, and the answer can differ:
    # a client already paying to be hosted does not start paying twice.
    includes_hosting = db.Column(db.Boolean, nullable=False, default=True)
    # Which glyph to draw where the product is not one company's thing. A
    # product with variants shows their logos instead - Stripe's mark says
    # more than any icon could.
    icon = db.Column(db.String(30), default="")
    # Anything specific to this product that a runbook does not already say,
    # prepended to the prompt built for a sale. Usually empty: the playbook is
    # the source, and a second copy of it here would go stale the first time
    # the vendor changed a screen.
    prompt_intro = db.Column(db.Text, default="")
    # What this product looks like in a codebase, so Cerebro can say a
    # client has it from the code alone. Texting built into an MVP before
    # the catalogue existed has no sale row, but it has twilio in it. A
    # line matching presence_pattern in a file matching presence_globs is
    # a sighting; presence_fixture is a line the pattern MUST match.
    presence_pattern = db.Column(db.Text, nullable=True)
    presence_globs = db.Column(db.String(300), nullable=True)
    presence_exclude = db.Column(db.String(300), nullable=True)
    presence_fixture = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sales = db.relationship("ProductSale", back_populates="product",
                            cascade="all, delete-orphan", lazy="dynamic")

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def price_label(self):
        """What to print where a price goes, including when there is not one."""
        if self.price is None and self.monthly_price is None:
            return "Quoted"
        parts = []
        if self.price is not None:
            parts.append(f"${self.price:,.0f}")
        if self.monthly_price:
            parts.append(f"${self.monthly_price:,.0f}/mo")
        return " + ".join(parts)

    def __repr__(self):
        return f"<Product {self.slug}>"


class ProductSale(db.Model):
    """One product, sold once, to one client.

    Always against a project, even when nothing custom was built. Somebody
    buying only a signing portal still needs somewhere for its runbook, its
    hosting fee and its tickets to live, and a project is that place - so a
    standalone sale makes a small one rather than inventing a second home for
    all three.

    The price is copied onto the sale rather than read back off the product,
    because the catalogue price is what it costs today and this is what that
    client agreed to. Changing the list price must not rewrite history.
    """

    __tablename__ = "product_sales"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # Which platform this one landed on, where the product has a choice.
    # Nullable because some products have none - a custom build is not "of"
    # anybody else's system. SET NULL rather than CASCADE: retiring a variant
    # from the catalogue must not delete the record of having sold it.
    variant_id = db.Column(db.Integer,
                           db.ForeignKey("product_variants.id", ondelete="SET NULL"),
                           nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    price = db.Column(db.Float, nullable=True)
    monthly_price = db.Column(db.Float, nullable=True)
    delivery_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship("Product", back_populates="sales")
    variant = db.relationship("ProductVariant")
    client = db.relationship("Client", backref=db.backref(
        "product_sales", lazy="dynamic", cascade="all, delete-orphan"))
    project = db.relationship("Project", backref=db.backref(
        "product_sales", lazy="dynamic", cascade="all, delete-orphan"))

    @property
    def label(self):
        """The product, named by its variant where there is one."""
        if self.variant is not None:
            return f"{self.product.name} - {self.variant.name}"
        return self.product.name

    def __repr__(self):
        return f"<ProductSale {self.product_id} -> client {self.client_id}>"


class ProductVariant(db.Model):
    """Which one, within a product.

    A product is the shape of the work; a variant is whose platform it lands
    on. Invoicing is the same build every time - the hard half is which
    payment provider it connects to. An API connection is the same shape of
    job whether the far end is Tripleseat or something nobody here has heard
    of yet.

    Catalogued as they are met rather than guessed at in advance. Selling
    something against a system that has no variant yet writes one, so the
    second client on that platform picks it from a list instead of typing it
    again. For a long time most sales will be the first of their kind; that is
    the nature of there being more systems in the world than anybody can
    enumerate.

    Price is an override, not a second price. Most variants cost what the
    product costs. The one that does not is the point of the column: a
    provider nobody here has integrated before is more work than the one that
    is known cold.
    """

    __tablename__ = "product_variants"
    __table_args__ = (
        db.UniqueConstraint("product_id", "slug", name="uq_product_variant_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    slug = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    # The runbook for this vendor, when one has been written. Held as a slug
    # for the same reason the product's is: a variant can name a playbook that
    # does not exist yet without failing to save.
    playbook_slug = db.Column(db.String(60), nullable=True)
    price = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    product = db.relationship("Product", backref=db.backref(
        "variants", lazy="select", cascade="all, delete-orphan",
        order_by="ProductVariant.sort_order"))

    def __repr__(self):
        return f"<ProductVariant {self.slug} of {self.product_id}>"


# ── What I have built before ─────────────────────────────────


class Feature(db.Model):
    """One capability, catalogued once, reusable on the next build.

    Products are things that run: an integration with somebody else's
    platform, or a whole second system. Features are what somebody uses when
    they open the app - a booking screen, an inquiry form, a way to tag
    things.

    Two jobs. Recall: "here is what I have built before" is hard to answer
    from a list of repositories, and the answer decides what goes in an MVP.
    So a feature's name is what a client would call it, and its summary is
    one sentence in their words; the client reads both on "What they see".
    Prices do not live here: Michael, 2026-11-03, "no price shit left over".
    What a build costs is typed on the SOW.

    And the one that pays for the rest: not building the same thing wrong
    twice. Talent Booker carries fifty-three landmines and Data Dungeon
    thirty-four, each written the day it cost an afternoon - and every one of
    them is trapped in the repository it was learned in. Talent Booker's
    LM-19 says a `|tojson` inside a double-quoted HTML attribute breaks the
    attribute; that exact bug shipped from this repository on 2026-09-03,
    because nothing here could see what was written over there.
    """

    __tablename__ = "features"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(20), nullable=False, default="records", index=True)
    summary = db.Column(db.Text, default="")

    # How it should be built, and what goes wrong. The second is the reason
    # this table exists; the first is what stops it being relearned.
    gold_standard_md = db.Column(db.Text, default="")
    pitfalls_md = db.Column(db.Text, default="")

    # Where the version worth copying lives. A repo and a path, because "look
    # at Talent Booker" is not an answer at eleven at night.
    reference_project = db.Column(db.String(120), default="")
    reference_path = db.Column(db.String(300), default="")

    # Two kinds share this table because they share everything else - the
    # categories, the guidance fields, the search. A `feature` is a
    # capability that gets picked for a client's MVP. A `rule` is the layer
    # under that: a way of building that must not be broken, regardless of
    # which features were picked - the tojson quoting, the sticky bars, the
    # migration guards. Rules never appear in the MVP picker; every build
    # prompt carries them.
    kind = db.Column(db.String(10), nullable=False, default="feature",
                     index=True)

    # A rule that can check itself. Data Dungeon's Cerebro made every
    # landmine a scanner with a fixture that proves the scanner fires;
    # this is the same idea held on the rule, so the nightly audit can
    # hold every client repo against it. A line matching check_pattern in
    # a file matching check_globs is a hit, unless the file also matches
    # check_unless. check_fixture is a line the pattern MUST match, run
    # on every page load, because a scanner that finds nothing looks
    # exactly like a scanner that is broken.
    check_pattern = db.Column(db.Text, nullable=True)
    check_globs = db.Column(db.String(300), nullable=True)
    check_exclude = db.Column(db.String(300), nullable=True)
    check_unless = db.Column(db.Text, nullable=True)
    check_fixture = db.Column(db.Text, nullable=True)

    # `built` is something shipped at least once. `idea` is something a client
    # asked for that does not exist yet - captured on the call rather than
    # lost, which is half the point of having the page open during one.
    status = db.Column(db.String(20), nullable=False, default="built")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Ordered the way a build is discussed: what brings work in, what happens
    # to it, what gets paid, and the machinery underneath.
    CATEGORIES = (
        ("intake", "Getting work in"),
        ("scheduling", "Scheduling"),
        ("records", "Records and data"),
        ("money", "Money"),
        ("comms", "Talking to people"),
        ("documents", "Documents"),
        ("portal", "Their own access"),
        ("platform", "Underneath"),
        ("ui", "Interface patterns"),
        # Not a kind of feature anybody buys. It is where the rules against
        # building something in the shape a model reaches for first live, so
        # they are one list rather than scattered through the others: the
        # coloured-left-edge alert, the em dash, and whatever is caught next.
        ("classics", "Claude classics"),
    )
    CATEGORY_LABELS = dict(CATEGORIES)

    STATUSES = (("built", "Built before"), ("idea", "Not built yet"))
    STATUS_LABELS = dict(STATUSES)

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def has_guidance(self):
        """Whether anything here would stop somebody rebuilding it badly."""
        return bool((self.gold_standard_md or "").strip()
                    or (self.pitfalls_md or "").strip())

    def __repr__(self):
        return f"<Feature {self.slug}>"


# ── The MVP, assembled ───────────────────────────────────────


class ProviderInvoice(db.Model):
    """What a vendor actually charged for one month. Typed in, on purpose.

    The board used to answer "what has Railway cost" by summing every expense
    whose description began with the provider's name. Two different things
    write those: the flat monthly charge from before per-project figures
    existed, and the sync, which books one expense per project per month. Both
    match the prefix, so any month holding both was counted twice, and the
    lifetime total read $231.65 against $136.90 of actual invoices.

    That was the wrong shape of answer, not a wrong sum. A derived total is a
    guess assembled from whatever happens to be in the ledger; the invoice is
    the number the vendor charged, and there is exactly one of it per month.
    This is Cerebro's principle pointed at money: the code is the truth about
    what a site has, and the INVOICE is the truth about what it cost. Usage
    per project stays what it always was, the truth about how to split it.

    One row per provider per month, so entering it twice corrects rather than
    doubles - which is the whole failure being fixed here.
    """

    __tablename__ = "provider_invoices"
    __table_args__ = (
        db.UniqueConstraint("provider_id", "period_month",
                            name="uq_provider_invoices_provider_month"),
    )

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("service_providers.id", ondelete="CASCADE",
                      name="fk_provider_invoices_provider_id"),
        nullable=False, index=True)
    # The first of the month it COVERS, not the day it was issued. Railway
    # bills in arrears: the invoice dated 1 September is August's usage, and
    # filing it under September would put every month's cost one month late.
    period_month = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    note = db.Column(db.String(300), default="")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    provider = db.relationship("ServiceProvider", backref=db.backref(
        "invoices", lazy="select", cascade="all, delete-orphan"))

    @property
    def month_label(self):
        return self.period_month.strftime("%b %Y") if self.period_month else ""

    def __repr__(self):
        return f"<ProviderInvoice {self.provider_id} {self.period_month} {self.amount}>"


# ---------------------------------------------------------------- workspace
#
# Michael, 2026-11-04: "I have a notes section. I want to replace that and
# integrate the workspace feature from Entertain HQ into that, where we have
# the messages, task, and projects." EntertainHQ's shape (docs/features in that
# repo), cut to a board with two people on it: everyone sees everything, the
# Tasks board opens on yours, and a project is the client project this board
# already had rather than a second kind of project.

# Where a task has got to. Backlog, In progress, Done: EntertainHQ's three
# columns, in their order. A done task also carries done_at, so "what was
# cleared this week" stays a query.
TASK_STAGES = (("backlog", "Backlog"), ("in_progress", "In progress"), ("done", "Done"))
TASK_STAGE_KEYS = tuple(k for k, _ in TASK_STAGES)


class WorkTask(db.Model):
    """Something to do, for one or more people on the board.

    What Notes were, with people and a column. Every note was carried across
    by migration a5d17c3e92b4 with its id, its words, its date and its four
    links, open ones into Backlog for the owner and done ones into Done.

    Everything it points at is OPTIONAL and none of it is exclusive, the rule
    Notes had: a thought arrives as a client and a project and a date at once.
    SET NULL on every link, because closing a project does not mean the task
    about it was done, and a task that loses its link still has its words.
    """

    __tablename__ = "work_tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    stage = db.Column(db.String(20), nullable=False, default="backlog", index=True)
    # Its place in its column, smallest first. Written by the drag; a new task
    # goes to the top of its column.
    position = db.Column(db.Integer, nullable=False, default=0)
    done_at = db.Column(db.DateTime, nullable=True, index=True)
    # A date, not a datetime: nothing here is due at 3pm.
    due_on = db.Column(db.Date, nullable=True, index=True)

    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL", name="fk_work_tasks_created_by_id"),
        nullable=True, index=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL", name="fk_work_tasks_client_id"),
        nullable=True, index=True)
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL", name="fk_work_tasks_project_id"),
        nullable=True, index=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="SET NULL", name="fk_work_tasks_product_id"),
        nullable=True, index=True)
    playbook_id = db.Column(
        db.Integer, db.ForeignKey("playbooks.id", ondelete="SET NULL", name="fk_work_tasks_playbook_id"),
        nullable=True, index=True)

    # The backref is "work_tasks", never "notes" or "tasks": Client, Project
    # and Product carry a free-text notes column, and a relationship with a
    # column's name refuses to map and takes every other model down with it.
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    client = db.relationship("Client", backref=db.backref("work_tasks", lazy="select"))
    project = db.relationship("Project", backref=db.backref("work_tasks", lazy="select"))
    product = db.relationship("Product", backref=db.backref("work_tasks", lazy="select"))
    playbook = db.relationship("Playbook", backref=db.backref("work_tasks", lazy="select"))
    people = db.relationship("WorkTaskPerson", back_populates="task", lazy="select",
                             cascade="all, delete-orphan", order_by="WorkTaskPerson.id")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    @property
    def is_done(self):
        return self.stage == "done"

    @property
    def is_overdue(self):
        """Past its date and still open. A done task is never late."""
        return bool(self.due_on and not self.is_done and self.due_on < date.today())

    @property
    def person_ids(self):
        return [p.user_id for p in self.people]

    def is_for(self, user_id):
        return user_id in self.person_ids

    @property
    def links(self):
        """What this is about, as (kind, label, endpoint, kwargs). One place
        decides the order, so the card and the window cannot disagree."""
        out = []
        if self.project:
            out.append(("project", self.project.name, "pm.project_detail", {"id": self.project_id}))
        if self.client:
            out.append(("client", self.client.name, "pm.client_detail", {"id": self.client_id}))
        if self.product:
            out.append(("product", self.product.name,
                        "mvp.price_list", {}))
        if self.playbook:
            out.append(("playbook", self.playbook.display_name,
                        "playbooks.playbook_detail", {"slug": self.playbook.slug}))
        return out

    def __repr__(self):
        return f"<WorkTask {self.id} {self.title[:30]!r}>"


class ProjectFold(db.Model):
    """One project folded into another, kept whole so it can be put back.

    Michael, 2026-11-04: "workforce was never ever its own project it was a
    feature added to talent booker which is entertainhq". Everything on the
    folded project moves to the one it belongs to (both Kenali's, so no
    client's figures change), and the folded one is deleted. `moved_json` is
    {table: [ids]} plus `_merged_playbooks` (a checklist the target already
    had: its row and step rows) and `_detached_tiles`; `project_json` is the
    folded project's row as it was. The downgrade puts every piece back.
    """

    __tablename__ = "project_folds"

    id = db.Column(db.Integer, primary_key=True)
    from_project_id = db.Column(db.Integer, nullable=False)
    into_project_id = db.Column(db.Integer, nullable=False)
    outcome = db.Column(db.String(20), nullable=False)  # "deleted" or "archived"
    moved_json = db.Column(db.Text, nullable=False, default="{}")
    kept_json = db.Column(db.Text, nullable=False, default="{}")
    project_json = db.Column(db.Text, nullable=False, default="{}")
    reason = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WorkTaskPerson(db.Model):
    """One person a task is for. `seen_at` NULL is "given to them and not
    shown to them yet", which is what the Workspace's count is: what is NEW,
    never the standing backlog (EntertainHQ, 2026-10-09)."""

    __tablename__ = "work_task_people"
    __table_args__ = (db.UniqueConstraint("task_id", "user_id", name="uq_work_task_people"),)

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer, db.ForeignKey("work_tasks.id", ondelete="CASCADE", name="fk_work_task_people_task_id"),
        nullable=False, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE", name="fk_work_task_people_user_id"),
        nullable=False, index=True)
    seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    task = db.relationship("WorkTask", back_populates="people")
    user = db.relationship("User")


class TeamConversation(db.Model):
    """A chat between people on the board: two of them, or a group.

    Named Team*, never Message: `Message` is the client mail this board reads
    from Gmail, and a model sharing another class's name is how a whole app's
    email went dark for fifteen hours elsewhere (catalogue rule "A model named
    like a library class shadows it").

    A pair has ONE direct conversation by construction: `pair_key` is the two
    ids sorted ("3:7"), unique among the rows that carry one, so two people
    starting a chat at the same moment land in the same one. A group has no
    key and is found again by its member set.
    """

    __tablename__ = "team_conversations"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=True)
    pair_key = db.Column(db.String(40), nullable=True)
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL", name="fk_team_conversations_created_by_id"),
        nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_message_at = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (db.UniqueConstraint("pair_key", name="uq_team_conversations_pair_key"),)

    members = db.relationship("TeamConversationMember", back_populates="conversation",
                              cascade="all, delete-orphan", lazy="select")
    messages = db.relationship("TeamMessage", back_populates="conversation",
                               cascade="all, delete-orphan", lazy="dynamic",
                               order_by="TeamMessage.id")

    @property
    def member_ids(self):
        return sorted(m.user_id for m in self.members)

    def others(self, user_id):
        return [m.user for m in self.members if m.user_id != user_id and m.user]

    def name_for(self, user_id):
        if self.title:
            return self.title
        names = [u.full_name for u in self.others(user_id)]
        return ", ".join(names) or "Just you"


class TeamConversationMember(db.Model):
    __tablename__ = "team_conversation_members"
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id",
                                          name="uq_team_conversation_members"),)

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("team_conversations.id", ondelete="CASCADE",
                                  name="fk_team_conversation_members_conversation_id"),
        nullable=False, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE",
                                  name="fk_team_conversation_members_user_id"),
        nullable=False, index=True)
    # Everything said by somebody else after this is unread for them.
    last_read_at = db.Column(db.DateTime, nullable=True)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = db.relationship("TeamConversation", back_populates="members")
    user = db.relationship("User")


class TeamMessage(db.Model):
    __tablename__ = "team_messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("team_conversations.id", ondelete="CASCADE",
                                  name="fk_team_messages_conversation_id"),
        nullable=False, index=True)
    author_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL", name="fk_team_messages_author_id"),
        nullable=True, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # Marked, not removed, so the line can say it was deleted and nothing
    # counts it any more.
    deleted_at = db.Column(db.DateTime, nullable=True)

    conversation = db.relationship("TeamConversation", back_populates="messages")
    author = db.relationship("User")
    links = db.relationship("TeamMessageLink", back_populates="message",
                            cascade="all, delete-orphan", lazy="select",
                            order_by="TeamMessageLink.id")


class TeamMessageLink(db.Model):
    """What a message is about: anything on the board, by kind and id.

    No foreign key, because the kinds are several tables; the name is read
    live when the message is drawn, and a record that has gone reads as gone
    rather than taking the message with it.
    """

    __tablename__ = "team_message_links"
    __table_args__ = (db.Index("ix_team_message_links_kind_record", "kind", "record_id"),)

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(
        db.Integer, db.ForeignKey("team_messages.id", ondelete="CASCADE",
                                  name="fk_team_message_links_message_id"),
        nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)

    message = db.relationship("TeamMessage", back_populates="links")


class Message(db.Model):
    """One email's worth of conversation with a client or a lead, kept here.

    Two ways in. The public site's contact form writes one directly, before
    it tries to send the notification email - so a lead is on the board even
    on the day SMTP is down. And the inbox sync reads Michael's Gmail over
    IMAP for anything sent by a client's address, or by anyone who has
    written through the form before, so a conversation that started on the
    site can continue by email and still be seen here.

    Replies go out from his own Gmail over SMTP and are stored as `out`
    rows, threaded to what they answer with real In-Reply-To headers, so the
    client's mail client threads them and Gmail keeps them in Sent.

    `thread_id` is the root message's id, including on the root itself, so
    a whole conversation is one query. `external_id` is the RFC Message-ID,
    which is what makes a sync idempotent: the same mail fetched twice is
    one row.
    """

    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    # contact_form | gmail
    source = db.Column(db.String(20), nullable=False, default="gmail")
    # in | out
    direction = db.Column(db.String(3), nullable=False, default="in", index=True)
    from_name = db.Column(db.String(200), default="")
    from_email = db.Column(db.String(200), nullable=False, index=True)
    to_email = db.Column(db.String(200), default="")
    subject = db.Column(db.String(300), default="")
    body = db.Column(db.Text, default="")
    # What the form's "project type" picker said, when it came from the form.
    project_type = db.Column(db.String(80), default="")
    external_id = db.Column(db.String(300), nullable=True, unique=True)
    thread_id = db.Column(db.Integer, nullable=True, index=True)
    in_reply_to_id = db.Column(
        db.Integer,
        db.ForeignKey("messages.id", ondelete="SET NULL", name="fk_messages_in_reply_to_id"),
        nullable=True)
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="SET NULL", name="fk_messages_client_id"),
        nullable=True, index=True)
    # in: new | replied | archived.  out: sent.
    status = db.Column(db.String(10), nullable=False, default="new", index=True)
    received_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    replied_at = db.Column(db.DateTime, nullable=True)
    # The inbox (issue #40): all of Primary and Sent, not only client mail.
    # Gmail's own ids, read over IMAP's X-GM-MSGID and X-GM-THRID: the message
    # (dedupe, and how an attachment is fetched again) and its conversation.
    gm_msgid = db.Column(db.String(32), nullable=True, unique=True, index=True)
    gm_thrid = db.Column(db.String(32), nullable=True, index=True)
    # {"to": [[name, email], ...], "cc": [...]}: who else was on it, for reply-all.
    recipients_json = db.Column(db.Text, nullable=True)
    # The References header as it arrived, so a reply carries the whole chain.
    refs = db.Column(db.Text, nullable=True)
    # [{"n": walk index, "name", "type", "size"}]: the files stay in Gmail and
    # are fetched when opened.
    attachments_json = db.Column(db.Text, nullable=True)
    # Read on the board (an inbound row only). Gmail's own read mark clears it too.
    seen_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    # A client, a lead or the contact form: the only mail Needs attention shows.
    watched = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # The press that sent it, so a double press sends once.
    send_key = db.Column(db.String(64), nullable=True, unique=True, index=True)

    client = db.relationship("Client", backref=db.backref("messages", lazy="dynamic"))

    @property
    def recipients(self):
        import json
        try:
            data = json.loads(self.recipients_json or "{}")
        except ValueError:
            data = {}
        return {"to": data.get("to") or [], "cc": data.get("cc") or []}

    @property
    def attachments(self):
        import json
        try:
            return json.loads(self.attachments_json or "[]")
        except ValueError:
            return []

    @property
    def short_body(self):
        """The body without the quoted mail under it, so a thread reads as
        what each person said (EntertainHQ's cleanText)."""
        from pm.mail_service import clean_text
        return clean_text(self.body or "")

    @property
    def snippet(self):
        text = " ".join((self.body or "").split())
        return text[:140] + ("..." if len(text) > 140 else "")

    @property
    def sender_label(self):
        return self.from_name or self.from_email

    def __repr__(self):
        return f"<Message {self.direction} {self.from_email} {self.status}>"


class RuleAudit(db.Model):
    """One repository held against one rule, as of the last nightly audit.

    Upserted on (repo, rule), so the table is always the current picture and
    never a log. `violations` is the count; `sample_json` keeps the first
    few as path, line and text, which is what a batch fix starts from.
    """

    __tablename__ = "rule_audits"
    __table_args__ = (
        db.UniqueConstraint("repo", "rule_id", name="uq_rule_audits_repo_rule"),
    )

    id = db.Column(db.Integer, primary_key=True)
    repo = db.Column(db.String(200), nullable=False, index=True)
    rule_id = db.Column(db.Integer, db.ForeignKey("features.id", ondelete="CASCADE",
                                                  name="fk_rule_audits_rule_id"),
                        nullable=False, index=True)
    sha = db.Column(db.String(64), nullable=True)
    violations = db.Column(db.Integer, nullable=False, default=0)
    sample_json = db.Column(db.Text, default="[]")
    checked_at = db.Column(db.DateTime, nullable=True)

    rule = db.relationship("Feature", backref=db.backref("audits", lazy="dynamic",
                                                         cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<RuleAudit {self.repo} rule={self.rule_id} {self.violations}>"


class ProductAudit(db.Model):
    """One repository held against one product's signature, as of the last
    nightly audit: how many lines looked like the product, and the first
    few. The positive twin of RuleAudit."""

    __tablename__ = "product_audits"
    __table_args__ = (
        db.UniqueConstraint("repo", "product_id", name="uq_product_audits_repo_product"),
    )

    id = db.Column(db.Integer, primary_key=True)
    repo = db.Column(db.String(200), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE",
                                                     name="fk_product_audits_product_id"),
                           nullable=False, index=True)
    sha = db.Column(db.String(64), nullable=True)
    hits = db.Column(db.Integer, nullable=False, default=0)
    sample_json = db.Column(db.Text, default="[]")
    checked_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("Product", backref=db.backref("audits", lazy="dynamic",
                                                            cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<ProductAudit {self.repo} product={self.product_id} {self.hits}>"


class RepoWatch(db.Model):
    """What the nightly sweep has already read of one repository's CLAUDE.md.

    The blob sha means an unchanged file costs one request and no parsing;
    the seen headings mean only what is new is proposed, and the first read
    of a repo records everything without proposing any of it, so the lessons
    already mined by hand never come back as duplicates.
    """

    __tablename__ = "repo_watches"

    id = db.Column(db.Integer, primary_key=True)
    repo = db.Column(db.String(200), nullable=False, unique=True)
    last_sha = db.Column(db.String(64), nullable=True)
    seen_json = db.Column(db.Text, default="[]")
    last_swept_at = db.Column(db.DateTime, nullable=True)
    filed_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<RepoWatch {self.repo}>"


class CatalogueProposal(db.Model):
    """One change a session asked to make to the catalogue, and what became of it.

    The catalogue is meant to grow itself: a session that finds a Stripe step
    moved, a better file to copy, or a rule that needs rewording says so
    through the guidance API. But a rule rides into every future build
    prompt, so a wrong one poisons every project after it. This row is the
    difference between a catalogue that learns and one that can be vandalised
    by a single confused session.

    Everything applies on arrival, rewrites included (Michael, 2026-11-02:
    "stop this waiting on a yes thing, just have it adjust properly over
    time"). The inbox held 188 rewrites and swept notes nobody was ever going
    to read one at a time, so the safety it promised was never delivered.
    What keeps the catalogue honest now is the nightly curator
    (`curate_practices.py`), which merges, tightens and retires, and the
    History tab, where any change still goes back in one press. `previous`
    is the snapshot that makes revert possible; `payload_json` carries a
    create, whose fields do not fit one column.

    `candidate` is raw material rather than a change: a section the sweeper
    read in a repo's CLAUDE.md. Repo prose is written for that repo, so it
    never rides into a build prompt as it stands; the curator reads it and
    either writes a rule for any project, folds it into one, or discards it.
    """

    __tablename__ = "catalogue_proposals"

    id = db.Column(db.Integer, primary_key=True)
    # feature | rule | playbook | product
    kind = db.Column(db.String(10), nullable=False)
    target_slug = db.Column(db.String(80), nullable=True, index=True)
    # The column being changed, or "*" for a create.
    field = db.Column(db.String(40), nullable=False)
    # append | replace | create | retire
    mode = db.Column(db.String(10), nullable=False)
    proposed = db.Column(db.Text, default="")
    previous = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, default="")
    # Which project's session learned it. A change with no provenance is a
    # change nobody can weigh.
    project = db.Column(db.String(120), default="")
    # applied | reverted | candidate | curated | discarded. Older rows also
    # carry accepted and rejected from when rewrites waited on a person.
    status = db.Column(db.String(10), nullable=False, default="applied", index=True)
    payload_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = db.Column(db.DateTime, nullable=True)

    KIND_LABELS = {"feature": "Feature", "rule": "Rule",
                   "playbook": "Playbook", "product": "Product",
                   "blueprint": "Blueprint", "map": "Map", "icon": "Icon"}

    @property
    def is_live(self):
        """Whether the change is currently in the catalogue."""
        return self.status in ("applied", "accepted")

    def __repr__(self):
        return f"<CatalogueProposal {self.kind}:{self.target_slug} {self.mode} {self.status}>"


class CuratorRun(db.Model):
    """One night of the curator, and what it did to Best Practices.

    The changes themselves are CatalogueProposal rows with project
    "curator", so each one reverts on its own; this is the night as a whole,
    which is what the History tab leads with. `status` is ok, partial (it
    ran and something failed), skipped (no ANTHROPIC_API_KEY) or failed.
    """

    __tablename__ = "curator_runs"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(10), nullable=False, default="running")
    model = db.Column(db.String(60), default="")
    added = db.Column(db.Integer, nullable=False, default=0)
    folded = db.Column(db.Integer, nullable=False, default=0)
    merged = db.Column(db.Integer, nullable=False, default=0)
    tightened = db.Column(db.Integer, nullable=False, default=0)
    retired = db.Column(db.Integer, nullable=False, default=0)
    discarded = db.Column(db.Integer, nullable=False, default=0)
    rules_before = db.Column(db.Integer, nullable=True)
    rules_after = db.Column(db.Integer, nullable=True)
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.Text, default="")

    @property
    def changed(self):
        return (self.added + self.folded + self.merged + self.tightened
                + self.retired)

    # Per million tokens, read and written, at list price. Cache reads are
    # counted in input_tokens at full price, so this is a ceiling, said as
    # "about". A Tend run is on the Max plan and has no API cost.
    PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
              "claude-opus-5": (5.0, 25.0)}
    TEND = "tend"

    @property
    def is_tend(self):
        return (self.model or "") == self.TEND

    @property
    def estimated_cost(self):
        price = self.PRICES.get(self.model or "")
        if price is None or not (self.input_tokens or self.output_tokens):
            return None
        return round((self.input_tokens or 0) / 1e6 * price[0] + (self.output_tokens or 0) / 1e6 * price[1], 2)

    def __repr__(self):
        return f"<CuratorRun {self.started_at} {self.status}>"


class VolumeInbox(db.Model):
    """A file the nightly service made, waiting for the web service to put it
    on the volume (volume_files.py). cost-sync has no volume and no way to
    reach the web's door without a key it does not hold, but it has the
    database, so it leaves the bytes here and the web moves them within a
    minute. A row lives only until then."""

    __tablename__ = "volume_inbox"
    __table_args__ = (db.UniqueConstraint("folder", "name", name="uq_volume_inbox_folder_name"),)

    id = db.Column(db.Integer, primary_key=True)
    folder = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class NightRun(db.Model):
    """One run of the nightly cost-sync job, with a result per step
    (night_log.py). Needs attention reads the newest: a failed step, or no run
    finished in a day and a bit, is one row there."""

    __tablename__ = "night_runs"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    # running, ok, partial (some steps failed) or failed (all of them).
    status = db.Column(db.String(10), nullable=False, default="running", server_default="running")
    steps_json = db.Column(db.Text, default="[]")

    @property
    def steps(self):
        import json
        try:
            return json.loads(self.steps_json or "[]")
        except ValueError:
            return []

    @steps.setter
    def steps(self, value):
        import json
        self.steps_json = json.dumps(value or [])

    @property
    def failed_steps(self):
        return [s for s in self.steps if not s.get("ok")]

    def __repr__(self):
        return f"<NightRun {self.started_at} {self.status}>"


class RailwayService(db.Model):
    """One Railway service in one environment, as the nightly read last saw it
    (railway_watch.py): its repo, its domains and its latest deploy.

    One account-token query a night per workspace answers what used to be
    typed or remembered: which Railway project is which build (ServiceMapping,
    written only on a single unambiguous match and only into an empty field),
    which tile it serves (AppLink.railway_url), what is live with no tile, and
    whether the latest deploy worked and is the branch's head.
    """

    __tablename__ = "railway_services"
    __table_args__ = (
        db.UniqueConstraint("service_ref", "environment", name="uq_railway_services_service_env"),
    )

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey(
        "service_providers.id", ondelete="CASCADE", name="fk_railway_services_provider_id"),
        nullable=True, index=True)
    project_ref = db.Column(db.String(64), nullable=False, index=True)
    project_name = db.Column(db.String(200), default="")
    service_ref = db.Column(db.String(64), nullable=False)
    service_name = db.Column(db.String(200), default="")
    environment = db.Column(db.String(60), nullable=False, default="production")
    repo = db.Column(db.String(200), nullable=True, index=True)
    image = db.Column(db.String(300), nullable=True)
    domains_json = db.Column(db.Text, default="[]")
    custom_domains_json = db.Column(db.Text, default="[]")
    deploy_status = db.Column(db.String(20), nullable=True)
    deploy_commit = db.Column(db.String(64), nullable=True)
    deploy_branch = db.Column(db.String(120), nullable=True)
    deployed_at = db.Column(db.DateTime, nullable=True)
    healthcheck_path = db.Column(db.String(200), nullable=True)
    pre_deploy = db.Column(db.String(300), nullable=True)
    # The branch's head on GitHub when the deploy was last read.
    branch_head = db.Column(db.String(64), nullable=True)
    branch_head_at = db.Column(db.DateTime, nullable=True)
    seen_at = db.Column(db.DateTime, nullable=True)
    # "Not an app" pressed on the list of live services with no tile.
    ignored = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    provider = db.relationship("ServiceProvider")

    @property
    def domains(self):
        """Every address it answers on, Railway's own and custom."""
        import json
        try:
            return json.loads(self.domains_json or "[]")
        except ValueError:
            return []

    @property
    def custom_domains(self):
        import json
        try:
            return json.loads(self.custom_domains_json or "[]")
        except ValueError:
            return []

    @property
    def dashboard_url(self):
        return f"https://railway.com/project/{self.project_ref}/service/{self.service_ref}"

    @property
    def is_database(self):
        """A template database, not something anybody visits."""
        if self.repo:
            return False
        image = (self.image or "").lower()
        name = (self.service_name or "").lower()
        return any(w in image or w == name for w in
                   ("railwayapp-templates", "postgres", "redis", "mysql", "mongo"))

    def __repr__(self):
        return f"<RailwayService {self.project_name}/{self.service_name} {self.environment}>"


class SiteCheck(db.Model):
    """The last nightly answer from one live address (live_watch.py): status,
    where it ended up, the certificate's expiry, and since when it has been
    down. Every tile's URL and every map surface's URL is checked."""

    __tablename__ = "site_checks"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), nullable=False, unique=True)
    host = db.Column(db.String(255), nullable=False, default="", index=True)
    status_code = db.Column(db.Integer, nullable=True)
    ok = db.Column(db.Boolean, nullable=True)
    final_url = db.Column(db.String(500), nullable=True)
    error = db.Column(db.String(300), nullable=True)
    cert_expires_on = db.Column(db.Date, nullable=True)
    checked_at = db.Column(db.DateTime, nullable=True)
    down_since = db.Column(db.DateTime, nullable=True)
    # Nights in a row it has failed; two is a row on Needs attention.
    fail_nights = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def __repr__(self):
        return f"<SiteCheck {self.url} ok={self.ok}>"


class DomainWatch(db.Model):
    """When a domain the board's sites live on runs out, and whether it renews
    itself. Cloudflare's registrar says both; any other registrar is read off
    public RDAP, which gives the date and never the renewal setting."""

    __tablename__ = "domain_watches"

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), nullable=False, unique=True)
    expires_on = db.Column(db.Date, nullable=True)
    auto_renew = db.Column(db.Boolean, nullable=True)
    registrar = db.Column(db.String(40), nullable=True)
    checked_at = db.Column(db.DateTime, nullable=True)
    error = db.Column(db.String(300), nullable=True)

    def __repr__(self):
        return f"<DomainWatch {self.domain} {self.expires_on}>"


class MvpPackage(db.Model):
    """One client's build, assembled while they are still talking.

    The page this backs is open during the first call. Products and features
    get tapped in as the client names them, and none of it requires the client
    to have agreed to anything - a package with no contract behind it is the
    normal case, which is why it lives here and not on a project. It holds no
    money (Michael, 2026-11-04): what a build costs is typed on the SOW.

    From a finished package come the two documents that start a build: the
    statement of work, prefilled with what was chosen, and the build prompt -
    everything the catalogue knows about the chosen features stitched into
    one piece of text a fresh Claude session starts from.
    """

    __tablename__ = "mvp_packages"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    # What they are trying to do, in their words, written down while they say
    # it. This becomes the SOW's project description and the prompt's opening.
    summary = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="scoping")
    # The whole app this build starts from, when there is one: its blueprint
    # opens the prompt and the features below are the tweaks.
    blueprint_id = db.Column(db.Integer, db.ForeignKey(
        "app_blueprints.id", ondelete="SET NULL", name="fk_mvp_packages_blueprint_id"),
        nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    blueprint = db.relationship("AppBlueprint")
    client = db.relationship("Client", backref=db.backref(
        "mvp_packages", lazy="dynamic", cascade="all, delete-orphan"))
    items = db.relationship("MvpPackageItem", back_populates="package",
                            cascade="all, delete-orphan",
                            order_by="MvpPackageItem.sort_order,"
                                     " MvpPackageItem.id")

    STATUSES = (
        ("scoping", "Being scoped"),
        ("ready", "Ready to build"),
        ("contracted", "Contracted"),
        ("parked", "Parked"),
    )
    STATUS_LABELS = dict(STATUSES)

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def product_items(self):
        return [i for i in self.items if i.kind == "product"]

    @property
    def feature_items(self):
        return [i for i in self.items if i.kind == "feature"]

    def __repr__(self):
        return f"<MvpPackage {self.name} for client {self.client_id}>"


class MvpPackageItem(db.Model):
    """One chosen thing on a package: a product that will run, or a feature
    that will get used.

    The name is copied on at the moment of choosing and then owned by the
    package - renaming a catalogue row must not rewrite what a client was
    shown. The catalogue links are SET NULL for the same reason: retiring a
    row must not erase the record of having offered it, so `kind` is its own
    column rather than being inferred from which foreign key survived.
    """

    __tablename__ = "mvp_package_items"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(db.Integer,
                           db.ForeignKey("mvp_packages.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, default="feature")
    feature_id = db.Column(db.Integer,
                           db.ForeignKey("features.id", ondelete="SET NULL"),
                           nullable=True, index=True)
    product_id = db.Column(db.Integer,
                           db.ForeignKey("products.id", ondelete="SET NULL"),
                           nullable=True, index=True)
    name = db.Column(db.String(160), nullable=False)
    # Anything said about this one in particular - "their version of tagging
    # is by crew, not costume". Carried into the prompt beside the feature.
    notes = db.Column(db.Text, default="")
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    package = db.relationship("MvpPackage", back_populates="items")
    feature = db.relationship("Feature")
    product = db.relationship("Product")

    def __repr__(self):
        return f"<MvpPackageItem {self.kind} {self.name!r}>"


class Lead(db.Model):
    """A business in the trade area that has not bought anything yet.

    Every column here came out of a public record, and the ones that stay
    empty are as honest as the ones that fill: no free source publishes the
    revenue or the headcount of a private firm in a town of 25,000, so those
    two are hand-typed when somebody learns them on a call and are never
    guessed. What IS public turns out to be the better signal anyway - a
    business with a sales tax permit, no website and eleven years of trading
    is a better call than a guessed dollar figure ever was.

    `dedupe_key` is what makes the import re-runnable: it is the trading name
    and the street, flattened, so the same shop arriving from the Comptroller
    and from OpenStreetMap lands on one row and the second source only fills
    the gaps the first left.
    """

    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)

    # What it trades as, which is what she will say on the phone, and the
    # entity behind it, which is what the state calls it. For a sole trader
    # the second is usually a person's name, and that is the owner.
    name = db.Column(db.String(200), nullable=False, index=True)
    legal_name = db.Column(db.String(200), default="")
    owner_name = db.Column(db.String(160), default="")

    address = db.Column(db.String(240), default="")
    city = db.Column(db.String(80), default="", index=True)
    state = db.Column(db.String(10), default="TX")
    zip_code = db.Column(db.String(12), default="")
    county = db.Column(db.String(60), default="")
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)

    phone = db.Column(db.String(40), default="")
    email = db.Column(db.String(200), default="")
    website = db.Column(db.String(300), default="")

    industry = db.Column(db.String(120), default="")
    naics = db.Column(db.String(10), default="")
    entity_type = db.Column(db.String(60), default="")
    # When the state first saw them selling. The age of a business is public
    # where its size is not, and it says plenty.
    started_on = db.Column(db.Date, nullable=True)
    # How many outlets the same taxpayer runs statewide. One is a shop; nine
    # is a chain, and that is a size signal nobody had to publish.
    locations = db.Column(db.Integer, default=1)

    # Left empty by the import on purpose. See the class note.
    employees = db.Column(db.Integer, nullable=True)
    revenue = db.Column(db.Float, nullable=True)

    # A page on somebody else's platform is not a website, and the gap
    # between the two is the pitch: a business with 4,000 followers and
    # nowhere to send them is the easiest call on the list.
    social = db.Column(db.String(300), default="")

    taxpayer_number = db.Column(db.String(40), default="", index=True)
    osm_ref = db.Column(db.String(40), default="")
    overture_id = db.Column(db.String(60), default="")
    npi = db.Column(db.String(20), default="")
    sources = db.Column(db.String(200), default="")
    # When somebody last went looking for a website. Null means nobody has,
    # and the board must not say "no website" about a row that is null: an
    # empty column and an established absence are different facts.
    website_checked_at = db.Column(db.DateTime, nullable=True)
    dedupe_key = db.Column(db.String(240), nullable=False, unique=True)

    stage = db.Column(db.String(30), default="lead", index=True)
    stage_changed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, default="")

    # Set when she converts one. SET NULL rather than CASCADE: deleting a
    # client must not erase the record of where they came from.
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    converted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client")
    people = db.relationship("LeadPerson", back_populates="lead",
                             cascade="all, delete-orphan",
                             order_by="LeadPerson.sort_order, LeadPerson.id")
    # Newest first: the only question asked of this list is "when did we last
    # try them, and what happened".
    touches = db.relationship("LeadTouch", back_populates="lead",
                              cascade="all, delete-orphan",
                              order_by="LeadTouch.occurred_on.desc(), LeadTouch.id.desc()")

    @property
    def last_touch(self):
        return self.touches[0] if self.touches else None

    @property
    def days_since_touch(self):
        last = self.last_touch
        if not last or not last.occurred_on:
            return None
        return (date.today() - last.occurred_on).days

    @property
    def channels_tried(self):
        used = {t.channel for t in self.touches}
        return [key for key, _ in CONTACT_CHANNEL_CHOICES if key in used]

    @property
    def reached(self):
        """Has anybody ever actually got a person on the other end."""
        return any(t.outcome in LEAD_OUTCOMES_REACHED for t in self.touches)

    @property
    def years_trading(self):
        if not self.started_on:
            return None
        return max(0, (date.today() - self.started_on).days // 365)

    @property
    def has_website(self):
        return bool((self.website or "").strip())

    @property
    def social_only(self):
        """A page on a platform and nowhere of their own."""
        return bool((self.social or "").strip()) and not self.has_website

    @property
    def no_website(self):
        """Somebody looked and found nothing. Not the same as a blank column,
        which only means nobody has looked yet."""
        return bool(self.website_checked_at) and not self.has_website

    @property
    def stage_label(self):
        return dict(CLIENT_STAGE_CHOICES).get(self.stage, self.stage)

    @property
    def primary_person(self):
        return self.people[0] if self.people else None

    def __repr__(self):
        return f"<Lead {self.name!r} {self.city}>"


class LeadPerson(db.Model):
    """Somebody to ask for by name at that business.

    Separate rows rather than columns on the lead, because the owner, the
    manager and the person who answers the phone are three different calls
    and the one who is worth ringing changes.
    """

    __tablename__ = "lead_people"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    role = db.Column(db.String(120), default="")
    email = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    source = db.Column(db.String(60), default="")
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    lead = db.relationship("Lead", back_populates="people")

    def __repr__(self):
        return f"<LeadPerson {self.name!r}>"


class LeadTouch(db.Model):
    """One attempt to reach a lead, and what came of it.

    ClientContact is the same idea one stage later and this deliberately
    speaks its vocabulary (CONTACT_CHANNEL_CHOICES, a date rather than a
    timestamp). The column it adds is `outcome`: cold calling a town, the
    difference between "rang them" and "rang them, wrong number" is the
    difference between a list that gets better and a list that gets rung
    twice.
    """

    __tablename__ = "lead_touches"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # Who did it. SET NULL: switching an account off must not delete the
    # history of the calls that person made.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    channel = db.Column(db.String(20), nullable=False, default="phone")
    outcome = db.Column(db.String(20), nullable=False, default="no_answer")
    went = db.Column(db.String(10), default="")
    occurred_on = db.Column(db.Date, nullable=False, default=lambda: date.today())
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    lead = db.relationship("Lead", back_populates="touches")
    user = db.relationship("User")

    @property
    def channel_label(self):
        return dict(CONTACT_CHANNEL_CHOICES).get(self.channel, self.channel)

    @property
    def outcome_label(self):
        return dict(LEAD_OUTCOME_CHOICES).get(self.outcome, self.outcome)

    @property
    def went_label(self):
        return dict(LEAD_WENT_CHOICES).get(self.went or "", "")

    def __repr__(self):
        return f"<LeadTouch {self.channel} {self.outcome} {self.occurred_on}>"
