import re
from datetime import datetime, timezone, date, timedelta
from flask_sqlalchemy import SQLAlchemy
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
    ingest_secret = db.Column(db.String(120), default="")
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
    # Newest first, because the only question anybody asks of this list is
    # "when did we last try them".
    contacts = db.relationship("ClientContact", back_populates="client",
                               cascade="all, delete-orphan",
                               order_by="ClientContact.occurred_on.desc(),"
                                        " ClientContact.id.desc()")

    @property
    def last_contact(self):
        """The most recent attempt, or None if nobody has tried yet."""
        return self.contacts[0] if self.contacts else None

    @property
    def channels_tried(self):
        """Which channels have been used, in the order they are offered.

        A set would be the obvious type and the wrong one: the row renders
        this, and "Email · Phone" flipping to "Phone · Email" between page
        loads reads as a change when nothing changed.
        """
        used = {c.channel for c in self.contacts}
        return [key for key, _ in CONTACT_CHANNEL_CHOICES if key in used]

    @property
    def days_since_contact(self):
        last = self.last_contact
        if not last or not last.occurred_on:
            return None
        return (date.today() - last.occurred_on).days

    @property
    def active_projects_count(self):
        return self.projects.filter_by(status="active").count()

    @property
    def total_revenue(self):
        return sum(inv.amount_paid for inv in self.invoices if inv.status == "paid")

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


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    # Nothing reaches this board before it is under contract, so that is
    # where a project starts.
    phase = db.Column(db.String(30), default="contracted")
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
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"),
                           nullable=True, index=True)

    # Where it came from. `origin` is the app's own slug ("kuper", "talent-booker"),
    # `origin_ticket_id` is its id over there, and the pair is unique so the same
    # ticket arriving twice updates rather than duplicates. A ticket raised here
    # by hand carries origin "local" and no origin id.
    origin = db.Column(db.String(40), nullable=False, default="local", index=True)
    origin_ticket_id = db.Column(db.Integer, nullable=True)
    origin_url = db.Column(db.String(500), default="")

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
    )

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

    client = db.relationship("Client", backref="expenses")
    project = db.relationship("Project", backref="expenses")
    ticket = db.relationship("Ticket", back_populates="expenses")
    time_entry = db.relationship("TimeEntry", backref=db.backref(
        "expense", uselist=False, cascade="all, delete-orphan"))
    children = db.relationship("Expense", backref=db.backref("parent_expense", remote_side="Expense.id"), lazy="dynamic")

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
    amount_due = db.Column(db.Float, default=0.0)
    due_date = db.Column(db.Date, nullable=True)
    period_start = db.Column(db.Date, nullable=True)
    period_end = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, default="")
    sent_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
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
    # For a vendor whose API will not report spend. Railway's schema is all
    # CPU, memory, disk and network and has no measurement denominated in
    # money, so the only way to book it is a figure set here once.
    monthly_cost = db.Column(db.Float, nullable=True)
    # Day of the month the charge lands, for a flat provider. A vendor whose
    # API reports real charges carries their dates already and leaves this null.
    billing_day = db.Column(db.Integer, nullable=True)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    sync_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    mappings = db.relationship("ServiceMapping", back_populates="provider",
                               cascade="all, delete-orphan", lazy="dynamic")
    cost_entries = db.relationship("ServiceCostEntry", back_populates="provider",
                                   cascade="all, delete-orphan", lazy="dynamic")

    def __repr__(self):
        return f"<ServiceProvider {self.display_name}>"


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
    expense = db.relationship("Expense", backref=db.backref("service_cost_entry", uselist=False))

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
    # The one-click link that signs them in and opens the ceremony. Kept
    # because without SMTP it is the only way the client ever gets it, and
    # because "resend the link" is the most common thing anyone asks for.
    signing_url = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="sent")
    # Whether the portal actually emailed them, or only wrote to its outbox.
    mail_mode = db.Column(db.String(10), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    synced_at = db.Column(db.DateTime, nullable=True)

    # What the client said when they would not sign it. The portal collects a
    # reason on decline; without this it lived only in an email, which is the
    # one place a negotiation cannot be picked up from later.
    decline_reason = db.Column(db.Text, nullable=True)
    declined_at = db.Column(db.DateTime, nullable=True)

    # The form that produced the document, so a revision starts from what was
    # actually sent rather than from a blank page and somebody's memory.
    form_json = db.Column(db.Text, nullable=True)

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
    def kind_label(self):
        return {
            "engagement_letter": "Engagement letter",
            "sow": "Statement of work",
            "addon": "Add-on agreement",
            "addendum": "Addendum",
            "hosting": "Hosting agreement",
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

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def is_external(self):
        """Whether following this leaves the app, and so wants a new tab."""
        return self.url.startswith("http://") or self.url.startswith("https://")

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
    things. The two are priced and sold differently, which is why they are
    two tables and not one with a flag.

    Three jobs, in the order they get used:

    Pricing. A number per feature turns a phone call into an estimate while
    the client is still talking, instead of a quote written that evening from
    memory.

    Recall. "Here is what I have built before" is hard to answer from a list
    of repositories, and the answer decides what gets offered.

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

    # What this contributes to an estimate. Nullable, because plenty of these
    # are a morning's work bundled into the build and pricing them
    # individually would be pricing a screen.
    typical_value = db.Column(db.Float, nullable=True)

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
    # capability that gets offered and priced. A `rule` is the layer under
    # that: a way of building that must not be broken, regardless of which
    # features were bought - the tojson quoting, the sticky bars, the
    # migration guards. Rules never appear in the MVP picker and never carry
    # a price; every one of them rides into every build prompt.
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


class Note(db.Model):
    """Something to do that no other page on the board owns.

    A ticket belongs to whoever raised it and is answerable to them. A time
    entry belongs to a project. This is the rest of it: the things that have
    to happen for the business, or about a client, that have nowhere else to
    live. Nobody is waiting on a reply to one of these, which is exactly why
    they get forgotten and why they need a list.

    Everything it points at is OPTIONAL and none of it is exclusive. A note
    can be about a client and the project it is for and the playbook being
    followed on it at the same time, because that is how the thought arrives.
    A note with nothing attached is the common case and is not lesser.

    Done is a timestamp rather than a flag, so "what did I clear this week"
    is a query rather than a second column that has to be kept in step with
    the first.
    """

    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")

    done_at = db.Column(db.DateTime, nullable=True, index=True)
    # A date, not a datetime. Nothing here is due at 3pm, and a time nobody
    # meant would make every one of these look late by lunchtime.
    due_on = db.Column(db.Date, nullable=True, index=True)

    # What it is about. SET NULL rather than CASCADE on every one: closing a
    # project does not mean the note about it was done, and a note that loses
    # its link still has its words. The same call AppLink.project_id makes.
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="SET NULL", name="fk_notes_client_id"),
        nullable=True, index=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="SET NULL", name="fk_notes_project_id"),
        nullable=True, index=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="SET NULL", name="fk_notes_product_id"),
        nullable=True, index=True)
    playbook_id = db.Column(
        db.Integer,
        db.ForeignKey("playbooks.id", ondelete="SET NULL", name="fk_notes_playbook_id"),
        nullable=True, index=True)

    # The backref is "todos", not "notes": Client, Project and Product each
    # already carry a free-text notes column, and a relationship of the same
    # name does not collide quietly, it refuses to map at all and takes every
    # other model down with it.
    client = db.relationship("Client", backref=db.backref("todos", lazy="select"))
    project = db.relationship("Project", backref=db.backref("todos", lazy="select"))
    product = db.relationship("Product", backref=db.backref("todos", lazy="select"))
    playbook = db.relationship("Playbook", backref=db.backref("todos", lazy="select"))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    @property
    def is_done(self):
        return self.done_at is not None

    @property
    def is_overdue(self):
        """Past its date and still open. A done note is never late."""
        return bool(self.due_on and not self.is_done and self.due_on < date.today())

    @property
    def days_until_due(self):
        """Negative when it has gone by. None when no date was set."""
        return None if not self.due_on else (self.due_on - date.today()).days

    @property
    def links(self):
        """What this is about, as (label, url_endpoint, kwargs) to render.

        One place decides the order, so the row, the filters and any future
        page cannot disagree about which attachment leads.
        """
        out = []
        if self.client:
            out.append(("client", self.client.name,
                        "pm.client_detail", {"id": self.client_id}))
        if self.project:
            out.append(("project", self.project.name,
                        "pm.project_detail", {"id": self.project_id}))
        if self.product:
            out.append(("product", self.product.name,
                        "products.products_index", {}))
        if self.playbook:
            out.append(("playbook", self.playbook.display_name,
                        "playbooks.playbook_detail", {"slug": self.playbook.slug}))
        return out

    def __repr__(self):
        return f"<Note {self.id} {self.title[:30]!r}>"


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

    client = db.relationship("Client", backref=db.backref("messages", lazy="dynamic"))

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

    The policy is by shape, not by trust. Anything ADDITIVE - a lesson
    appended, a new rule or feature created - applies on arrival, because it
    cannot damage what was already there and can be reverted from the inbox
    in one press. Anything that REPLACES existing words waits as `pending`
    until Michael accepts it. `previous` is the snapshot that makes revert
    possible; `payload_json` carries a create, whose fields do not fit one
    column.
    """

    __tablename__ = "catalogue_proposals"

    id = db.Column(db.Integer, primary_key=True)
    # feature | rule | playbook | product
    kind = db.Column(db.String(10), nullable=False)
    target_slug = db.Column(db.String(80), nullable=True, index=True)
    # The column being changed, or "*" for a create.
    field = db.Column(db.String(40), nullable=False)
    # append | replace | create
    mode = db.Column(db.String(10), nullable=False)
    proposed = db.Column(db.Text, default="")
    previous = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, default="")
    # Which project's session learned it. A change with no provenance is a
    # change nobody can weigh.
    project = db.Column(db.String(120), default="")
    # applied (auto) | pending | accepted | rejected | reverted
    status = db.Column(db.String(10), nullable=False, default="pending", index=True)
    payload_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = db.Column(db.DateTime, nullable=True)

    KIND_LABELS = {"feature": "Feature", "rule": "Rule",
                   "playbook": "Playbook", "product": "Product"}

    @property
    def is_live(self):
        """Whether the change is currently in the catalogue."""
        return self.status in ("applied", "accepted")

    def __repr__(self):
        return f"<CatalogueProposal {self.kind}:{self.target_slug} {self.mode} {self.status}>"


class MvpPackage(db.Model):
    """One client's build, assembled while they are still talking.

    The page this backs is open during the first call. Products and features
    get tapped in as the client names them, the estimate keeps a running
    answer to "what would that cost", and none of it requires the client to
    have agreed to anything - a package with no contract behind it is a quote
    waiting, not an error, which is why it lives here and not on a project.

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
    # A quoted number that is not the sum of the parts. Null means the
    # estimate is the arithmetic; set, it is what was actually said on the
    # phone, and the arithmetic becomes a footnote.
    price_override = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", backref=db.backref(
        "mvp_packages", lazy="dynamic", cascade="all, delete-orphan"))
    items = db.relationship("MvpPackageItem", back_populates="package",
                            cascade="all, delete-orphan",
                            order_by="MvpPackageItem.sort_order,"
                                     " MvpPackageItem.id")

    STATUSES = (
        ("scoping", "Being scoped"),
        ("ready", "Ready to quote"),
        ("contracted", "Contracted"),
        ("parked", "Parked"),
    )
    STATUS_LABELS = dict(STATUSES)

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def items_total(self):
        return sum(i.price for i in self.items if i.price)

    @property
    def estimate(self):
        """What this package costs: the number said out loud, or the sum."""
        return self.price_override if self.price_override is not None \
            else self.items_total

    @property
    def monthly_estimate(self):
        return sum(i.monthly_price for i in self.items if i.monthly_price)

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

    The name and price are copied on at the moment of choosing and then owned
    by the package - repricing the catalogue must not silently reprice a
    quote somebody already heard. The catalogue links are SET NULL for the
    same reason: retiring a row must not erase the record of having offered
    it, so `kind` is its own column rather than being inferred from which
    foreign key survived.
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
    price = db.Column(db.Float, nullable=True)
    monthly_price = db.Column(db.Float, nullable=True)
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
