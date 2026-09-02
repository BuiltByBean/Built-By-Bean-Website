from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SelectField, FloatField, DateField, PasswordField, DecimalField, BooleanField
from wtforms.validators import DataRequired, Email, Optional, NumberRange

PHASE_CHOICES = [
    ("discovery", "Discovery"),
    ("proposal", "Proposal"),
    ("contracted", "Contracted"),
    ("mvp", "MVP"),
    ("live", "Live"),
]

PROJECT_STATUS_CHOICES = [
    ("active", "Active"),
    ("on-hold", "On Hold"),
    ("completed", "Completed"),
    ("archived", "Archived"),
]

# Where the work has got to, and nothing else. The old task words (todo,
# in_progress, review, done) described my own queue; these describe a request
# somebody made, which is what a ticket is. They match the vocabulary the
# client apps already use, so a ticket does not change meaning in transit.
TICKET_STATUS_CHOICES = [
    ("new", "New"),
    ("in-progress", "In progress"),
    ("resolved", "Resolved"),
    ("dismissed", "Dismissed"),
]

# How badly the person who raised it needs it. Their voice, not my triage call,
# which is why "medium" is gone: nobody reporting a problem calls it medium.
# Ordered most urgent first, and that order IS the board's sort order.
PRIORITY_CHOICES = [
    ("urgent", "Urgent"),
    ("soon", "Soon"),
    ("normal", "Normal"),
    ("backlog", "Backlog"),
]

TICKET_CATEGORY_CHOICES = [
    ("bug", "Bug"),
    ("feature", "Feature"),
    ("enhancement", "Enhancement"),
    ("other", "Other"),
]

# Blank is deliberately first and deliberately not "Free": an unclassified
# ticket has to stay distinguishable from a no-charge one, or undecided work
# gets presented on an invoice as free.
BILLING_BUCKET_CHOICES = [
    ("", "Not classified"),
    ("free", "Free fix"),
    ("maintenance", "Maintenance ($100/hr)"),
    ("new", "New development ($200/hr)"),
]

RATE_TYPE_CHOICES = [
    ("maintenance", "Maintenance ($100/hr)"),
    ("new_feature", "New Feature ($200/hr)"),
    ("mvp_build", "MVP Build (flat fee)"),
]

FREQUENCY_CHOICES = [
    ("", "One-time"),
    ("weekly", "Weekly"),
    ("biweekly", "Bi-weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("yearly", "Yearly"),
]

EXPENSE_CATEGORY_CHOICES = [
    ("software", "Software"),
    ("hosting", "Hosting"),
    ("design", "Design"),
    ("hardware", "Hardware"),
    ("travel", "Travel"),
    ("subcontractor", "Subcontractor"),
    ("billable_time", "Billable Time"),
    ("service_cost", "Service Cost"),
    ("misc", "Miscellaneous"),
]


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])


class SetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired()])
    confirm = PasswordField("Confirm Password", validators=[DataRequired()])


# Defined next to the columns they constrain rather than here, because the
# Client model needs the channel order to render what has been tried. Re-
# exported so callers keep importing every choice list from one place.
from models import CLIENT_STAGE_CHOICES, CONTACT_CHANNEL_CHOICES  # noqa: E402,F401


class ContactLogForm(FlaskForm):
    """One attempt to reach a business.

    The note is where the useful part lives — "left a voicemail", "spoke to
    the owner, call back in September" — so it is the field with the room.
    """

    channel = SelectField("How", choices=CONTACT_CHANNEL_CHOICES, default="phone")
    occurred_on = DateField("When", validators=[Optional()])
    note = TextAreaField("What happened", validators=[Optional()])


class ClientForm(FlaskForm):
    name = StringField("Client Name", validators=[DataRequired()])
    stage = SelectField("Stage", choices=CLIENT_STAGE_CHOICES, default="lead")
    email = StringField("Email", validators=[Optional(), Email()])
    phone = StringField("Phone", validators=[Optional()])
    company = StringField("Company", validators=[Optional()])
    address = TextAreaField("Address", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])

    # If this client has an app of their own, these three are how its tickets
    # reach this board and how my replies get back. Empty for a client who has
    # no app, which is the ordinary case.
    origin_slug = StringField("App slug", validators=[Optional()])
    ingest_secret = StringField("Shared secret", validators=[Optional()])
    origin_base_url = StringField("App URL", validators=[Optional()])


class ProjectForm(FlaskForm):
    name = StringField("Project Name", validators=[DataRequired()])
    client_id = SelectField("Client", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    phase = SelectField("Phase", choices=PHASE_CHOICES, default="discovery")
    budget = FloatField("Budget ($)", validators=[Optional(), NumberRange(min=0)])
    mvp_date = DateField("MVP Delivery Date", validators=[Optional()])
    status = SelectField("Status", choices=PROJECT_STATUS_CHOICES, default="active")
    notes = TextAreaField("Notes", validators=[Optional()])


class TicketForm(FlaskForm):
    # The client is required and the project is not. A bug report from a live
    # app belongs to whoever reported it from the moment it lands; it does not
    # become project work until I decide it is, and most never do.
    client_id = SelectField("Client", coerce=int, validators=[DataRequired()])
    project_id = SelectField("Project", coerce=int, validators=[Optional()])
    # Optional, because neither app that feeds this board has one. A ticket
    # with no title is named by its own first sentence.
    title = StringField("Title", validators=[Optional()])
    description = TextAreaField("What's up", validators=[DataRequired()])
    detailed_notes = TextAreaField("Detailed Notes", validators=[Optional()])
    category = SelectField("Kind", choices=TICKET_CATEGORY_CHOICES, default="bug")
    status = SelectField("Status", choices=TICKET_STATUS_CHOICES, default="new")
    priority = SelectField("Priority", choices=PRIORITY_CHOICES, default="normal")
    due_date = DateField("Due Date", validators=[Optional()])


class ExpenseForm(FlaskForm):
    client_id = SelectField("Client", coerce=int, validators=[Optional()])
    project_id = SelectField("Project", coerce=int, validators=[Optional()])
    ticket_id = SelectField("Ticket", coerce=int, validators=[Optional()])
    amount = FloatField("Amount ($)", validators=[DataRequired(), NumberRange(min=0.01)])
    description = StringField("Description", validators=[Optional()])
    category = SelectField("Category", choices=EXPENSE_CATEGORY_CHOICES, default="misc")
    date = DateField("Date", validators=[DataRequired()])
    receipt = FileField("Receipt", validators=[Optional(), FileAllowed(["pdf", "jpg", "jpeg", "png", "webp"], "Files only!")])
    is_recurring = BooleanField("Recurring Expense", default=False)
    frequency = SelectField("Frequency", choices=FREQUENCY_CHOICES, default="", validators=[Optional()])
    recurring_end_date = DateField("End Date (Optional)", validators=[Optional()])


class TimeEntryForm(FlaskForm):
    project_id = SelectField("Project", coerce=int, validators=[DataRequired()])
    ticket_id = SelectField("Ticket (Optional)", coerce=int, validators=[Optional()])
    date = DateField("Date", validators=[DataRequired()])
    hours = FloatField("Hours", validators=[DataRequired(), NumberRange(min=0.25)])
    description = TextAreaField("Description", validators=[Optional()])
    rate_type = SelectField("Rate Type", choices=RATE_TYPE_CHOICES, default="maintenance")
