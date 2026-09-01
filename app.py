import os
import math
import uuid
from datetime import datetime, timezone, date, timedelta
from dateutil.relativedelta import relativedelta

import boto3
from botocore.exceptions import ClientError
from sqlalchemy.exc import IntegrityError
from flask import (
    Flask, Blueprint, render_template, redirect, url_for, flash, request, abort,
    send_from_directory, jsonify, Response,
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

from config import Config
import hub
import signadoc_service
import time
from tax_engine import compute as tax_compute
from models import (
    db, Client, Project, Ticket, TicketNote, Expense, TimeEntry, Document, User,
    Invoice, InvoiceLineItem, TimerSession, TaxSetting,
    ServiceProvider, ServiceCostEntry,
    Playbook, PlaybookStep, ProjectPlaybook, ProjectPlaybookStep,
    TICKET_CATEGORIES, TICKET_CATEGORY_LABELS,
    TICKET_STATUSES, TICKET_STATUS_LABELS, TICKET_CLOSED_STATUSES,
    TICKET_PRIORITIES, TICKET_PRIORITY_LABELS,
    TICKET_BILLING_BUCKETS, TICKET_BILLING_LABELS, TICKET_BILLING_RATES,
)
from forms import (
    ClientForm, ProjectForm, TicketForm, ExpenseForm, TimeEntryForm, LoginForm,
    PHASE_CHOICES, PROJECT_STATUS_CHOICES, TICKET_STATUS_CHOICES,
    PRIORITY_CHOICES, RATE_TYPE_CHOICES, EXPENSE_CATEGORY_CHOICES,
    FREQUENCY_CHOICES,
)


# Where a signature field goes on the signature blocks below. The label cell
# runs from the 30mm left margin to 60mm and the underscore rule starts there,
# so a 6mm-tall box from the top of the row sits on the rule rather than
# through it. Millimetres, because that is what fpdf measures in.
SIGN_FIELD_X, SIGN_FIELD_W, SIGN_FIELD_H = 61.0, 86.0, 6.0


def _billable_hours_from_seconds(seconds):
    """Convert elapsed seconds to billable hours, rounded UP to the nearest 15 min
    (0.25h), with a minimum of one quarter-hour for any tracked time."""
    hours = (seconds or 0) / 3600.0
    quarters = math.ceil(hours * 4 - 1e-9)  # tolerance so an exact 0.25 stays 0.25
    return max(0.25, quarters / 4.0)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    pm_bp = Blueprint(
        "pm",
        __name__,
        url_prefix="/admin/pm",
        template_folder="templates/pm",
        static_folder="static/pm",
        static_url_path="/static/pm",
    )

    db.init_app(app)
    migrate = Migrate(app, db)

    # ── Flask-Mail (for Bible Study invites) ──────────────────
    from flask_mail import Mail
    mail = Mail(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = ""

    @login_manager.user_loader
    def load_user(user_id):
        # Bible Study users have IDs prefixed with "bs_"
        uid = str(user_id)
        if uid.startswith("bs_"):
            from bible_study.bs_models import BibleStudyUser
            return db.session.get(BibleStudyUser, int(uid[3:]))
        return db.session.get(User, int(user_id))

    # ── S3 Client ─────────────────────────────────────────────
    _s3_bucket = os.environ.get("AWS_S3_BUCKET")
    _s3_region = os.environ.get("AWS_S3_REGION", "us-east-2")
    _s3_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    _s3_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    _s3_client = boto3.client(
        "s3",
        region_name=_s3_region,
        aws_access_key_id=_s3_access_key,
        aws_secret_access_key=_s3_secret_key,
    ) if (_s3_bucket and _s3_access_key and _s3_secret_key) else None

    with app.app_context():
        if not _s3_client:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "documents"), exist_ok=True)
            os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "receipts"), exist_ok=True)
        db.create_all()

        # Add must_change_password column if it doesn't exist yet
        from sqlalchemy import text
        with db.engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE"))
                conn.commit()
            except Exception:
                pass

        # Add stage and contract_revenue columns to clients if they don't exist
        with db.engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE clients ADD COLUMN stage VARCHAR(30) DEFAULT 'lead'"))
                conn.commit()
            except Exception:
                pass
        with db.engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE clients ADD COLUMN contract_revenue FLOAT DEFAULT 0.0"))
                conn.commit()
            except Exception:
                pass

        # Add maintenance_days column to projects if it doesn't exist
        with db.engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE projects ADD COLUMN maintenance_days INTEGER DEFAULT 30"))
                conn.commit()
            except Exception:
                pass

        # One-time data fix: set J&D Entertainment contract values from existing SOW
        with db.engine.connect() as conn:
            conn.execute(text(
                "UPDATE clients SET stage = 'contracted', contract_revenue = 5000.0 "
                "WHERE name = 'J&D Entertainment' AND (contract_revenue IS NULL OR contract_revenue = 0.0)"
            ))
            conn.commit()

        # Seed default users if they don't exist
        from models import User
        _admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if _admin_password and not User.query.filter(User.username.ilike("Michael.Bean")).first():
            admin = User(
                username="Michael.Bean",
                first_name="Michael",
                last_name="Bean",
                email="michael@builtbybean.com",
                role="admin",
                must_change_password=False,
            )
            admin.set_password(_admin_password)
            db.session.add(admin)
            db.session.commit()

        # Seeded only when an explicit password is supplied. This repo is
        # public, so a literal password here is a published admin credential.
        _dev_password = os.environ.get("DEV_PASSWORD", "")
        if _dev_password and not User.query.filter(User.username.ilike("tlane")).first():
            dev = User(
                username="tlane",
                first_name="T",
                last_name="Lane",
                email="tlane@builtbybean.com",
                role="admin",
                must_change_password=True,
            )
            dev.set_password(_dev_password)
            db.session.add(dev)
            db.session.commit()

        # Ensure the Mbean admin exists. A password is set ONLY when the account
        # is first created, and only from MBEAN_PASSWORD. Booting the app must
        # never reset an existing account's password — the previous version did
        # that on every boot with a hardcoded literal.
        _mbean = User.query.filter(User.username.ilike("Mbean")).first()
        if _mbean is None:
            _mbean_by_email = User.query.filter(User.email.ilike("mbean@builtbybean.com")).first()
            if _mbean_by_email is not None:
                # Same person under an older username: adopt it, leave the
                # password alone.
                _mbean_by_email.username = "Mbean"
                _mbean_by_email.role = "admin"
                db.session.commit()
            else:
                _mbean_password = os.environ.get("MBEAN_PASSWORD", "")
                if _mbean_password:
                    _mbean = User(
                        username="Mbean",
                        first_name="Matthew",
                        last_name="Bean",
                        email="mbean@builtbybean.com",
                        role="admin",
                        must_change_password=False,
                    )
                    _mbean.set_password(_mbean_password)
                    db.session.add(_mbean)
                    db.session.commit()

        # Add stripe_customer_id column if it doesn't exist yet
        with db.engine.connect() as conn2:
            try:
                conn2.execute(text("ALTER TABLE clients ADD COLUMN stripe_customer_id VARCHAR(100)"))
                conn2.commit()
            except Exception:
                pass

        # Add monthly_cost column to service_mappings if it doesn't exist
        with db.engine.connect() as conn3:
            try:
                conn3.execute(text("ALTER TABLE service_mappings ADD COLUMN monthly_cost FLOAT"))
                conn3.commit()
            except Exception:
                pass

        # Migrate old phase values to new ones
        _phase_remap = {"rnd": "proposal", "mvp_delivered": "mvp"}
        for old_val, new_val in _phase_remap.items():
            Project.query.filter_by(phase=old_val).update({"phase": new_val})
        db.session.commit()

    # ── Stripe ──────────────────────────────────────────────
    from stripe_service import init_stripe
    init_stripe(app)

    from pm.stripe_routes import stripe_bp
    app.register_blueprint(stripe_bp)

    # ── Service Costs ───────────────────────────────────────
    from pm.service_costs_routes import service_costs_bp
    app.register_blueprint(service_costs_bp)

    # ── Vendor Playbooks ────────────────────────────────────
    from pm.playbooks_routes import playbooks_bp
    app.register_blueprint(playbooks_bp)

    # ── Tax Estimate ────────────────────────────────────────
    from pm.tax_routes import tax_bp
    app.register_blueprint(tax_bp)

    # ── Signatures (SignaDoc) ───────────────────────────────
    from pm.contract_routes import contracts_bp, send_generated
    app.register_blueprint(contracts_bp)

    # ── My Apps board ───────────────────────────────────────
    from pm.apps_routes import apps_bp
    app.register_blueprint(apps_bp)

    # ── Pluralism Project ──────────────────────────────────
    from pluralism import pluralism_bp
    app.register_blueprint(pluralism_bp)

    # ── Bible Study Project ────────────────────────────────
    from bible_study import bible_study_bp, init_bible_study
    app.register_blueprint(bible_study_bp)
    init_bible_study(app)

    # ── Helpers ──────────────────────────────────────────────

    def allowed_file(filename):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]

    def save_upload(file, subfolder="documents"):
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit(".", 1)[1].lower()
            stored_name = f"{uuid.uuid4().hex}.{ext}"
            if _s3_client:
                s3_key = f"{subfolder}/{stored_name}"
                file_data = file.read()
                try:
                    _s3_client.put_object(
                        Bucket=_s3_bucket,
                        Key=s3_key,
                        Body=file_data,
                        ContentType=file.content_type or "application/octet-stream",
                    )
                except Exception as e:
                    app.logger.error(f"S3 upload failed for {s3_key} (bucket={_s3_bucket}): {e}")
                    # Fall back to local storage
                    folder = os.path.join(app.config["UPLOAD_FOLDER"], subfolder)
                    os.makedirs(folder, exist_ok=True)
                    filepath = os.path.join(folder, stored_name)
                    with open(filepath, "wb") as f:
                        f.write(file_data)
                size = len(file_data)
            else:
                folder = os.path.join(app.config["UPLOAD_FOLDER"], subfolder)
                os.makedirs(folder, exist_ok=True)
                filepath = os.path.join(folder, stored_name)
                file.save(filepath)
                size = os.path.getsize(filepath)
            return stored_name, file.filename, size
        return None, None, 0

    def delete_upload(stored_name, subfolder="documents"):
        if _s3_client and stored_name:
            try:
                _s3_client.delete_object(Bucket=_s3_bucket, Key=f"{subfolder}/{stored_name}")
            except ClientError:
                pass
        else:
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], subfolder, stored_name)
            if os.path.exists(filepath):
                os.remove(filepath)

    def download_upload(stored_name, original_name, subfolder="documents"):
        local_folder = os.path.join(app.config["UPLOAD_FOLDER"], subfolder)
        local_path = os.path.join(local_folder, stored_name) if stored_name else None

        if _s3_client:
            try:
                s3_obj = _s3_client.get_object(Bucket=_s3_bucket, Key=f"{subfolder}/{stored_name}")
                data = s3_obj["Body"].read()
                return Response(
                    data,
                    headers={"Content-Disposition": f'attachment; filename="{original_name}"'},
                    content_type=s3_obj.get("ContentType", "application/octet-stream"),
                )
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "Unknown")
                app.logger.error(
                    f"S3 download failed for {subfolder}/{stored_name} "
                    f"(bucket={_s3_bucket}, code={code}): {e}"
                )
                if local_path and os.path.exists(local_path):
                    return send_from_directory(local_folder, stored_name, as_attachment=True, download_name=original_name)
                if code in ("NoSuchKey", "404"):
                    flash(f"File '{original_name}' is no longer available. It may have been lost during a previous deploy.", "danger")
                else:
                    flash(f"Download failed ({code}). Please try again or contact support.", "danger")
                return redirect(request.referrer or url_for("index"))
            except Exception as e:
                app.logger.error(f"Unexpected download error for {subfolder}/{stored_name}: {e}")
                flash("Download failed due to an unexpected error.", "danger")
                return redirect(request.referrer or url_for("index"))

        if local_path and os.path.exists(local_path):
            return send_from_directory(local_folder, stored_name, as_attachment=True, download_name=original_name)
        flash(f"File '{original_name}' could not be found on the server.", "danger")
        return redirect(request.referrer or url_for("index"))

    # ── Auto-Expense Helpers ──────────────────────────────────

    def _in_free_maintenance(project, rate_type):
        """Check if this work falls within the project's free maintenance window."""
        if rate_type == "maintenance" and project and project.free_maintenance_end:
            if project.free_maintenance_end >= date.today():
                return True
        return False

    def _sync_expense_for_time_entry(entry, project):
        """Billable time is pipeline revenue, not an expense — so we do NOT create a
        mirror expense for it. This used to generate a "billable_time" Expense per
        time entry, which wrongly inflated Total Expenses and cluttered the expenses
        list. Here we just remove any legacy mirror still attached to this entry and
        report whether the entry is billable (used for the save/flash message)."""
        if entry.expense:
            db.session.delete(entry.expense)
        return entry.cost > 0

    # ── Recurring Expense Helpers ─────────────────────────────

    def _advance_date(d, frequency):
        """Advance a date by one frequency interval."""
        if frequency == "weekly":
            return d + timedelta(weeks=1)
        elif frequency == "biweekly":
            return d + timedelta(weeks=2)
        elif frequency == "monthly":
            return d + relativedelta(months=1)
        elif frequency == "quarterly":
            return d + relativedelta(months=3)
        elif frequency == "yearly":
            return d + relativedelta(years=1)
        return d

    def generate_due_recurring_expenses():
        """Create child expenses for any recurring templates that are past due."""
        today = date.today()
        recurring = Expense.query.filter(
            Expense.is_recurring == True,  # noqa: E712
            Expense.next_due_date <= today,
        ).all()

        created = 0
        for parent in recurring:
            # Skip if past end date
            if parent.recurring_end_date and parent.recurring_end_date < today:
                parent.is_recurring = False
                continue

            # Generate all missed periods
            while parent.next_due_date and parent.next_due_date <= today:
                if parent.recurring_end_date and parent.next_due_date > parent.recurring_end_date:
                    parent.is_recurring = False
                    break

                child = Expense(
                    client_id=parent.client_id,
                    project_id=parent.project_id,
                    ticket_id=parent.ticket_id,
                    amount=parent.amount,
                    description=parent.description,
                    category=parent.category,
                    date=parent.next_due_date,
                    parent_expense_id=parent.id,
                )
                db.session.add(child)
                created += 1

                parent.next_due_date = _advance_date(parent.next_due_date, parent.frequency)

        if created:
            db.session.commit()
        return created

    # ── Template Filters ─────────────────────────────────────

    @app.template_filter("format_currency")
    def format_currency(value):
        if value is None:
            return "$0.00"
        return f"${value:,.2f}"

    @app.template_filter("format_date")
    def format_date(value):
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%b %d, %Y")
        if isinstance(value, date):
            return value.strftime("%b %d, %Y")
        return str(value)

    @app.template_filter("format_hours")
    def format_hours(value):
        if value is None:
            return "0h"
        h = int(value)
        m = int((value - h) * 60)
        if m > 0:
            return f"{h}h {m}m"
        return f"{h}h"

    # ── Context Processor ────────────────────────────────────

    # Asset cache-busting version (updates on each process boot → each deploy)
    _asset_version = str(int(datetime.now(timezone.utc).timestamp()))

    def _timer_state(timer):
        """Serialize a TimerSession for the front-end widget."""
        if not timer:
            return None
        return {
            "id": timer.id,
            "elapsed_seconds": round(timer.elapsed_seconds),
            "is_paused": bool(timer.is_paused),
            "rate_type": timer.rate_type,
            "project_id": timer.project_id,
            "project_name": timer.project.name if timer.project else None,
            "description": timer.description or "",
        }

    @app.context_processor
    def inject_features():
        """Which optional parts of the app are switched on right now."""
        return {"time_tracking": app.config.get("FEATURE_TIME_TRACKING", False)}

    @app.context_processor
    def inject_globals():
        active_timer = None
        timer_projects = []
        if current_user.is_authenticated and not str(current_user.get_id()).startswith("bs_"):
            try:
                timer = TimerSession.query.filter_by(user_id=current_user.id).first()
                active_timer = _timer_state(timer)
                timer_projects = [
                    {"id": p.id, "label": f"{p.name} ({p.client.name})"}
                    for p in Project.query.join(Client).filter(Project.status == "active")
                                          .order_by(Project.name).all()
                ]
            except Exception:
                # Table may not exist yet (pre-migration) — fail open, hide widget.
                active_timer = None
                timer_projects = []
        return {
            "now": datetime.now(timezone.utc),
            "asset_version": _asset_version,
            "phase_choices": PHASE_CHOICES,
            "status_choices": PROJECT_STATUS_CHOICES,
            "ticket_status_choices": TICKET_STATUS_CHOICES,
            "priority_choices": PRIORITY_CHOICES,
            "rate_type_choices": RATE_TYPE_CHOICES,
            "expense_category_choices": EXPENSE_CATEGORY_CHOICES,
            "frequency_choices": FREQUENCY_CHOICES,
            "active_timer": active_timer,
            "timer_projects": timer_projects,
        }

    # ── Force password change ─────────────────────────────────
    @app.before_request
    def check_password_change():
        exempt = {"login", "logout", "change_password", "static"}
        if current_user.is_authenticated and current_user.must_change_password:
            if request.endpoint not in exempt:
                return redirect(url_for("change_password"))

    # ── Auth Routes ──────────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("pm.dashboard"))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter(User.username.ilike(form.username.data)).first()
            if user and user.check_password(form.password.data):
                login_user(user)
                return redirect(request.args.get("next") or url_for("pm.dashboard"))
            flash("Invalid username or password.", "error")
        return render_template("login.html", form=form)

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            new_password = request.form.get("new_password", "").strip()
            confirm = request.form.get("confirm_password", "").strip()
            if not new_password or len(new_password) < 6:
                flash("Password must be at least 6 characters.", "error")
            elif new_password != confirm:
                flash("Passwords do not match.", "error")
            else:
                current_user.set_password(new_password)
                current_user.must_change_password = False
                db.session.commit()
                flash("Password updated successfully.", "success")
                return redirect(url_for("pm.dashboard"))
        return render_template("pm/auth/change_password.html")

    # ── Routes ───────────────────────────────────────────────

    # ── Marketing & hub routes (top-level) ───────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/contact", methods=["POST"])
    def contact():
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        project_type = (data.get("project_type") or "").strip()
        message = (data.get("message") or "").strip()
        if not name or not email or not message:
            return jsonify({"error": "Please fill in all required fields."}), 400
        try:
            mail_server = app.config.get("MAIL_SERVER", "smtp.gmail.com")
            mail_port = int(app.config.get("MAIL_PORT", 587))
            mail_username = app.config.get("MAIL_USERNAME")
            mail_password = app.config.get("MAIL_PASSWORD")
            contact_email = app.config.get("CONTACT_EMAIL", "mbean@builtbybeans.com")
            msg = MIMEMultipart()
            msg["From"] = mail_username or "noreply@builtbybean.com"
            msg["To"] = contact_email
            msg["Subject"] = f"New Inquiry from {name} - {project_type or 'General'}"
            msg["Reply-To"] = email
            body = f"New contact form submission from builtbybean.com\n\nName: {name}\nEmail: {email}\nProject Type: {project_type or 'Not specified'}\n\nMessage:\n{message}\n"
            msg.attach(MIMEText(body, "plain"))
            if mail_username and mail_password:
                with smtplib.SMTP(mail_server, mail_port) as server:
                    server.starttls()
                    server.login(mail_username, mail_password)
                    server.send_message(msg)
            return jsonify({"success": True, "message": "Message sent! I'll get back to you soon."})
        except Exception as e:
            print(f"Email error: {e}")
            return jsonify({"error": "Something went wrong. Please email me directly at mbean@builtbybeans.com"}), 500

    @app.route("/admin")
    @login_required
    def admin_hub():
        return redirect(url_for("apps.index"), code=301)

    # ── Dashboard ────────────────────────────────────────────

    @pm_bp.route("/")
    @login_required
    def dashboard():
        today = date.today()

        # All-time financials, pulled live from Stripe rather than from local
        # invoice records, since billing happens directly in Stripe and there
        # are no local rows for any of it.
        #
        # "Invoiced" here means money that has been billed or committed and is
        # NOT yet paid. Three parts:
        #
        #   open      sent, sitting unpaid
        #   draft     written and dated but not sent. This is the load bearing
        #             one: a year of monthly work gets drafted up front, so
        #             excluding drafts as "not really invoiced" hides most of
        #             what is actually booked.
        #   scheduled what the recurring plans will bill before year end
        #
        # Paid deliberately does not appear in it. Collected money is Total
        # Revenue; adding it here would make one number mean two things.
        from stripe_service import (
            get_stripe_invoice_totals, get_scheduled_subscription_revenue,
        )
        stripe_totals = get_stripe_invoice_totals()
        stripe_by_customer = stripe_totals["paid_by_customer"]

        # Only clients count toward the forward figure. A Stripe subscriber
        # with no client record is somebody else's line of business.
        client_customer_ids = {
            row[0] for row in db.session.query(Client.stripe_customer_id).filter(
                Client.stripe_customer_id.isnot(None)
            ).all()
        }
        scheduled_subscriptions, scheduled_by_customer = get_scheduled_subscription_revenue(
            client_customer_ids
        )

        total_revenue = stripe_totals["paid"]
        total_awaiting = stripe_totals["open"]
        total_invoiced = (
            stripe_totals["open"] + stripe_totals["draft"] + scheduled_subscriptions
        )
        # Material expenses only — exclude any time-entry-linked (billable time) rows.
        total_expenses = db.session.query(db.func.sum(Expense.amount)).filter(
            Expense.time_entry_id.is_(None)
        ).scalar() or 0

        # Unbilled: the dollar value of logged time not yet on a draft/open/paid
        # invoice — money in the pipeline that still needs to be billed.
        invoiced_ids = db.session.query(InvoiceLineItem.time_entry_id).filter(
            InvoiceLineItem.time_entry_id.isnot(None),
            InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
        ).subquery()
        unbilled_entries = TimeEntry.query.filter(
            ~TimeEntry.id.in_(db.session.query(invoiced_ids))
        ).all()
        total_unbilled = sum(e.cost for e in unbilled_entries)
        unbilled_by_client = {}
        for e in unbilled_entries:
            if e.cost:
                unbilled_by_client[e.client_id] = unbilled_by_client.get(e.client_id, 0.0) + e.cost

        # Per-client financials
        clients = Client.query.order_by(Client.name).all()
        client_financials = []
        for c in clients:
            cust = c.stripe_customer_id
            c_revenue = stripe_by_customer.get(cust, 0.0) if cust else 0.0
            # The same two figures as the cards, split per client: everything
            # still to come, and the part of it that has actually been sent.
            c_awaiting = stripe_totals["open_by_customer"].get(cust, 0.0) if cust else 0.0
            c_invoiced = (
                c_awaiting
                + (stripe_totals["draft_by_customer"].get(cust, 0.0) if cust else 0.0)
                + (scheduled_by_customer.get(cust, 0.0) if cust else 0.0)
            )
            c_expenses = sum(e.amount for e in Expense.query.filter(
                Expense.client_id == c.id, Expense.time_entry_id.is_(None)
            ).all())
            client_financials.append({
                "id": c.id,
                "name": c.name,
                "stage": c.stage or "lead",
                "revenue": c_revenue,
                "invoiced": c_invoiced,
                "awaiting": c_awaiting,
                # Still calculated while Unbilled Revenue is hidden rather than
                # retired. The template's column and card are commented out.
                "unbilled": unbilled_by_client.get(c.id, 0.0),
                "expenses": c_expenses,
            })

        # Upcoming deadlines, from both places a date can live.
        #
        # This only ever read tickets, and no ticket has ever carried a due
        # date, so the panel was permanently empty while a project delivery
        # date sat right there in the record. A project's mvp_date is the
        # deadline that actually matters.
        #
        # "done" was never a ticket status either — the closed ones are
        # resolved and dismissed — so the filter excluded nothing.
        deadlines = []
        for tk in Ticket.query.filter(
            Ticket.due_date >= today,
            ~Ticket.status.in_(TICKET_CLOSED_STATUSES),
        ).order_by(Ticket.due_date.asc()).all():
            deadlines.append({
                "kind": "ticket", "when": tk.due_date, "title": tk.display_title,
                "where": tk.client.name + (f" · {tk.project.name}" if tk.project else ""),
                "url": url_for("pm.ticket_detail", id=tk.id),
            })
        for pr in Project.query.filter(
            Project.mvp_date >= today, Project.status == "active",
        ).order_by(Project.mvp_date.asc()).all():
            deadlines.append({
                "kind": "project", "when": pr.mvp_date, "title": pr.name + " — delivery",
                "where": pr.client.name,
                "url": url_for("pm.project_detail", id=pr.id),
            })
        deadlines.sort(key=lambda d: d["when"])
        deadlines = deadlines[:10]

        # ── What is owed on this, roughly ────────────────────
        #
        # Only the tax attributable to this business, not the household bill:
        # tax_engine works out the difference the profit makes on top of the
        # wages already entered on the Taxes page, which is the only honest
        # way to answer "what does this cost me" when profit stacks on a
        # salary and can straddle a bracket.
        pre_tax_profit = total_revenue - total_expenses
        settings = TaxSetting.get()
        tax = tax_compute(
            pre_tax_profit,
            filing_status=settings.filing_status,
            your_wages=settings.your_wages,
            spouse_wages=settings.spouse_wages,
            other_income=settings.other_income,
            federal_withheld=settings.federal_withheld,
            state_rate=settings.state_tax_rate,
            year=today.year,
        )
        estimated_tax = tax["business_tax"]
        post_tax_profit = pre_tax_profit - estimated_tax

        # ── Where the money went, by service ─────────────────
        #
        # Grouped from the cost entries rather than from expense categories,
        # because that is the only place a row knows which vendor it came
        # from. Anything with no service behind it is gathered at the bottom
        # so the table still adds up to Total Expenses.
        by_service = db.session.query(
            ServiceProvider.display_name,
            db.func.sum(ServiceCostEntry.allocated_amount),
        ).join(
            ServiceCostEntry, ServiceCostEntry.provider_id == ServiceProvider.id
        ).group_by(ServiceProvider.display_name).all()
        service_expenses = [
            {"name": name, "amount": float(amount or 0)}
            for name, amount in by_service if (amount or 0) > 0
        ]
        service_expenses.sort(key=lambda r: -r["amount"])
        tracked = sum(r["amount"] for r in service_expenses)
        remainder = total_expenses - tracked
        if round(remainder, 2) > 0:
            service_expenses.append({"name": "Everything else", "amount": remainder})

        return render_template("pm/dashboard/index.html",
            total_revenue=total_revenue,
            total_invoiced=total_invoiced,
            total_awaiting=total_awaiting,
            total_unbilled=total_unbilled,
            total_expenses=total_expenses,
            client_financials=client_financials,
            deadlines=deadlines,
            pre_tax_profit=pre_tax_profit,
            estimated_tax=estimated_tax,
            post_tax_profit=post_tax_profit,
            tax=tax,
            service_expenses=service_expenses,
        )

    # ── Clients ──────────────────────────────────────────────

    @pm_bp.route("/clients")
    @login_required
    def clients_list():
        page = request.args.get("page", 1, type=int)
        search = request.args.get("search", "")
        query = Client.query
        if search:
            query = query.filter(
                db.or_(Client.name.ilike(f"%{search}%"), Client.company.ilike(f"%{search}%"))
            )
        query = query.order_by(Client.name.asc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)
        return render_template("pm/clients/list.html", clients=pagination.items, pagination=pagination, search=search)

    def _apply_client_app_fields(client, form):
        """Wire a client's own app to this board.

        origin_slug is UNIQUE and nullable, so an empty one has to be stored as
        NULL rather than "". Two clients with no app of their own would both
        carry the empty string and the second save would fail on the unique
        constraint, which reads as a database error over a field the user left
        blank on purpose. Null does not collide with null.

        **The secret writes itself.** Naming a slug is the whole of the
        decision; generating a random string is not, and asking somebody to go
        and produce one before the feature works is how it stays unconfigured.
        So the first save with a slug and no secret mints one, and it is then
        shown on the form to be copied into that app once.

        It is only ever generated, never regenerated. Rotating is deliberate:
        clearing the field and saving mints a fresh one, and until the app is
        updated to match, its pushes come back 401 and sit in its outbox. Doing
        that silently on every save would break the link every time anybody
        edited a phone number.
        """
        slug = (form.origin_slug.data or "").strip()
        client.origin_slug = slug or None
        secret = (form.ingest_secret.data or "").strip()
        if slug and not secret:
            import secrets as _secrets
            secret = _secrets.token_urlsafe(32)
        client.ingest_secret = secret if slug else ""
        client.origin_base_url = (form.origin_base_url.data or "").strip().rstrip("/")

    @pm_bp.route("/clients/new", methods=["GET", "POST"])
    @login_required
    def client_create():
        form = ClientForm()
        if form.validate_on_submit():
            client = Client(
                name=form.name.data,
                email=form.email.data or "",
                phone=form.phone.data or "",
                company=form.company.data or "",
                address=form.address.data or "",
                notes=form.notes.data or "",
            )
            _apply_client_app_fields(client, form)
            db.session.add(client)
            db.session.commit()
            from stripe_service import create_stripe_customer
            result = create_stripe_customer(client)
            if result:
                db.session.commit()
            flash(f"Client '{client.name}' created.", "success")
            return redirect(url_for("pm.client_detail", id=client.id))
        return render_template("pm/clients/form.html", form=form, editing=False)

    @pm_bp.route("/clients/<int:id>")
    @login_required
    def client_detail(id):
        client = db.session.get(Client, id) or abort(404)
        projects = client.projects.order_by(Project.created_at.desc()).all()
        total_hours = client.total_hours
        total_revenue = client.total_revenue
        total_expenses = sum(p.total_expenses for p in projects)
        documents = client.documents.order_by(Document.uploaded_at.desc()).all()
        return render_template("pm/clients/detail.html",
            client=client, projects=projects, documents=documents,
            total_hours=total_hours, total_revenue=total_revenue, total_expenses=total_expenses)

    @pm_bp.route("/clients/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def client_edit(id):
        client = db.session.get(Client, id) or abort(404)
        form = ClientForm(obj=client)
        if form.validate_on_submit():
            form.populate_obj(client)
            # After populate_obj, which would otherwise write "" into a unique
            # column.
            _apply_client_app_fields(client, form)
            db.session.commit()
            from stripe_service import update_stripe_customer
            update_stripe_customer(client)
            flash(f"Client '{client.name}' updated.", "success")
            return redirect(url_for("pm.client_detail", id=client.id))
        return render_template("pm/clients/form.html", form=form, editing=True, client=client)

    @pm_bp.route("/clients/<int:id>/delete", methods=["POST"])
    @login_required
    def client_delete(id):
        client = db.session.get(Client, id) or abort(404)
        name = client.name
        db.session.delete(client)
        db.session.commit()
        flash(f"Client '{name}' deleted.", "success")
        return redirect(url_for("pm.clients_list"))

    # ── Projects ─────────────────────────────────────────────

    @pm_bp.route("/projects")
    @login_required
    def projects_list():
        page = request.args.get("page", 1, type=int)
        search = request.args.get("search", "")
        phase = request.args.get("phase", "")
        status = request.args.get("status", "")

        query = Project.query.join(Client)
        if search:
            query = query.filter(
                db.or_(Project.name.ilike(f"%{search}%"), Client.name.ilike(f"%{search}%"))
            )
        if phase:
            query = query.filter(Project.phase == phase)
        if status:
            query = query.filter(Project.status == status)

        query = query.order_by(Project.created_at.desc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)
        return render_template("pm/projects/list.html",
            projects=pagination.items, pagination=pagination,
            search=search, phase=phase, status=status)

    @pm_bp.route("/projects/new", methods=["GET", "POST"])
    @login_required
    def project_create():
        form = ProjectForm()
        form.client_id.choices = [(c.id, c.name) for c in Client.query.order_by(Client.name).all()]
        pre_client = request.args.get("client_id", type=int)
        if request.method == "GET" and pre_client:
            form.client_id.data = pre_client
        if form.validate_on_submit():
            project = Project(
                client_id=form.client_id.data,
                name=form.name.data,
                description=form.description.data or "",
                phase=form.phase.data,
                status=form.status.data,
                notes=form.notes.data or "",
            )
            db.session.add(project)
            db.session.commit()
            applied = _apply_default_playbooks(project)
            db.session.commit()
            note = f" {applied} playbook checklists are ready." if applied else ""
            flash(f"Project '{project.name}' created.{note}", "success")
            return redirect(url_for("pm.project_detail", id=project.id))
        return render_template("pm/projects/form.html", form=form, editing=False)

    def _apply_default_playbooks(project):
        """Attach every playbook marked default. Returns how many were added.

        Run on creation rather than offered as a choice, because GitHub and
        Railway are on every build and a question with one answer is not a
        question.
        """
        added = 0
        for pb in Playbook.query.filter_by(is_default=True, is_active=True).all():
            exists = ProjectPlaybook.query.filter_by(
                project_id=project.id, playbook_id=pb.id).first()
            if not exists:
                db.session.add(ProjectPlaybook(project_id=project.id, playbook_id=pb.id))
                added += 1
        return added

    @pm_bp.route("/projects/<int:id>")
    @login_required
    def project_detail(id):
        project = db.session.get(Project, id) or abort(404)
        tickets = project.tickets.order_by(Ticket.created_at.desc()).all()
        time_entries = project.time_entries.order_by(TimeEntry.date.desc()).all()
        expenses = Expense.query.filter(Expense.project_id == project.id).order_by(Expense.date.desc()).all()
        documents = project.documents.order_by(Document.uploaded_at.desc()).all()

        # The two that run on every build lead, then whatever was added for
        # this one. Ordering by sort_order alone buried GitHub and Railway
        # under an optional playbook somebody added last week.
        applied = ProjectPlaybook.query.filter_by(project_id=project.id).join(
            Playbook).order_by(Playbook.is_default.desc(), Playbook.sort_order).all()
        taken = {a.playbook_id for a in applied}
        available = [pb for pb in Playbook.query.filter_by(is_active=True)
                     .order_by(Playbook.sort_order).all() if pb.id not in taken]

        return render_template("pm/projects/detail.html",
            project=project, tickets=tickets, time_entries=time_entries, expenses=expenses,
            documents=documents, applied_playbooks=applied, available_playbooks=available)

    @pm_bp.route("/projects/<int:id>/playbooks/add", methods=["POST"])
    @login_required
    def project_playbook_add(id):
        project = db.session.get(Project, id) or abort(404)
        pb = db.session.get(Playbook, request.form.get("playbook_id", type=int) or 0)
        if not pb:
            flash("Pick a playbook to add.", "warning")
            return redirect(url_for("pm.project_detail", id=id))
        if ProjectPlaybook.query.filter_by(project_id=project.id, playbook_id=pb.id).first():
            flash(f"{pb.display_name} is already on this project.", "info")
        else:
            db.session.add(ProjectPlaybook(project_id=project.id, playbook_id=pb.id))
            db.session.commit()
            flash(f"{pb.display_name} added, {pb.steps.count()} steps to work through.", "success")
        return redirect(url_for("pm.project_detail", id=id))

    @pm_bp.route("/projects/playbooks/<int:applied_id>/remove", methods=["POST"])
    @login_required
    def project_playbook_remove(applied_id):
        applied = db.session.get(ProjectPlaybook, applied_id) or abort(404)
        pid, name = applied.project_id, applied.playbook.display_name
        db.session.delete(applied)
        db.session.commit()
        flash(f"{name} removed from this project, along with what was ticked.", "success")
        return redirect(url_for("pm.project_detail", id=pid))

    @pm_bp.route("/projects/playbooks/<int:applied_id>/step/<int:step_id>", methods=["POST"])
    @login_required
    def project_playbook_step(applied_id, step_id):
        """Tick or untick one step.

        The row is made on first touch rather than written out for every step
        when a playbook is applied, so editing a playbook's steps later changes
        what every project sees next instead of leaving old ones working from a
        frozen copy.
        """
        applied = db.session.get(ProjectPlaybook, applied_id) or abort(404)
        step = db.session.get(PlaybookStep, step_id) or abort(404)
        if step.playbook_id != applied.playbook_id:
            abort(404)

        row = ProjectPlaybookStep.query.filter_by(
            project_playbook_id=applied.id, playbook_step_id=step.id).first()
        if not row:
            row = ProjectPlaybookStep(project_playbook_id=applied.id, playbook_step_id=step.id)
            db.session.add(row)
        row.done = not row.done
        row.done_at = datetime.now(timezone.utc) if row.done else None
        db.session.commit()
        return redirect(url_for("pm.project_detail", id=applied.project_id) + "#playbooks")

    @pm_bp.route("/projects/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def project_edit(id):
        project = db.session.get(Project, id) or abort(404)
        form = ProjectForm(obj=project)
        form.client_id.choices = [(c.id, c.name) for c in Client.query.order_by(Client.name).all()]
        if form.validate_on_submit():
            form.populate_obj(project)
            db.session.commit()
            flash(f"Project '{project.name}' updated.", "success")
            return redirect(url_for("pm.project_detail", id=project.id))
        return render_template("pm/projects/form.html", form=form, editing=True, project=project)

    @pm_bp.route("/projects/<int:id>/delete", methods=["POST"])
    @login_required
    def project_delete(id):
        project = db.session.get(Project, id) or abort(404)
        name = project.name
        client_id = project.client_id
        db.session.delete(project)
        db.session.commit()
        flash(f"Project '{name}' deleted.", "success")
        return redirect(url_for("pm.client_detail", id=client_id))

    @pm_bp.route("/projects/<int:id>/phase", methods=["POST"])
    @login_required
    def project_phase_update(id):
        project = db.session.get(Project, id) or abort(404)
        new_phase = request.form.get("phase")
        valid_phases = [p[0] for p in PHASE_CHOICES]
        if new_phase in valid_phases:
            project.phase = new_phase
            db.session.commit()
            flash(f"Phase updated to '{dict(PHASE_CHOICES)[new_phase]}'.", "success")
        return redirect(url_for("pm.project_detail", id=project.id))

    def _ticket_choices(blank="No specific ticket"):
        """Every ticket, labelled by client, for the pickers on time and expenses.

        Joined to Client and NOT to Project. A ticket's project is nullable now,
        so an inner join to Project silently drops every ticket not filed under
        one, which is most of them once they start arriving from a client's app.
        The label carries the client for the same reason: the project used to be
        how you told two similar ones apart and is no longer always there.
        """
        rows = (Ticket.query.join(Client, Ticket.client_id == Client.id)
                .order_by(Client.name, Ticket.created_at.desc()).all())
        return [(0, blank)] + [
            (t.id, f"{t.display_title} ({t.client.name})") for t in rows
        ]

    # ── The hub: tickets arriving from a client's own app ────────
    #
    # Signed with that client's own secret, never authenticated by URL. See
    # hub.py for why, and for the copy of this protocol each client app holds.

    def _hub_client():
        """Which client is posting, and are they really them.

        Returns (client, None) or (None, response). The origin names who is
        claiming to post; the signature over the exact body proves it.
        """
        slug = (request.headers.get(hub.ORIGIN_HEADER) or "").strip()
        if not slug:
            return None, (jsonify({"error": "no origin"}), 400)
        client = Client.query.filter_by(origin_slug=slug).first()
        if client is None:
            # Deliberately the same shape of answer as a bad signature. Saying
            # "no such client" tells an unauthenticated caller which slugs
            # exist, which is the one thing they cannot otherwise find out.
            app.logger.warning("hub: no client for origin %r", slug)
            return None, (jsonify({"error": "unauthorised"}), 401)
        reason = hub.verify(client.ingest_secret, request.get_data(),
                            request.headers.get(hub.TIMESTAMP_HEADER),
                            request.headers.get(hub.SIGNATURE_HEADER))
        if reason:
            app.logger.warning("hub: refused %s: %s", slug, reason)
            return None, (jsonify({"error": "unauthorised"}), 401)
        return client, None

    @pm_bp.route("/api/hub/tickets", methods=["POST"])
    def hub_ingest_ticket():
        """One ticket from a client's app, created or brought up to date.

        Keyed on (origin, origin_ticket_id) with a unique index behind it, so
        the same ticket arriving twice updates rather than duplicating. Their
        outbox retries on any failure, which means a duplicate delivery is the
        normal case rather than the exceptional one.

        **What an update is allowed to touch is the whole design.** They own
        what was reported: the words, the screen it came from, who reported it,
        and how badly they need it. I own where the work has got to and what it
        costs, so `status`, `billing_bucket`, `billed_minutes` and both flags
        are never taken from the wire. Without that, triaging a ticket here and
        the reporter then editing it over there would quietly un-resolve work
        that is finished.

        `category` is taken on creation only, for the same reason: reclassifying
        a "bug" that is really a feature request is a triage call, and it must
        not be undone by their next save.
        """
        client, refusal = _hub_client()
        if refusal:
            return refusal
        data = request.get_json(silent=True) or {}
        their_id = data.get("ticket_id")
        if not isinstance(their_id, int):
            return jsonify({"error": "ticket_id must be an integer"}), 400

        ticket = Ticket.query.filter_by(origin=client.origin_slug,
                                        origin_ticket_id=their_id).first()
        created = ticket is None
        if created:
            ticket = Ticket(client_id=client.id, origin=client.origin_slug,
                            origin_ticket_id=their_id)
            ticket.category = data.get("category") if data.get("category") in TICKET_CATEGORIES else "bug"
            # Status is taken on CREATION only, for the same reason as category.
            # On an update I own it and theirs must not overwrite my triage. On
            # creation I have no opinion yet and theirs is the only truth there
            # is: without this, a client connected after years of history has
            # every resolved ticket land as New and their finished work fills
            # my open board. Found by backfilling J&D and reading the result.
            if data.get("status") in TICKET_STATUSES:
                ticket.status = data["status"]
            # They told me this status a moment ago, so they already know it.
            # Left null, the status drain would read it as a change of mine and
            # push it straight back, which is one half of a loop.
            ticket.hub_status_sent = ticket.status
            db.session.add(ticket)

        ticket.description = (data.get("description") or "")[:20000]
        ticket.title = (data.get("title") or "")[:300]
        ticket.source_label = (data.get("source_label") or "")[:200]
        ticket.source_path = (data.get("source_path") or "")[:500]
        ticket.origin_url = (data.get("url") or "")[:500]
        ticket.reporter_name = (data.get("reporter_name") or "")[:200]
        ticket.reporter_email = (data.get("reporter_email") or "")[:200]
        if data.get("priority") in TICKET_PRIORITIES:
            ticket.priority = data["priority"]
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        app.logger.info("hub: %s ticket %s/%s -> %s",
                        "created" if created else "updated",
                        client.origin_slug, their_id, ticket.id)
        return jsonify({"ok": True, "id": ticket.id, "created": created}), 201 if created else 200

    @pm_bp.route("/api/hub/status", methods=["POST"])
    def hub_ingest_status():
        """Their app changed where the work stands, and is telling me.

        Last change wins. These are two people acting minutes apart rather than
        two processes racing, so the newer statement of fact is the true one and
        there is nothing here worth a merge strategy.

        `hub_status_sent` is set to the same value in the same breath. That is
        the echo guard: the drain only pushes when the two disagree, so a status
        that arrived from them never reads as a change of mine and never goes
        straight back to them.
        """
        client, refusal = _hub_client()
        if refusal:
            return refusal
        data = request.get_json(silent=True) or {}
        their_id, status = data.get("ticket_id"), data.get("status")
        if not isinstance(their_id, int):
            return jsonify({"error": "ticket_id must be an integer"}), 400
        if status not in TICKET_STATUSES:
            return jsonify({"error": "unknown status"}), 400

        ticket = Ticket.query.filter_by(origin=client.origin_slug,
                                        origin_ticket_id=their_id).first()
        if ticket is None:
            return jsonify({"error": "no such ticket here yet"}), 404
        ticket.status = status
        ticket.hub_status_sent = status
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        app.logger.info("hub: %s/%s is now %s", client.origin_slug, their_id, status)
        return jsonify({"ok": True}), 200

    @pm_bp.route("/api/hub/notes", methods=["POST"])
    def hub_ingest_note():
        """Something the reporter said, onto the thread it belongs to.

        Deduplicated on (ticket_id, origin_note_id), which is a unique index,
        so a retried delivery is a no-op rather than the same sentence twice.

        A note from the reporter on a resolved ticket reopens it, exactly as it
        does inside their own app. Dismissed is left alone: that status is a
        decision, not an oversight.
        """
        client, refusal = _hub_client()
        if refusal:
            return refusal
        data = request.get_json(silent=True) or {}
        their_ticket = data.get("ticket_id")
        their_note = data.get("note_id")
        if not isinstance(their_ticket, int) or not isinstance(their_note, int):
            return jsonify({"error": "ticket_id and note_id must be integers"}), 400

        ticket = Ticket.query.filter_by(origin=client.origin_slug,
                                        origin_ticket_id=their_ticket).first()
        if ticket is None:
            # Their outbox will retry, by which time the ticket that this note
            # hangs off will have arrived. Saying "not yet" is the honest answer
            # and 404 is what makes them keep it queued.
            return jsonify({"error": "no such ticket here yet"}), 404

        existing = TicketNote.query.filter_by(ticket_id=ticket.id,
                                              origin_note_id=their_note).first()
        if existing is not None:
            return jsonify({"ok": True, "id": existing.id, "duplicate": True}), 200

        db.session.add(TicketNote(
            ticket_id=ticket.id,
            origin_note_id=their_note,
            author_name=(data.get("author_name") or "")[:200],
            body=(data.get("body") or "")[:5000],
            is_staff_reply=False,          # it came from them, by definition
        ))
        ticket.updated_at = datetime.now(timezone.utc)
        if ticket.status == "resolved":
            ticket.status = "in-progress"
        db.session.commit()
        return jsonify({"ok": True}), 201

    # ── Tickets ────────────────────────────────────────────────
    #
    # One board across every client. The shape is Talent Booker's, which is the
    # one that has been in daily use longest and has already made and fixed the
    # mistakes this one would otherwise make.

    def _ticket_board_order(query):
        """Bugs first, always. Then urgent. Then newest.

        Something broken outranks something wished for whatever priority either
        carries, so category is the FIRST key rather than priority. The
        consequence worth knowing: an urgent new feature sits below every bug,
        which is what "always" asks for.

        Each key only breaks ties in the one before it. Priority alone would
        shuffle a month of ordinary tickets into no order at all.
        """
        bugs_first = db.case({"bug": 0}, value=Ticket.category, else_=1)
        priority_rank = db.case(
            {name: i for i, name in enumerate(TICKET_PRIORITIES)},
            value=Ticket.priority, else_=len(TICKET_PRIORITIES),
        )
        return query.order_by(bugs_first, priority_rank, Ticket.created_at.desc())

    def _ticket_counts():
        """Header badges. Each counts EXACTLY what clicking it shows.

        Out of scope is excluded from "open" because the open board excludes it:
        it renders in its own section underneath. A badge that counts what the
        list below it does not show is the badge lying.
        """
        out = {name: 0 for name in TICKET_STATUSES}
        out["follow-up"] = out["out-of-scope"] = out["open"] = 0
        for t in Ticket.query.all():
            out[t.status] = out.get(t.status, 0) + 1
            if t.followup_flagged:
                out["follow-up"] += 1
            if t.out_of_scope:
                out["out-of-scope"] += 1
            elif t.status not in TICKET_CLOSED_STATUSES:
                out["open"] += 1
        out["total"] = sum(out[name] for name in TICKET_STATUSES)
        return out

    @pm_bp.route("/tickets")
    @login_required
    def tickets_list():
        status_filter = request.args.get("status", "open")
        category_filter = request.args.get("category", "all")
        client_filter = request.args.get("client_id", type=int)

        query = Ticket.query
        if status_filter == "open":
            query = query.filter(~Ticket.status.in_(TICKET_CLOSED_STATUSES))
        elif status_filter == "follow-up":
            # The flag, so this list can hold a finished ticket I still want to
            # talk about. That is the entire point of it.
            query = query.filter(Ticket.followup_flagged.is_(True))
        elif status_filter == "out-of-scope":
            query = query.filter(Ticket.out_of_scope.is_(True))
        elif status_filter in TICKET_STATUSES:
            query = query.filter(Ticket.status == status_filter)
        if status_filter in ("open", "all"):
            # They render in their own section below, so they must not also be
            # in the list above it. One ticket, one place on the page.
            query = query.filter(Ticket.out_of_scope.is_(False))
        if category_filter in TICKET_CATEGORIES:
            query = query.filter(Ticket.category == category_filter)
        if client_filter:
            query = query.filter(Ticket.client_id == client_filter)

        tickets = _ticket_board_order(query).all()

        # A separate query rather than sorted to the bottom of the main one:
        # they are not work in the queue, and anything that filters the board
        # must not interleave them back in.
        out_of_scope = []
        if status_filter in ("open", "all"):
            oos = Ticket.query.filter(Ticket.out_of_scope.is_(True))
            if category_filter in TICKET_CATEGORIES:
                oos = oos.filter(Ticket.category == category_filter)
            if client_filter:
                oos = oos.filter(Ticket.client_id == client_filter)
            out_of_scope = oos.order_by(Ticket.updated_at.desc()).all()

        return render_template(
            "pm/tickets/list.html",
            tickets=tickets, out_of_scope=out_of_scope, counts=_ticket_counts(),
            clients=Client.query.order_by(Client.name).all(),
            status_filter=status_filter, category_filter=category_filter,
            client_filter=client_filter,
            statuses=TICKET_STATUSES, status_labels=TICKET_STATUS_LABELS,
            categories=TICKET_CATEGORIES, category_labels=TICKET_CATEGORY_LABELS,
            priority_labels=TICKET_PRIORITY_LABELS,
            billing_labels=TICKET_BILLING_LABELS,
            billing_buckets=TICKET_BILLING_BUCKETS,
        )

    @pm_bp.route("/tickets/new", methods=["GET", "POST"])
    @login_required
    def ticket_create():
        form = TicketForm()
        form.client_id.choices = [
            (c.id, c.name) for c in Client.query.order_by(Client.name).all()
        ]
        form.project_id.choices = [(0, "No project")] + [
            (p.id, f"{p.name} ({p.client.name})")
            for p in Project.query.join(Client).order_by(Project.name).all()
        ]
        pre_project = request.args.get("project_id", type=int)
        if request.method == "GET" and pre_project:
            project = db.session.get(Project, pre_project)
            if project:
                form.project_id.data = pre_project
                form.client_id.data = project.client_id
        if form.validate_on_submit():
            ticket = Ticket(
                client_id=form.client_id.data,
                project_id=form.project_id.data or None,
                origin="local",          # raised here, not pushed in by an app
                reporter_name=current_user.full_name,
                title=(form.title.data or "").strip(),
                description=form.description.data or "",
                detailed_notes=form.detailed_notes.data or "",
                category=form.category.data,
                status=form.status.data,
                priority=form.priority.data,
                due_date=form.due_date.data,
            )
            db.session.add(ticket)
            db.session.commit()
            flash(f"Ticket '{ticket.display_title}' created.", "success")
            return redirect(url_for("pm.ticket_detail", id=ticket.id))
        return render_template("pm/tickets/form.html", form=form, editing=False)

    @pm_bp.route("/tickets/<int:id>")
    @login_required
    def ticket_detail(id):
        ticket = db.session.get(Ticket, id) or abort(404)
        # Stamped by the view that RENDERS the note, so the badge clears by the
        # thing being read rather than by a count being dismissed.
        stamped = 0
        for note in ticket.notes:
            if note.read_at is None and not note.is_staff_reply:
                note.read_at = datetime.now(timezone.utc)
                stamped += 1
        if stamped:
            db.session.commit()
        return render_template(
            "pm/tickets/detail.html", ticket=ticket,
            documents=ticket.documents.order_by(Document.uploaded_at.desc()).all(),
            expenses=ticket.expenses.order_by(Expense.date.desc()).all(),
            time_entries=ticket.time_entries.order_by(TimeEntry.date.desc()).all(),
            status_labels=TICKET_STATUS_LABELS, statuses=TICKET_STATUSES,
            categories=TICKET_CATEGORIES, category_labels=TICKET_CATEGORY_LABELS,
            priorities=TICKET_PRIORITIES, priority_labels=TICKET_PRIORITY_LABELS,
            billing_buckets=TICKET_BILLING_BUCKETS, billing_labels=TICKET_BILLING_LABELS,
        )

    @pm_bp.route("/tickets/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def ticket_edit(id):
        ticket = db.session.get(Ticket, id) or abort(404)
        form = TicketForm(obj=ticket)
        form.client_id.choices = [
            (c.id, c.name) for c in Client.query.order_by(Client.name).all()
        ]
        form.project_id.choices = [(0, "No project")] + [
            (p.id, f"{p.name} ({p.client.name})")
            for p in Project.query.join(Client).order_by(Project.name).all()
        ]
        if request.method == "GET" and not ticket.project_id:
            form.project_id.data = 0
        if form.validate_on_submit():
            form.populate_obj(ticket)
            ticket.project_id = form.project_id.data or None
            db.session.commit()
            flash(f"Ticket '{ticket.display_title}' updated.", "success")
            return redirect(url_for("pm.ticket_detail", id=ticket.id))
        return render_template("pm/tickets/form.html", form=form, editing=True, ticket=ticket)

    @pm_bp.route("/tickets/<int:id>/delete", methods=["POST"])
    @login_required
    def ticket_delete(id):
        ticket = db.session.get(Ticket, id) or abort(404)
        title = ticket.display_title
        db.session.delete(ticket)          # notes cascade
        db.session.commit()
        flash(f"Ticket '{title}' deleted.", "success")
        return redirect(url_for("pm.tickets_list"))

    @pm_bp.route("/tickets/<int:id>/triage", methods=["POST"])
    @login_required
    def ticket_triage(id):
        """Status, category, priority and billing from one row of controls.

        Each is applied only if it was actually submitted, so a form carrying
        one of them cannot blank the other three.
        """
        ticket = db.session.get(Ticket, id) or abort(404)
        if "status" in request.form and request.form["status"] in TICKET_STATUSES:
            ticket.status = request.form["status"]
        if "category" in request.form and request.form["category"] in TICKET_CATEGORIES:
            ticket.category = request.form["category"]
        if "priority" in request.form and request.form["priority"] in TICKET_PRIORITIES:
            ticket.priority = request.form["priority"]
        if "billing_bucket" in request.form:
            bucket = request.form["billing_bucket"]
            # Anything unrecognised clears it back to undecided rather than
            # guessing, because a guess here is presented to the client as free.
            ticket.billing_bucket = bucket if bucket in TICKET_BILLING_BUCKETS else ""
        if "billed_minutes" in request.form:
            ticket.billed_minutes = max(0, request.form.get("billed_minutes", type=int) or 0)
        db.session.commit()
        return redirect(request.referrer or url_for("pm.tickets_list"))

    @pm_bp.route("/tickets/<int:id>/flag", methods=["POST"])
    @login_required
    def ticket_flag(id):
        """Come back to this one. A flag alongside any status, including done."""
        ticket = db.session.get(Ticket, id) or abort(404)
        ticket.followup_flagged = not ticket.followup_flagged
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return redirect(request.referrer or url_for("pm.tickets_list"))

    @pm_bp.route("/tickets/<int:id>/scope", methods=["POST"])
    @login_required
    def ticket_scope(id):
        """Rule it outside what their app is for. Touches nothing else.

        Deliberately does not set status, exactly like the follow-up flag and
        for the same reason: status is what the reporter is shown, and this is
        my own note about what I am not going to build. The ticket keeps
        whatever status it had and nothing changes on their side.
        """
        ticket = db.session.get(Ticket, id) or abort(404)
        ticket.out_of_scope = not ticket.out_of_scope
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Filed as out of scope. Nothing changed on their side."
              if ticket.out_of_scope else "Back on the board.", "success")
        return redirect(request.referrer or url_for("pm.tickets_list"))

    @pm_bp.route("/tickets/<int:id>/reply", methods=["POST"])
    @login_required
    def ticket_reply(id):
        """Answer from here, on the board, rather than in three separate apps.

        The note is recorded in the shared thread FIRST and independently of
        whether it can be delivered. Talent Booker shipped this as email only,
        so the reporter had no way to see a reply in the app and nothing to
        reply TO: the conversation existed solely in an inbox, and a reply to
        somebody with no address on file vanished entirely.

        `delivered_at` stays null, which is what marks it as still owed to the
        client's app. Nothing drains that yet, so the reply lives here and is
        visible as undelivered rather than being quietly dropped.
        """
        ticket = db.session.get(Ticket, id) or abort(404)
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Write something first.", "error")
            return redirect(request.referrer or url_for("pm.ticket_detail", id=id))
        db.session.add(TicketNote(
            ticket_id=ticket.id,
            author_name=current_user.full_name,
            body=body[:5000],
            is_staff_reply=True,
        ))
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        # Name every destination. Saying only "sent" is how Talent Booker's own
        # thread came to look like a feature that did not exist.
        if ticket.origin == "local" or not ticket.client.origin_base_url:
            flash("Posted to the thread. Their app is not wired up to receive it yet.",
                  "success")
        else:
            flash("Posted to the thread, and queued to go back to their app.", "success")
        return redirect(url_for("pm.ticket_detail", id=ticket.id))

    # ── Sending my replies back to the client's app ───────────────
    #
    # `TicketNote.delivered_at` IS the outbox. A staff reply with a null
    # delivered_at is one they have not been told about, so there is no second
    # table to keep in step with the first, and nothing can be marked sent
    # without the thing itself being sent.

    def deliver_pending_statuses(limit=100):
        """Push every status I have changed and not yet told them about.

        Driven by the two columns disagreeing rather than by a queue table: the
        ticket itself is the record of what they were last told, so there is no
        second list to keep in step with the first and nothing can be marked
        sent without the sending having happened.

        Returns (sent, skipped, failed). Never raises.
        """
        sent = skipped = failed = 0
        stale = (Ticket.query
                 .filter(Ticket.origin != "local",
                         db.or_(Ticket.hub_status_sent.is_(None),
                                Ticket.hub_status_sent != Ticket.status))
                 .limit(limit).all())
        for ticket in stale:
            client = ticket.client
            if (client is None or not client.origin_base_url
                    or not client.ingest_secret or not ticket.origin_ticket_id):
                skipped += 1
                continue
            try:
                hub.post(client.origin_base_url, "/api/hub/status",
                         {"ticket_id": ticket.origin_ticket_id, "status": ticket.status},
                         secret=client.ingest_secret, origin_slug=client.origin_slug)
            except hub.DeliveryError as exc:
                # Left disagreeing on purpose, so the next pass tries again.
                failed += 1
                app.logger.warning("hub: status for %s failed: %s", ticket.id, exc)
                continue
            # Stamped only after they took it. The other order is how a ticket
            # comes to read as synced when nothing left the building.
            ticket.hub_status_sent = ticket.status
            db.session.commit()
            sent += 1
        return sent, skipped, failed

    app.deliver_pending_statuses = deliver_pending_statuses

    def deliver_pending_replies(limit=50):
        """Push every reply that is still owed to a client's app.

        Returns (sent, skipped, failed). Never raises: this runs on a timer and
        on a CLI, and a thrown exception on either would stop the queue rather
        than the one message.

        A note whose client has no origin_base_url is SKIPPED, not failed and
        not retried forever. There is nowhere to send it, which is a
        configuration fact rather than an outage, and the thread already says
        so in as many words on the ticket.
        """
        sent = skipped = failed = 0
        pending = (TicketNote.query
                   .filter(TicketNote.is_staff_reply.is_(True),
                           TicketNote.delivered_at.is_(None))
                   .order_by(TicketNote.created_at)
                   .limit(limit).all())
        for note in pending:
            ticket = note.ticket
            client = ticket.client if ticket else None
            if (ticket is None or client is None or ticket.origin == "local"
                    or not client.origin_base_url or not client.ingest_secret
                    or not ticket.origin_ticket_id):
                skipped += 1
                continue
            try:
                hub.post(
                    client.origin_base_url, "/api/hub/reply",
                    {
                        "ticket_id": ticket.origin_ticket_id,
                        "note_id": note.id,          # MY id, their dedupe key
                        "body": note.body or "",
                        "author_name": note.author_name or "",
                        "status": ticket.status,
                    },
                    secret=client.ingest_secret,
                    origin_slug=client.origin_slug,
                )
            except hub.DeliveryError as exc:
                # Left pending on purpose. The next pass tries again, and the
                # ticket goes on saying it has not been sent, which is true.
                failed += 1
                app.logger.warning("hub: reply %s to %s failed: %s",
                                   note.id, client.origin_slug, exc)
                continue
            # Stamped only after the far end took it. Stamping first and
            # sending after is how a reply comes to read as delivered when
            # nothing left the building.
            note.delivered_at = datetime.now(timezone.utc)
            db.session.commit()
            sent += 1
        return sent, skipped, failed

    app.deliver_pending_replies = deliver_pending_replies

    @app.cli.command("push-replies")
    def push_replies_cmd():
        """Drain the reply queue by hand."""
        sent, skipped, failed = deliver_pending_replies()
        print(f"sent {sent}, skipped {skipped}, failed {failed}")

    def _start_reply_sender():
        """Drain the queue on a timer, in the background.

        Guarded on a flag so it starts once per process. Under gunicorn each
        worker gets its own, which is fine: a note is claimed by its own commit
        and the far end deduplicates on note_id anyway, so the worst two
        workers can do is send the same reply twice to an endpoint that ignores
        the second.
        """
        import threading

        interval = int(os.environ.get("HUB_PUSH_INTERVAL_SECONDS", "60"))
        if interval <= 0 or os.environ.get("HUB_PUSH_DISABLED") == "1":
            return

        def loop():
            while True:
                time.sleep(interval)
                try:
                    with app.app_context():
                        deliver_pending_replies()
                        deliver_pending_statuses()
                except Exception as exc:            # noqa: BLE001
                    # A dead thread is a queue that silently stops draining, so
                    # nothing is allowed out of this loop.
                    app.logger.warning("hub: reply sender pass failed: %s", exc)

        threading.Thread(target=loop, daemon=True, name="hub-reply-sender").start()

    _start_reply_sender()


    # ── Documents ────────────────────────────────────────────

    @pm_bp.route("/tickets/<int:id>/documents/upload", methods=["POST"])
    @login_required
    def ticket_upload_document(id):
        ticket = db.session.get(Ticket, id) or abort(404)
        files = request.files.getlist("documents")
        count = 0
        for f in files:
            stored_name, original_name, size = save_upload(f, "documents")
            if stored_name:
                doc = Document(
                    ticket_id=ticket.id,
                    filename=stored_name,
                    original_name=original_name,
                    file_size=size,
                )
                db.session.add(doc)
                count += 1
        db.session.commit()
        if count:
            flash(f"{count} document(s) uploaded.", "success")
        else:
            flash("No valid files to upload.", "warning")
        return redirect(url_for("pm.ticket_detail", id=ticket.id))

    @pm_bp.route("/documents/<int:id>/download")
    @login_required
    def document_download(id):
        doc = db.session.get(Document, id) or abort(404)
        return download_upload(doc.filename, doc.original_name, "documents")

    @pm_bp.route("/projects/<int:id>/documents/upload", methods=["POST"])
    @login_required
    def project_upload_document(id):
        project = db.session.get(Project, id) or abort(404)
        files = request.files.getlist("documents")
        count = 0
        for f in files:
            stored_name, original_name, size = save_upload(f, "documents")
            if stored_name:
                doc = Document(
                    project_id=project.id,
                    filename=stored_name,
                    original_name=original_name,
                    file_size=size,
                )
                db.session.add(doc)
                count += 1
        db.session.commit()
        if count:
            flash(f"{count} document(s) uploaded.", "success")
        else:
            flash("No valid files to upload.", "warning")
        return redirect(url_for("pm.project_detail", id=project.id))

    @pm_bp.route("/clients/<int:id>/documents/upload", methods=["POST"])
    @login_required
    def client_upload_document(id):
        client = db.session.get(Client, id) or abort(404)
        files = request.files.getlist("documents")
        count = 0
        for f in files:
            stored_name, original_name, size = save_upload(f, "documents")
            if stored_name:
                doc = Document(
                    client_id=client.id,
                    filename=stored_name,
                    original_name=original_name,
                    file_size=size,
                )
                db.session.add(doc)
                count += 1
        db.session.commit()
        if count:
            flash(f"{count} document(s) uploaded.", "success")
        else:
            flash("No valid files to upload.", "warning")
        return redirect(url_for("pm.client_detail", id=client.id))

    @pm_bp.route("/documents/<int:id>/delete", methods=["POST"])
    @login_required
    def document_delete(id):
        doc = db.session.get(Document, id) or abort(404)
        ticket_id = doc.ticket_id
        project_id = doc.project_id
        client_id = doc.client_id
        delete_upload(doc.filename, "documents")
        db.session.delete(doc)
        db.session.commit()
        flash("Document deleted.", "success")
        if ticket_id:
            return redirect(url_for("pm.ticket_detail", id=ticket_id))
        elif project_id:
            return redirect(url_for("pm.project_detail", id=project_id))
        elif client_id:
            return redirect(url_for("pm.client_detail", id=client_id))
        return redirect(url_for("pm.dashboard"))

    # ── Contract Templates ──────────────────────────────────
    #
    # These live under /contracts because that is the only place they are
    # reached from: a letter or an SOW is a contract at the start of its life,
    # and having them as their own destinations meant three sidebar entries
    # for one job. The old /documents paths redirect rather than 404, since
    # they have been bookmarked and linked to.

    @pm_bp.route("/documents/engagement-letter")
    def engagement_letter_moved():
        return redirect(url_for("pm.engagement_letter_form"), code=301)

    @pm_bp.route("/documents/sow")
    def sow_moved():
        return redirect(url_for("pm.sow_form"), code=301)

    def _client_picker():
        """Everyone a contract can be written for, and the email on file.

        Returned as both a list for the dropdown and a lookup keyed by id, so
        the form can fill the signer in the moment a client is chosen rather
        than asking for an address the board already knows.
        """
        clients = Client.query.order_by(Client.name).all()
        options = [(c.id, c.name) for c in clients]
        lookup = {
            str(c.id): {"name": c.name, "email": (c.email or "").strip()}
            for c in clients
        }
        return options, lookup

    @pm_bp.route("/contracts/new/engagement-letter", methods=["GET"])
    @login_required
    def engagement_letter_form():
        options, lookup = _client_picker()
        return render_template("pm/contracts/engagement_letter_form.html",
                               today=date.today().isoformat(),
                               client_options=options, client_lookup=lookup)

    @pm_bp.route("/contracts/new/engagement-letter", methods=["POST"])
    @login_required
    def generate_engagement_letter():
        from io import BytesIO
        from fpdf import FPDF

        client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
        raw_date = request.form.get("date", "")
        project_description = request.form.get("project_description", "").strip()
        mvp_price = "2,500"

        if not client or not project_description:
            flash("Choose a client and describe the project.", "warning")
            return redirect(url_for("pm.engagement_letter_form"))
        client_name = client.name

        try:
            formatted_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%B %d, %Y")
        except (ValueError, TypeError):
            formatted_date = raw_date

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=25)
        pdf.set_margins(30, 25, 30)

        NAVY = (26, 26, 46)
        GOLD = (184, 134, 11)
        GRAY = (100, 100, 100)
        BLACK = (0, 0, 0)

        def add_header():
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*NAVY)
            pdf.cell(0, 5, "B U I L T   B Y   B E A N   L L C", new_x="LMARGIN")
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*GOLD)
            pdf.cell(0, 5, "  Web Development & Digital Solutions", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(30, pdf.get_y() + 1, 180, pdf.get_y() + 1)
            pdf.ln(6)

        def add_footer():
            pdf.set_y(-20)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(160, 160, 160)
            pdf.cell(0, 5, f"Confidential - Built by Bean LLC    Page {pdf.page_no()}", align="C")

        def section_heading(text):
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*NAVY)
            pdf.cell(0, 7, text.upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(30, pdf.get_y(), 180, pdf.get_y())
            pdf.ln(5)

        def body_text(text):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*GRAY)
            pdf.multi_cell(0, 5.5, text)
            pdf.ln(3)

        def add_table(rows):
            pdf.set_font("Helvetica", "", 9)
            col_w = [55, 95]
            for label, value in rows:
                y_start = pdf.get_y()
                pdf.set_text_color(*BLACK)
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(col_w[0], 12, label, border="B")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(*GRAY)
                pdf.cell(col_w[1], 12, value, border="B", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)

        # --- Page 1 ---
        pdf.add_page()
        add_header()

        # Title
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 12, "Client Engagement Letter", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 7, "Service Agreement & Pricing Terms", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)

        # Prepared for
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(25, 6, "Prepared for: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(60, 6, client_name)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(12, 6, "Date: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, formatted_date, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

        body_text(f"Thank you for the opportunity to work with {client_name}. This letter outlines the scope, pricing structure, and terms of our engagement. Please review, sign, and return prior to the start of any work.")

        # Section 1
        section_heading("1. Project Overview")
        body_text(f"Built by Bean LLC will {project_description}. The engagement begins with an MVP - the agreed-upon, fully functional launch version of the site or application. All subsequent work is contracted separately and governed by the terms in Sections 3 and 4 of this letter.")

        # Section 2
        section_heading("2. MVP Development - Flat Project Fee")
        body_text("The MVP (Minimum Viable Product) is scoped and priced as a flat project fee determined during a discovery session before any work begins. The final fee reflects the agreed scope only - work or features outside that scope are billed separately under Sections 3 and 4.")
        add_table([
            ("Minimum Starting Price", f"${mvp_price} - final fee determined by project scope"),
            ("Payment Structure", "50% due at project kickoff; 50% due upon delivery and acceptance"),
            ("Price Lock", "Flat fee is agreed upon and locked in writing before work begins"),
            ("Scope Changes", "Any changes to agreed scope require a written amendment"),
        ])
        body_text("The MVP fee covers only the agreed initial scope. Features, additions, or changes beyond that scope are subject to separate fees as outlined below.")

        # Section 3
        section_heading("3. Maintenance & Support")
        body_text("Once the MVP is delivered and accepted, Built by Bean LLC has no obligation to perform further work unless separately contracted. Ongoing maintenance - including bug fixes, performance updates, security patches, and general upkeep of existing functionality - is available at the following rate:")
        add_table([
            ("Maintenance Hourly Rate", "$100/hour"),
            ("Scope", "Bug fixes, updates, and support for existing functionality only"),
            ("Billing Increment", "Work is billed in one-hour minimum increments"),
            ("Invoicing", "Net 30 days from invoice date"),
        ])
        body_text("Maintenance covers what has already been built. Requests for new functionality are treated as new feature development and billed at the rate in Section 4.")

        # Section 4
        section_heading("4. New Feature Development")
        body_text("Any feature, functionality, or integration not included in the original agreed MVP scope is considered new feature development. This work requires additional scoping, design, development, testing, and deployment and is billed at a higher rate to reflect that investment.")
        add_table([
            ("New Feature Hourly Rate", "$200/hour"),
            ("Billing Increment", "Work is billed in one-hour minimum increments"),
            ("Authorization", "All feature work requires written approval before work begins"),
            ("Invoicing", "Net 30 days from invoice date"),
        ])

        # Section 5
        section_heading("5. General Terms")
        terms = [
            "All project scopes, timelines, and fees are confirmed in a signed Statement of Work (SOW) before work begins.",
            "Client is responsible for timely feedback, content, and approvals. Client-caused delays may affect project timelines.",
            "Built by Bean LLC has no obligation to perform any work beyond a delivered and accepted MVP unless separately contracted in writing.",
            "Built by Bean LLC reserves the right to display completed work in its portfolio unless the client requests otherwise in writing.",
            "This engagement letter does not constitute a binding contract for services. A formal SOW governs each individual project or work request.",
            "All fees are in USD. Late payments are subject to a 1.5% monthly late fee after the invoice due date.",
        ]
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRAY)
        for term in terms:
            pdf.cell(6, 5.5, "-")
            pdf.multi_cell(0, 5.5, f" {term}")
            pdf.ln(2)
        pdf.ln(4)

        body_text("Please sign and return this letter to confirm your agreement to these terms.")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(0, 6, "Phone: 903-491-2095", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "Email: mbean@builtbybeans.com", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

        # Client Acknowledgment
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.5)
        pdf.line(30, pdf.get_y(), 180, pdf.get_y())
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 7, "CLIENT ACKNOWLEDGMENT", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        body_text(f"By signing below, {client_name} acknowledges receipt of this engagement letter and agrees to the terms outlined herein.")
        pdf.ln(4)

        # Note where each line lands as it is drawn, so the signing portal can
        # put a field on it. Recorded here rather than searched for in the
        # finished PDF: this code knows exactly where it put them, and a
        # heuristic looking for something signature-shaped would not.
        sign_anchors = []
        for label in ["Signature", "Printed Name", "Title", "Date"]:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*BLACK)
            sign_anchors.append({"label": label, "page": pdf.page_no(), "y": pdf.get_y(),
                                 "x": SIGN_FIELD_X, "w": SIGN_FIELD_W, "h": SIGN_FIELD_H})
            pdf.cell(30, 8, f"{label}:")
            pdf.cell(100, 8, "_" * 50, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

        # Add footers. Auto page break comes off first: the footer sits 20mm
        # from the bottom, which is already past the 25mm break margin, so
        # writing it triggers a new page and every letter ends on a blank
        # sheet. Nothing is drawn after this, so it is not turned back on.
        pdf.set_auto_page_break(auto=False)
        for page_num in range(1, pdf.pages_count + 1):
            pdf.page = page_num
            add_footer()

        pdf_bytes = pdf.output()
        safe_name = client_name.replace(" ", "_").replace("&", "and")
        filename = f"{safe_name}_Engagement_Letter.pdf"

        # Auto-save PDF to client. The client came from the picker, so it is
        # always there; this used to re-find it by ilike on a typed name and
        # filed nothing at all when the spelling drifted.
        doc = None
        if client:
            stored_name = f"{uuid.uuid4().hex}.pdf"
            pdf_data = bytes(pdf_bytes)
            if _s3_client:
                s3_key = f"documents/{stored_name}"
                _s3_client.put_object(
                    Bucket=_s3_bucket, Key=s3_key, Body=pdf_data,
                    ContentType="application/pdf",
                )
            else:
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "documents")
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, stored_name), "wb") as f:
                    f.write(pdf_data)
            doc = Document(
                client_id=client.id, filename=stored_name,
                original_name=filename, file_size=len(pdf_data),
            )
            db.session.add(doc)
            db.session.commit()

        # Straight out for signature, if that was asked for. The fields go on
        # the lines just drawn, so the client signs where the letter says to
        # sign rather than wherever a guess put a box.
        sent = send_generated(
            bytes(pdf_bytes), filename=filename,
            title=f"Engagement Letter - {client_name}",
            kind="engagement_letter",
            fields=signadoc_service.fields_for(sign_anchors, pdf.w, pdf.h),
            client=client, document=doc,
        )
        if sent:
            return redirect(url_for("contracts.contract_detail", id=sent.id))

        from flask import make_response as _make_response
        response = _make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @pm_bp.route("/contracts/new/statement-of-work", methods=["GET"])
    @login_required
    def sow_form():
        options, lookup = _client_picker()
        return render_template("pm/contracts/sow_form.html",
                               today=date.today().isoformat(),
                               client_options=options, client_lookup=lookup)

    @pm_bp.route("/contracts/new/statement-of-work", methods=["POST"])
    @login_required
    def generate_sow():
        from io import BytesIO
        from fpdf import FPDF

        client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
        client_name = client.name if client else ""
        project_name = request.form.get("project_name", "").strip()
        project_description = request.form.get("project_description", "").strip()
        mvp_price = request.form.get("mvp_price", "2,500").strip()
        raw_sow_date = request.form.get("sow_date", "")
        raw_delivery_date = request.form.get("delivery_date", "")
        maintenance_days = request.form.get("maintenance_days", "30").strip()
        hosting_fee = request.form.get("hosting_fee", "25").strip()
        hosting_cycle = request.form.get("hosting_cycle", "monthly").strip()
        payment_pcts = request.form.getlist("payment_pct")
        payment_labels = request.form.getlist("payment_label")
        payment_milestones = []
        for pct, label in zip(payment_pcts, payment_labels):
            pct = pct.strip()
            label = label.strip()
            if pct and label:
                payment_milestones.append((pct, label))
        if payment_milestones:
            payment_description = "; ".join(f"{p}% due {l}" for p, l in payment_milestones)
        else:
            payment_description = "50% due at project kickoff; 50% due upon delivery and acceptance"
        features = [f.strip() for f in request.form.getlist("features") if f.strip()]

        if not client or not project_name or not project_description or not features:
            flash("Choose a client, and give a project name, description and at least one feature.", "warning")
            return redirect(url_for("pm.sow_form"))

        try:
            sow_date = datetime.strptime(raw_sow_date, "%Y-%m-%d").strftime("%B %d, %Y")
        except (ValueError, TypeError):
            sow_date = raw_sow_date
        try:
            delivery_date = datetime.strptime(raw_delivery_date, "%Y-%m-%d").strftime("%B %d, %Y")
        except (ValueError, TypeError):
            delivery_date = raw_delivery_date

        maint_days = int(maintenance_days) if maintenance_days.isdigit() else 30

        # --- Build PDF ---
        try:
            return _build_sow_pdf(client, project_name, project_description,
                                  mvp_price, sow_date, delivery_date, maint_days, features,
                                  payment_description, payment_milestones,
                                  hosting_fee, hosting_cycle)
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash(f"PDF generation error: {e}", "error")
            return redirect(url_for("pm.sow_form"))

    def _build_sow_pdf(client, project_name, project_description,
                        mvp_price, sow_date, delivery_date, maint_days, features,
                        payment_description, payment_milestones,
                        hosting_fee, hosting_cycle):
        # The chosen client, passed in rather than looked up again by name.
        client_name = client.name
        from fpdf import FPDF

        def sanitize(text):
            return text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2026", "...")

        client_name = sanitize(client_name)
        project_name = sanitize(project_name)
        project_description = sanitize(project_description)
        payment_description = sanitize(payment_description)
        features = [sanitize(f) for f in features]
        payment_milestones = [(p, sanitize(l)) for p, l in payment_milestones]

        NAVY = (26, 26, 46)
        GOLD = (184, 134, 11)
        GRAY = (100, 100, 100)
        BLACK = (0, 0, 0)

        class SOWPDF(FPDF):
            def header(self):
                if self.page_no() == 1:
                    return
                self.set_font("Helvetica", "B", 7)
                self.set_text_color(*NAVY)
                self.cell(75, 4, "B U I L T   B Y   B E A N   L L C")
                self.set_font("Helvetica", "I", 7)
                self.set_text_color(*GOLD)
                self.cell(0, 4, "Statement of Work", align="R", new_x="LMARGIN", new_y="NEXT")
                self.set_draw_color(*GOLD)
                self.set_line_width(0.3)
                self.line(30, self.get_y() + 1, 180, self.get_y() + 1)
                self.ln(4)

            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "", 7)
                self.set_text_color(160, 160, 160)
                self.cell(0, 5, f"Confidential - Built by Bean LLC    Page {self.page_no()}", align="C")

        pdf = SOWPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.set_margins(30, 25, 30)

        import os
        font_path = os.path.join(os.path.dirname(__file__), "static", "fonts", "DancingScript.ttf")
        if os.path.exists(font_path):
            pdf.add_font("DancingScript", "", font_path)

        def section_heading(text):
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            pdf.ln(6)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*NAVY)
            pdf.cell(0, 7, text.upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(30, pdf.get_y(), 180, pdf.get_y())
            pdf.ln(5)

        def body_text(text):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*GRAY)
            pdf.multi_cell(0, 5.5, text)
            pdf.ln(3)

        def add_table(rows):
            pdf.set_font("Helvetica", "", 9)
            col_w = [55, 95]
            for label, value in rows:
                pdf.set_text_color(*BLACK)
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(col_w[0], 12, label, border="B")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(*GRAY)
                pdf.cell(col_w[1], 12, value, border="B", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)

        def bullet_list(items):
            for item in items:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(*GRAY)
                pdf.multi_cell(0, 5.5, f"  -  {item}")
                pdf.ln(1.5)
            pdf.ln(2)

        # --- Page 1 ---
        pdf.add_page()

        # Header (only on first page)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*NAVY)
        pdf.cell(75, 5, "B U I L T   B Y   B E A N   L L C")
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*GOLD)
        pdf.cell(0, 5, "Statement of Work", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.5)
        pdf.line(30, pdf.get_y() + 1, 180, pdf.get_y() + 1)
        pdf.ln(8)

        # Title
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 12, "Statement of Work", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 7, f"{project_name} - {client_name}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)

        # Project info block
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(25, 6, "Client: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(60, 6, client_name)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(12, 6, "Date: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, sow_date, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(25, 6, "Project: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, project_name, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

        # Section 1 - Project Summary
        section_heading("1. Project Summary")
        body_text(project_description)

        # Section 2 - MVP Scope
        section_heading("2. MVP Scope & Deliverables")
        body_text("The following features constitute the complete MVP scope. Only the items listed below are included in the flat project fee. Any work, features, or functionality not explicitly listed is considered out of scope and will be billed separately under Sections 5 and 6.")
        bullet_list(features)
        body_text("This list represents the full and final MVP scope. Changes or additions require a written amendment to this SOW before work proceeds.")

        # Section 3 - Pricing & Payment (custom payment structure)
        section_heading("3. MVP Pricing & Payment")
        add_table([
            ("MVP Flat Fee", f"${mvp_price}"),
            ("Estimated Delivery", delivery_date),
            ("Price Lock", "Flat fee is locked upon signing - no surprises"),
        ])
        if payment_milestones:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*NAVY)
            pdf.cell(0, 7, "Payment Schedule:", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
            for pct, label in payment_milestones:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(*GRAY)
                pdf.multi_cell(0, 5.5, f"  -  {pct}% due {label}")
                pdf.ln(1.5)
            pdf.ln(2)
        else:
            add_table([("Payment Structure", payment_description)])
        body_text("The MVP fee covers only the scope defined in Section 2. Work outside that scope is billed at the rates in Sections 5 and 6.")

        # Section 4 - Free Maintenance Window
        section_heading("4. Post-MVP Free Maintenance Window")
        body_text(f"Upon delivery and client acceptance of the MVP, Built by Bean LLC will provide a {maint_days}-day complimentary maintenance window. During this period, the following is covered at no additional charge:")
        bullet_list([
            "Bug fixes for delivered functionality that is not working as agreed",
            "Minor adjustments to delivered features (e.g. text changes, color tweaks)",
            "Browser compatibility issues discovered after launch",
        ])
        body_text(f"This window begins on the date the client formally accepts the MVP and ends {maint_days} calendar days later. Work requested during this window that falls outside the original MVP scope (Section 2) is not covered and will be billed under Sections 5 or 6.")

        # Section 5 - Maintenance (no examples list)
        section_heading("5. Maintenance & Support (Post-Window)")
        body_text(f"After the {maint_days}-day free maintenance window expires, ongoing maintenance is available at the following rate. Maintenance covers preserving and supporting functionality that has already been built and delivered.")
        add_table([
            ("Maintenance Hourly Rate", "$100/hour"),
            ("Billing Increment", "Billed in one-hour minimum increments"),
            ("Invoicing", "Net 30 days from invoice date"),
        ])

        # Section 6 - New Feature Development (no examples list)
        section_heading("6. New Feature Development")
        body_text("Any feature, functionality, page, or integration that did not exist in the delivered MVP is considered new feature development. This work requires separate scoping, design, development, testing, and deployment.")
        add_table([
            ("New Feature Hourly Rate", "$200/hour"),
            ("Billing Increment", "Billed in one-hour minimum increments"),
            ("Authorization", "Written approval required before work begins"),
            ("Invoicing", "Net 30 days from invoice date"),
        ])
        body_text("The simple test: if it existed in the MVP and needs to be fixed or tweaked, it's maintenance ($100/hr). If it didn't exist and needs to be built, it's a new feature ($200/hr).")

        # Section 7 - Ongoing Hosting & Infrastructure
        section_heading("7. Ongoing Hosting & Infrastructure")
        cycle_label = {"monthly": "month", "quarterly": "quarter", "annually": "year"}.get(hosting_cycle, "month")
        body_text(f"After the MVP is delivered and accepted, the application requires ongoing hosting, data storage, and infrastructure services to remain operational. These services are billed separately from development work.")
        add_table([
            ("Hosting & Infrastructure Fee", f"${hosting_fee}/{cycle_label}"),
            ("Billing Cycle", hosting_cycle.title()),
        ])
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*BLACK)
        pdf.cell(0, 6, "Includes:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(0, 5, "Server hosting, data storage, SSL certificates, domain management, and routine infrastructure upkeep.")
        pdf.ln(3)
        body_text("This fee covers the cost of keeping the application live and accessible. It does not include development work, which is billed under Sections 5 and 6. The hosting fee may be adjusted with 30 days written notice to reflect changes in infrastructure requirements or third-party provider pricing.")

        # Section 8 - General Terms (no termination clause, $50/day late fee)
        section_heading("8. General Terms")
        terms = [
            "All project scopes, timelines, and fees are confirmed in this signed SOW before work begins.",
            "Client is responsible for timely feedback, content, and approvals. Client-caused delays may affect the delivery timeline and do not extend the free maintenance window.",
            "Built by Bean LLC has no obligation to perform any work beyond the delivered and accepted MVP unless separately contracted in writing.",
            "Built by Bean LLC reserves the right to display completed work in its portfolio unless the client requests otherwise in writing prior to project start.",
            "All fees are in USD. Late payments are subject to a $50 per day late fee for each day payment remains outstanding past the invoice due date.",
            "This SOW, once signed by both parties, constitutes a binding agreement for the scope and terms described herein.",
        ]
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRAY)
        for term in terms:
            pdf.cell(6, 5.5, "-")
            pdf.multi_cell(0, 5.5, f" {term}")
            pdf.ln(2)

        # Section 9 - Limitation of Liability (generic service references)
        section_heading("9. Limitation of Liability & Disclaimers")
        disclaimers = [
            "Built by Bean LLC provides web development services on a best-effort basis. To the maximum extent permitted by law, Built by Bean LLC shall not be held liable for any indirect, incidental, consequential, or punitive damages, including but not limited to loss of revenue, data, or business opportunities, arising from or related to the services provided under this SOW.",
            "Built by Bean LLC is not responsible for outages, data loss, or service interruptions caused by third-party infrastructure providers, including but not limited to hosting platforms, cloud storage services, domain registrars, DNS providers, email delivery services, or payment processors. Client acknowledges that these services operate under their own terms and service level agreements.",
            "Built by Bean LLC does not guarantee 100% uptime or availability of any deployed application. While reasonable efforts will be made to ensure reliability, factors outside of Built by Bean LLC's control - including server failures, network outages, cyberattacks, and force majeure events - may impact availability.",
            "Client is solely responsible for maintaining backups of any content, data, or credentials provided to Built by Bean LLC during the project. Built by Bean LLC is not responsible for loss of client-provided materials.",
            "Built by Bean LLC's total liability under this SOW shall not exceed the total fees paid by the client under this agreement.",
            "Any intellectual property, code, or design work created by Built by Bean LLC becomes the property of the client only upon receipt of full payment. Until full payment is received, all work product remains the property of Built by Bean LLC.",
            "Client is responsible for ensuring that any content, images, trademarks, or materials provided for use in the project do not infringe on third-party intellectual property rights. Client agrees to indemnify Built by Bean LLC against any claims arising from client-provided materials.",
            "This agreement shall be governed by the laws of the State of Texas. Any disputes arising under this agreement shall be resolved in the courts of the State of Texas.",
        ]
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*GRAY)
        for d in disclaimers:
            pdf.cell(6, 5.5, "-")
            pdf.multi_cell(0, 5, f" {d}")
            pdf.ln(2)

        # Signatures
        pdf.ln(4)
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.5)
        pdf.line(30, pdf.get_y(), 180, pdf.get_y())
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 7, "SIGNATURES", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        body_text("By signing below, both parties agree to the scope, pricing, and terms outlined in this Statement of Work.")

        # Built by Bean signature (pre-filled) - keep block together
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 7, "Built by Bean LLC", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        # Signature line with cursive font
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(30, 8, "Signature:")
        try:
            pdf.set_font("DancingScript", "", 20)
            pdf.set_text_color(*NAVY)
            pdf.cell(100, 8, "Michael Bean", new_x="LMARGIN", new_y="NEXT")
        except Exception:
            pdf.set_font("Helvetica", "I", 14)
            pdf.set_text_color(*NAVY)
            pdf.cell(100, 8, "Michael Bean", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for label, value in [("Printed Name", "Michael Bean"), ("Title", "Owner, Built by Bean LLC"), ("Date", sow_date)]:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*BLACK)
            pdf.cell(30, 8, f"{label}:")
            pdf.set_text_color(*GRAY)
            pdf.cell(100, 8, value, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        pdf.ln(6)

        # Client signature - keep block together
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(0, 7, client_name, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        # Only the client's block is captured. The Built by Bean signature
        # above it is already on the page, and offering to collect it again
        # would be asking somebody to sign their own document.
        sign_anchors = []
        for label in ["Signature", "Printed Name", "Title", "Date"]:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*BLACK)
            sign_anchors.append({"label": label, "page": pdf.page_no(), "y": pdf.get_y(),
                                 "x": SIGN_FIELD_X, "w": SIGN_FIELD_W, "h": SIGN_FIELD_H})
            pdf.cell(30, 8, f"{label}:")
            pdf.cell(100, 8, "_" * 50, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        # Contact - keep together
        if pdf.get_y() > pdf.h - 30:
            pdf.add_page()
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*BLACK)
        pdf.cell(0, 6, "Phone: 903-491-2095", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "Email: mbean@builtbybeans.com", new_x="LMARGIN", new_y="NEXT")

        pdf_bytes = bytes(pdf.output())
        safe_name = client_name.replace(" ", "_").replace("&", "and")
        filename = f"{safe_name}_SOW_{project_name.replace(' ', '_')}.pdf"

        # Auto-save PDF to client and update stage/revenue
        # Chosen from the picker above, so always found. This was an ilike on
        # a typed name, which filed nothing when the spelling drifted.
        doc = None
        project = None
        if client:
            stored_name = f"{uuid.uuid4().hex}.pdf"
            if _s3_client:
                s3_key = f"documents/{stored_name}"
                _s3_client.put_object(
                    Bucket=_s3_bucket, Key=s3_key, Body=pdf_bytes,
                    ContentType="application/pdf",
                )
            else:
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "documents")
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, stored_name), "wb") as f:
                    f.write(pdf_bytes)
            doc = Document(
                client_id=client.id, filename=stored_name,
                original_name=filename, file_size=len(pdf_bytes),
            )
            db.session.add(doc)
            # Parse MVP price and update client stage + revenue
            try:
                price_val = float(mvp_price.replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                price_val = 0.0
            client.stage = "contracted"
            client.contract_revenue = price_val
            # Update matching project with MVP date and maintenance days
            project = Project.query.filter(
                Project.client_id == client.id,
                Project.name.ilike(project_name),
            ).first()
            if project:
                try:
                    project.mvp_date = datetime.strptime(delivery_date, "%B %d, %Y").date()
                except (ValueError, TypeError):
                    pass
                project.maintenance_days = maint_days
                project.phase = "contracted"
                project.budget = price_val
            db.session.commit()

        sent = send_generated(
            bytes(pdf_bytes), filename=filename,
            title=f"Statement of Work - {project_name}",
            kind="sow",
            fields=signadoc_service.fields_for(sign_anchors, pdf.w, pdf.h),
            client=client, project=project, document=doc,
        )
        if sent:
            return redirect(url_for("contracts.contract_detail", id=sent.id))

        from flask import make_response
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Content-Length"] = len(pdf_bytes)
        return response

    # ── Time Tracking ────────────────────────────────────────

    @pm_bp.route("/time")
    @login_required
    def time_list():
        page = request.args.get("page", 1, type=int)
        project_id = request.args.get("project_id", "", type=str)
        rate_type = request.args.get("rate_type", "")

        query = TimeEntry.query.join(Project).join(Client)
        if project_id:
            query = query.filter(TimeEntry.project_id == int(project_id))
        if rate_type:
            query = query.filter(TimeEntry.rate_type == rate_type)

        query = query.order_by(TimeEntry.date.desc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)

        all_filtered = TimeEntry.query
        if project_id:
            all_filtered = all_filtered.filter(TimeEntry.project_id == int(project_id))
        if rate_type:
            all_filtered = all_filtered.filter(TimeEntry.rate_type == rate_type)
        all_entries = all_filtered.all()
        total_hours = sum(e.hours for e in all_entries)
        total_cost = sum(e.cost for e in all_entries)

        projects = Project.query.order_by(Project.name).all()

        invoiced_ids = set()
        entry_ids = [e.id for e in pagination.items]
        if entry_ids:
            invoiced_rows = db.session.query(InvoiceLineItem.time_entry_id).filter(
                InvoiceLineItem.time_entry_id.in_(entry_ids),
                InvoiceLineItem.invoice.has(Invoice.status.in_(["draft", "open", "paid"]))
            ).all()
            invoiced_ids = {r[0] for r in invoiced_rows}

        return render_template("pm/time/list.html",
            entries=pagination.items, pagination=pagination, projects=projects,
            project_id=project_id, rate_type=rate_type,
            total_hours=total_hours, total_cost=total_cost,
            invoiced_ids=invoiced_ids)

    @pm_bp.route("/time/new", methods=["GET", "POST"])
    @login_required
    def time_create():
        form = TimeEntryForm()
        projects = Project.query.join(Client).order_by(Project.name).all()
        form.project_id.choices = [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.ticket_id.choices = _ticket_choices()

        pre_project = request.args.get("project_id", type=int)
        pre_ticket = request.args.get("ticket_id", type=int)
        if request.method == "GET":
            if pre_project:
                form.project_id.data = pre_project
            if pre_ticket:
                form.ticket_id.data = pre_ticket
            if not form.date.data:
                form.date.data = date.today()

        if form.validate_on_submit():
            project = db.session.get(Project, form.project_id.data)
            entry = TimeEntry(
                project_id=form.project_id.data,
                ticket_id=form.ticket_id.data if form.ticket_id.data != 0 else None,
                client_id=project.client_id if project else None,
                date=form.date.data,
                hours=form.hours.data,
                description=form.description.data or "",
                rate_type=form.rate_type.data,
            )
            db.session.add(entry)
            db.session.flush()
            billed = _sync_expense_for_time_entry(entry, project)
            db.session.commit()
            if billed:
                flash(f"Logged {entry.hours}h ({entry.rate_type}) = {format_currency(entry.cost)} — expense auto-created", "success")
            elif _in_free_maintenance(project, entry.rate_type):
                flash(f"Logged {entry.hours}h ({entry.rate_type}) — free maintenance window, no charge", "success")
            else:
                flash(f"Logged {entry.hours}h ({entry.rate_type}) = {format_currency(entry.cost)}", "success")
            return redirect(url_for("pm.time_list"))
        return render_template("pm/time/form.html", form=form, editing=False)

    @pm_bp.route("/time/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def time_edit(id):
        entry = db.session.get(TimeEntry, id) or abort(404)
        form = TimeEntryForm(obj=entry)
        projects = Project.query.join(Client).order_by(Project.name).all()
        form.project_id.choices = [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.ticket_id.choices = _ticket_choices()
        if not entry.ticket_id:
            form.ticket_id.data = 0
        if form.validate_on_submit():
            project = db.session.get(Project, form.project_id.data)
            entry.project_id = form.project_id.data
            entry.ticket_id = form.ticket_id.data if form.ticket_id.data != 0 else None
            entry.client_id = project.client_id if project else None
            entry.date = form.date.data
            entry.hours = form.hours.data
            entry.description = form.description.data or ""
            entry.rate_type = form.rate_type.data
            _sync_expense_for_time_entry(entry, project)
            db.session.commit()
            flash("Time entry updated.", "success")
            return redirect(url_for("pm.time_list"))
        return render_template("pm/time/form.html", form=form, editing=True, entry=entry)

    @pm_bp.route("/time/<int:id>/delete", methods=["POST"])
    @login_required
    def time_delete(id):
        entry = db.session.get(TimeEntry, id) or abort(404)
        if entry.expense:
            db.session.delete(entry.expense)
        db.session.delete(entry)
        db.session.commit()
        flash("Time entry deleted.", "success")
        return redirect(url_for("pm.time_list"))

    # ── Live Working-Session Timer ───────────────────────────

    def _current_timer():
        return TimerSession.query.filter_by(user_id=current_user.id).first()

    def _valid_rate_type(value):
        valid = {c[0] for c in RATE_TYPE_CHOICES}
        return value if value in valid else "maintenance"

    @pm_bp.route("/time/timer/state")
    @login_required
    def timer_state():
        return jsonify(_timer_state(_current_timer()))

    @pm_bp.route("/time/timer/start", methods=["POST"])
    @login_required
    def timer_start():
        if _current_timer():
            return jsonify(error="A timer is already running."), 409
        project_id = request.form.get("project_id", type=int)
        project = db.session.get(Project, project_id) if project_id else None
        timer = TimerSession(
            user_id=current_user.id,
            project_id=project.id if project else None,
            rate_type=_valid_rate_type(request.form.get("rate_type", "maintenance")),
            description="",
            accumulated_seconds=0,
            is_paused=False,
            last_resumed_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(timer)
        try:
            db.session.commit()
        except IntegrityError:
            # Concurrent double-start raced past the guard above; the unique
            # user_id constraint rejected this one. Report the existing timer.
            db.session.rollback()
            return jsonify(error="A timer is already running."), 409
        return jsonify(_timer_state(timer))

    @pm_bp.route("/time/timer/pause", methods=["POST"])
    @login_required
    def timer_pause():
        timer = _current_timer()
        if not timer:
            return jsonify(error="No active timer."), 404
        if not timer.is_paused:
            timer.accumulated_seconds = int(round(timer.elapsed_seconds))
            timer.is_paused = True
            timer.last_resumed_at = None
            db.session.commit()
        return jsonify(_timer_state(timer))

    @pm_bp.route("/time/timer/resume", methods=["POST"])
    @login_required
    def timer_resume():
        timer = _current_timer()
        if not timer:
            return jsonify(error="No active timer."), 404
        if timer.is_paused:
            timer.is_paused = False
            timer.last_resumed_at = datetime.now(timezone.utc)
            db.session.commit()
        return jsonify(_timer_state(timer))

    @pm_bp.route("/time/timer/update", methods=["POST"])
    @login_required
    def timer_update():
        """Live-save the rate/project/description while a timer runs."""
        timer = _current_timer()
        if not timer:
            return jsonify(error="No active timer."), 404
        if "rate_type" in request.form:
            timer.rate_type = _valid_rate_type(request.form.get("rate_type"))
        if "project_id" in request.form:
            pid = request.form.get("project_id", type=int)
            timer.project_id = pid if pid else None
        if "description" in request.form:
            timer.description = request.form.get("description", "")
        db.session.commit()
        return jsonify(_timer_state(timer))

    @pm_bp.route("/time/timer/cancel", methods=["POST"])
    @login_required
    def timer_cancel():
        timer = _current_timer()
        if timer:
            db.session.delete(timer)
            db.session.commit()
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=True)
        flash("Timer discarded — nothing was logged.", "warning")
        return redirect(url_for("pm.time_list"))

    @pm_bp.route("/time/timer/review", methods=["GET"])
    @login_required
    def timer_review():
        """Stop the clock and show the save form pre-filled from the session."""
        timer = _current_timer()
        if not timer:
            flash("No active timer to save.", "warning")
            return redirect(url_for("pm.time_list"))
        # Freeze the clock so the elapsed total can't drift while reviewing.
        if not timer.is_paused:
            timer.accumulated_seconds = int(round(timer.elapsed_seconds))
            timer.is_paused = True
            timer.last_resumed_at = None
            db.session.commit()
        projects = Project.query.join(Client).order_by(Project.name).all()
        billable_hours = _billable_hours_from_seconds(timer.accumulated_seconds)
        return render_template(
            "pm/time/timer_review.html",
            timer=timer,
            projects=projects,
            billable_hours=billable_hours,
            today=date.today().isoformat(),
        )

    @pm_bp.route("/time/timer/save", methods=["POST"])
    @login_required
    def timer_save():
        timer = _current_timer()
        if not timer:
            flash("No active timer to save.", "warning")
            return redirect(url_for("pm.time_list"))

        project_id = request.form.get("project_id", type=int)
        project = db.session.get(Project, project_id) if project_id else None
        if not project:
            flash("Pick a project to apply this session to.", "error")
            return redirect(url_for("pm.timer_review"))

        hours = request.form.get("hours", type=float)
        if not hours or hours <= 0:
            hours = _billable_hours_from_seconds(timer.accumulated_seconds)

        entry_date = date.today()
        raw_date = request.form.get("date", "")
        if raw_date:
            try:
                entry_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        entry = TimeEntry(
            project_id=project.id,
            client_id=project.client_id,
            date=entry_date,
            hours=hours,
            description=request.form.get("description", "") or "",
            rate_type=_valid_rate_type(request.form.get("rate_type", timer.rate_type)),
        )
        db.session.add(entry)
        db.session.flush()
        billed = _sync_expense_for_time_entry(entry, project)
        db.session.delete(timer)
        db.session.commit()

        if billed:
            flash(f"Session saved: {entry.hours}h ({entry.rate_type.replace('_', ' ')}) "
                  f"= {format_currency(entry.cost)} — added to {project.name}", "success")
        elif _in_free_maintenance(project, entry.rate_type):
            flash(f"Session saved: {entry.hours}h — free maintenance window, no charge", "success")
        else:
            flash(f"Session saved: {entry.hours}h ({entry.rate_type.replace('_', ' ')}) "
                  f"= {format_currency(entry.cost)}", "success")
        return redirect(url_for("pm.time_list"))

    # ── API: Tickets for Project (for dynamic dropdowns) ───────

    @pm_bp.route("/api/projects/<int:project_id>/tickets")
    @login_required
    def api_project_tickets(project_id):
        rows = (Ticket.query.filter_by(project_id=project_id)
                .order_by(Ticket.created_at.desc()).all())
        return jsonify([{"id": t.id, "title": t.display_title} for t in rows])

    # ── Expenses ─────────────────────────────────────────────

    @pm_bp.route("/expenses")
    @login_required
    def expenses_list():
        generate_due_recurring_expenses()
        page = request.args.get("page", 1, type=int)
        category = request.args.get("category", "")
        project_id = request.args.get("project_id", "", type=str)

        # Only real (material) expenses — time-entry-linked "billable time" rows are
        # pipeline revenue, not expenses, and are shown on the Time Tracking side.
        query = Expense.query.filter(Expense.time_entry_id.is_(None)).outerjoin(Client, Expense.client_id == Client.id).outerjoin(Project, Expense.project_id == Project.id).outerjoin(Ticket, Expense.ticket_id == Ticket.id)
        if category:
            query = query.filter(Expense.category == category)
        if project_id:
            query = query.filter(Expense.project_id == int(project_id))

        query = query.order_by(Expense.date.desc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)

        all_filtered = Expense.query.filter(Expense.time_entry_id.is_(None))
        if category:
            all_filtered = all_filtered.filter(Expense.category == category)
        if project_id:
            all_filtered = all_filtered.filter(Expense.project_id == int(project_id))
        total_expenses = sum(e.amount for e in all_filtered.all())

        projects = Project.query.order_by(Project.name).all()
        return render_template("pm/expenses/list.html",
            expenses=pagination.items, pagination=pagination, projects=projects,
            category=category, project_id=project_id, total_expenses=total_expenses)

    @pm_bp.route("/expenses/new", methods=["GET", "POST"])
    @login_required
    def expense_create():
        form = ExpenseForm()
        clients = Client.query.order_by(Client.name).all()
        projects = Project.query.order_by(Project.name).all()
        form.client_id.choices = [(0, "— No client —")] + [(c.id, c.name) for c in clients]
        form.project_id.choices = [(0, "— No project —")] + [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.ticket_id.choices = _ticket_choices("No ticket")

        pre_ticket = request.args.get("ticket_id", type=int)
        if request.method == "GET":
            if pre_ticket:
                form.ticket_id.data = pre_ticket
                ticket_obj = db.session.get(Ticket, pre_ticket)
                if ticket_obj:
                    form.project_id.data = ticket_obj.project_id
                    # Off the ticket, not through the project. A ticket carries
                    # its own client now and its project is nullable, so the old
                    # hop through .project raised AttributeError the moment one
                    # arrived without being filed under a project.
                    form.client_id.data = ticket_obj.client_id
            if not form.date.data:
                form.date.data = date.today()

        if form.validate_on_submit():
            stored_name, original_name, size = None, None, 0
            if form.receipt.data:
                stored_name, original_name, size = save_upload(form.receipt.data, "receipts")

            is_rec = request.form.get("is_recurring") == "y" and form.frequency.data
            expense = Expense(
                client_id=form.client_id.data or None,
                project_id=form.project_id.data or None,
                ticket_id=form.ticket_id.data or None,
                amount=form.amount.data,
                description=form.description.data or "",
                category=form.category.data,
                date=form.date.data,
                receipt_filename=stored_name,
                receipt_original_name=original_name,
                is_recurring=bool(is_rec),
                frequency=form.frequency.data if is_rec else None,
                recurring_end_date=form.recurring_end_date.data if is_rec else None,
                next_due_date=_advance_date(form.date.data, form.frequency.data) if is_rec else None,
            )
            db.session.add(expense)
            db.session.commit()
            flash(f"Expense of {format_currency(expense.amount)} added.", "success")
            return redirect(url_for("pm.expenses_list"))
        return render_template("pm/expenses/form.html", form=form, editing=False)

    @pm_bp.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def expense_edit(id):
        expense = db.session.get(Expense, id) or abort(404)
        if expense.is_auto_generated:
            flash("Auto-generated expenses can only be changed by editing the linked time entry.", "warning")
            return redirect(url_for("pm.expenses_list"))
        form = ExpenseForm(obj=expense)
        clients = Client.query.order_by(Client.name).all()
        projects = Project.query.order_by(Project.name).all()
        form.client_id.choices = [(0, "— No client —")] + [(c.id, c.name) for c in clients]
        form.project_id.choices = [(0, "— No project —")] + [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.ticket_id.choices = _ticket_choices("No ticket")

        if request.method == "GET":
            form.client_id.data = expense.client_id or 0
            form.project_id.data = expense.project_id or 0
            form.ticket_id.data = expense.ticket_id or 0
            form.is_recurring.data = expense.is_recurring
            form.frequency.data = expense.frequency or ""
            form.recurring_end_date.data = expense.recurring_end_date

        if form.validate_on_submit():
            expense.client_id = form.client_id.data or None
            expense.project_id = form.project_id.data or None
            expense.ticket_id = form.ticket_id.data or None
            expense.amount = form.amount.data
            expense.description = form.description.data or ""
            expense.category = form.category.data
            expense.date = form.date.data

            is_rec = request.form.get("is_recurring") == "y" and form.frequency.data
            expense.is_recurring = bool(is_rec)
            expense.frequency = form.frequency.data if is_rec else None
            expense.recurring_end_date = form.recurring_end_date.data if is_rec else None
            if is_rec and not expense.next_due_date:
                expense.next_due_date = _advance_date(form.date.data, form.frequency.data)

            if form.receipt.data:
                stored_name, original_name, size = save_upload(form.receipt.data, "receipts")
                if stored_name:
                    if expense.receipt_filename:
                        delete_upload(expense.receipt_filename, "receipts")
                    expense.receipt_filename = stored_name
                    expense.receipt_original_name = original_name
            db.session.commit()
            flash("Expense updated.", "success")
            return redirect(url_for("pm.expenses_list"))
        return render_template("pm/expenses/form.html", form=form, editing=True, expense=expense)

    @pm_bp.route("/expenses/<int:id>/delete", methods=["POST"])
    @login_required
    def expense_delete(id):
        expense = db.session.get(Expense, id) or abort(404)
        if expense.is_auto_generated:
            flash("Auto-generated expenses are deleted when their time entry is deleted.", "warning")
            return redirect(url_for("pm.expenses_list"))
        if expense.receipt_filename:
            delete_upload(expense.receipt_filename, "receipts")
        db.session.delete(expense)
        db.session.commit()
        flash("Expense deleted.", "success")
        return redirect(url_for("pm.expenses_list"))

    @pm_bp.route("/expenses/<int:id>/receipt")
    @login_required
    def expense_receipt(id):
        expense = db.session.get(Expense, id) or abort(404)
        if not expense.receipt_filename:
            abort(404)
        return download_upload(expense.receipt_filename, expense.receipt_original_name, "receipts")

    # ── Reports ──────────────────────────────────────────────

    @pm_bp.route("/reports")
    @login_required
    def reports():
        clients = Client.query.order_by(Client.name).all()
        client_data = []
        for c in clients:
            projects = c.projects.all()
            total_hours = c.total_hours
            total_revenue = c.total_revenue
            total_expenses = sum(p.total_expenses for p in projects)
            client_data.append({
                "client": c,
                "projects_count": len(projects),
                "total_hours": total_hours,
                "total_revenue": total_revenue,
                "total_expenses": total_expenses,
                "net": total_revenue - total_expenses,
            })

        projects_list_data = []
        for p in Project.query.join(Client).order_by(Project.name).all():
            projects_list_data.append({
                "project": p,
                "client_name": p.client.name,
                "phase": p.phase,
                "total_hours": p.total_hours,
                "total_revenue": p.total_revenue,
                "total_expenses": p.total_expenses,
            })

        today = date.today()
        monthly_data = []
        for i in range(6):
            month = today.month - i
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            first = date(year, month, 1)
            if month == 12:
                last = date(year + 1, 1, 1)
            else:
                last = date(year, month + 1, 1)
            entries = TimeEntry.query.filter(TimeEntry.date >= first, TimeEntry.date < last).all()
            maint_hours = sum(e.hours for e in entries if e.rate_type == "maintenance")
            feat_hours = sum(e.hours for e in entries if e.rate_type == "new_feature")
            maint_rev = sum(e.cost for e in entries if e.rate_type == "maintenance")
            feat_rev = sum(e.cost for e in entries if e.rate_type == "new_feature")
            monthly_data.append({
                "label": first.strftime("%b %Y"),
                "maintenance_hours": maint_hours,
                "feature_hours": feat_hours,
                "maintenance_revenue": maint_rev,
                "feature_revenue": feat_rev,
                "total_revenue": maint_rev + feat_rev,
            })

        expense_by_cat = {}
        for cat_val, cat_label in EXPENSE_CATEGORY_CHOICES:
            total = sum(e.amount for e in Expense.query.filter_by(category=cat_val).filter(
                Expense.time_entry_id.is_(None)).all())
            if total > 0:
                expense_by_cat[cat_label] = total

        return render_template("pm/reports/index.html",
            client_data=client_data,
            projects_data=projects_list_data,
            monthly_data=monthly_data,
            expense_by_cat=expense_by_cat,
        )

    # ── Register PM blueprint ────────────────────────────────
    app.register_blueprint(pm_bp)

    # ── Error Handlers ───────────────────────────────────────

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
