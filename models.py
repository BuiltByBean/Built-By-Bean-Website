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
    stage = db.Column(db.String(30), default="lead")
    contract_revenue = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    projects = db.relationship("Project", back_populates="client", cascade="all, delete-orphan", lazy="dynamic")
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
    tasks = db.relationship("Task", back_populates="project", cascade="all, delete-orphan", lazy="dynamic")
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


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    parent_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, default="")
    detailed_notes = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="todo")
    priority = db.Column(db.String(20), default="medium")
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = db.relationship("Project", back_populates="tasks")
    subtasks = db.relationship(
        "Task",
        backref=db.backref("parent_task", remote_side="Task.id"),
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="Task.created_at",
    )
    expenses = db.relationship("Expense", back_populates="task", cascade="all, delete-orphan", lazy="dynamic")
    time_entries = db.relationship("TimeEntry", backref="task", lazy="dynamic")
    documents = db.relationship("Document", back_populates="task", cascade="all, delete-orphan", lazy="dynamic")

    @property
    def total_expenses(self):
        return sum(e.amount for e in self.expenses)

    @property
    def total_hours(self):
        return sum(e.hours for e in self.time_entries)

    @property
    def is_subtask(self):
        return self.parent_task_id is not None

    @property
    def subtask_count(self):
        return self.subtasks.count()

    @property
    def completed_subtask_count(self):
        return self.subtasks.filter(Task.status == "done").count()

    @property
    def subtask_progress(self):
        return (self.completed_subtask_count, self.subtask_count)

    def __repr__(self):
        return f"<Task {self.title}>"


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    time_entry_id = db.Column(db.Integer, db.ForeignKey("time_entries.id", ondelete="CASCADE"), nullable=True, unique=True)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(300), default="")
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
    task = db.relationship("Task", back_populates="expenses")
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
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
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


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    filename = db.Column(db.String(300), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    task = db.relationship("Task", back_populates="documents")
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
        db.UniqueConstraint("provider_id", "resource_identifier", "period_start", "period_end",
                            name="uq_service_cost_entry"),
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
