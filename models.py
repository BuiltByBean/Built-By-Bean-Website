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
    role = db.Column(db.String(20), default="admin")
    must_change_password = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    phase = db.Column(db.String(30), default="discovery")
    budget = db.Column(db.Float, nullable=True)
    mvp_date = db.Column(db.Date, nullable=True)
    maintenance_days = db.Column(db.Integer, default=30)
    status = db.Column(db.String(20), default="active")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", back_populates="projects")
    tickets = db.relationship("Ticket", back_populates="project", lazy="dynamic")
    time_entries = db.relationship("TimeEntry", backref="project", lazy="dynamic")

    @property
    def free_maintenance_end(self):
        if self.mvp_date:
            return self.mvp_date + timedelta(days=self.maintenance_days or 30)
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
        """Material expenses only — excludes auto-generated billable time expenses."""
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
    def total_expenses(self):
        # Material expenses only — exclude time-entry-linked billable time rows.
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
    time_entry = db.relationship("TimeEntry", backref=db.backref("expense", uselist=False))
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

    user = db.relationship("User", backref=db.backref("timer_session", uselist=False))
    project = db.relationship("Project")

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

    client = db.relationship("Client", backref="invoices")
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
    to know — which client this was for, which project, which of our documents
    it came from — plus the last status seen, so a list can be drawn without
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
    # engagement_letter | sow | document — what produced the PDF, so the list
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
    given — which is why it is normalised on the way in.
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
    # the code behind it. Both optional — a page inside this app has neither.
    railway_url = db.Column(db.String(500), nullable=True)
    github_url = db.Column(db.String(500), nullable=True)

    # The engagement this app belongs to, where there is one. Nullable because
    # half the board is mine — Bible Study, Pluralism, Data Dungeon — and those
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
