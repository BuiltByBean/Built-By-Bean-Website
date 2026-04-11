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

TASK_STATUS_CHOICES = [
    ("todo", "To Do"),
    ("in_progress", "In Progress"),
    ("review", "Review"),
    ("done", "Done"),
]

PRIORITY_CHOICES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("urgent", "Urgent"),
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


class ClientForm(FlaskForm):
    name = StringField("Client Name", validators=[DataRequired()])
    email = StringField("Email", validators=[Optional(), Email()])
    phone = StringField("Phone", validators=[Optional()])
    company = StringField("Company", validators=[Optional()])
    address = TextAreaField("Address", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])


class ProjectForm(FlaskForm):
    name = StringField("Project Name", validators=[DataRequired()])
    client_id = SelectField("Client", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    phase = SelectField("Phase", choices=PHASE_CHOICES, default="discovery")
    budget = FloatField("Budget ($)", validators=[Optional(), NumberRange(min=0)])
    mvp_date = DateField("MVP Delivery Date", validators=[Optional()])
    status = SelectField("Status", choices=PROJECT_STATUS_CHOICES, default="active")
    notes = TextAreaField("Notes", validators=[Optional()])


class TaskForm(FlaskForm):
    title = StringField("Task Title", validators=[DataRequired()])
    project_id = SelectField("Project", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional()])
    detailed_notes = TextAreaField("Detailed Notes", validators=[Optional()])
    status = SelectField("Status", choices=TASK_STATUS_CHOICES, default="todo")
    priority = SelectField("Priority", choices=PRIORITY_CHOICES, default="medium")
    due_date = DateField("Due Date", validators=[Optional()])


class ExpenseForm(FlaskForm):
    client_id = SelectField("Client", coerce=int, validators=[Optional()])
    project_id = SelectField("Project", coerce=int, validators=[Optional()])
    task_id = SelectField("Task", coerce=int, validators=[Optional()])
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
    task_id = SelectField("Task (Optional)", coerce=int, validators=[Optional()])
    date = DateField("Date", validators=[DataRequired()])
    hours = FloatField("Hours", validators=[DataRequired(), NumberRange(min=0.25)])
    description = TextAreaField("Description", validators=[Optional()])
    rate_type = SelectField("Rate Type", choices=RATE_TYPE_CHOICES, default="maintenance")
