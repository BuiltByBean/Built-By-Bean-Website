import os
import uuid
from datetime import datetime, timezone, date, timedelta
from dateutil.relativedelta import relativedelta

import boto3
from botocore.exceptions import ClientError
from flask import (
    Flask, Blueprint, render_template, redirect, url_for, flash, request, abort,
    send_from_directory, jsonify, Response,
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

from config import Config
from models import db, Client, Project, Task, Expense, TimeEntry, Document, User, Invoice, InvoiceLineItem
from forms import (
    ClientForm, ProjectForm, TaskForm, ExpenseForm, TimeEntryForm, LoginForm,
    PHASE_CHOICES, PROJECT_STATUS_CHOICES, TASK_STATUS_CHOICES,
    PRIORITY_CHOICES, RATE_TYPE_CHOICES, EXPENSE_CATEGORY_CHOICES,
    FREQUENCY_CHOICES,
)


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
    _s3_client = boto3.client(
        "s3",
        region_name=_s3_region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    ) if _s3_bucket else None

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

        if not User.query.filter(User.username.ilike("tlane")).first():
            dev = User(
                username="tlane",
                first_name="T",
                last_name="Lane",
                email="tlane@builtbybean.com",
                role="admin",
                must_change_password=True,
            )
            dev.set_password("password")
            db.session.add(dev)
            db.session.commit()

        # One-time admin upsert: ensure Mbean exists with the known password.
        # Remove this block once login is verified.
        _mbean = User.query.filter(User.username.ilike("Mbean")).first()
        if _mbean is None:
            _mbean_by_email = User.query.filter(User.email.ilike("mbean@builtbybean.com")).first()
            if _mbean_by_email is not None:
                _mbean_by_email.username = "Mbean"
                _mbean = _mbean_by_email
            else:
                _mbean = User(
                    username="Mbean",
                    first_name="Matthew",
                    last_name="Bean",
                    email="mbean@builtbybean.com",
                    role="admin",
                    must_change_password=False,
                )
                db.session.add(_mbean)
        _mbean.set_password("Scout0213!")
        if hasattr(_mbean, "must_change_password"):
            _mbean.must_change_password = False
        _mbean.role = "admin"
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
                _s3_client.put_object(
                    Bucket=_s3_bucket,
                    Key=s3_key,
                    Body=file_data,
                    ContentType=file.content_type or "application/octet-stream",
                )
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
        if _s3_client:
            s3_obj = _s3_client.get_object(Bucket=_s3_bucket, Key=f"{subfolder}/{stored_name}")
            data = s3_obj["Body"].read()
            return Response(
                data,
                headers={"Content-Disposition": f'attachment; filename="{original_name}"'},
                content_type=s3_obj.get("ContentType", "application/octet-stream"),
            )
        folder = os.path.join(app.config["UPLOAD_FOLDER"], subfolder)
        return send_from_directory(folder, stored_name, as_attachment=True, download_name=original_name)

    # ── Auto-Expense Helpers ──────────────────────────────────

    def _in_free_maintenance(project, rate_type):
        """Check if this work falls within the project's free maintenance window."""
        if rate_type == "maintenance" and project and project.free_maintenance_end:
            if project.free_maintenance_end >= date.today():
                return True
        return False

    def _sync_expense_for_time_entry(entry, project):
        """Create, update, or delete the auto-generated expense for a time entry."""
        skip = entry.rate_type == "mvp_build" or _in_free_maintenance(project, entry.rate_type)

        if skip:
            # Remove existing auto-expense if switching into free window
            if entry.expense:
                db.session.delete(entry.expense)
            return False  # no expense created

        desc = f"{entry.hours}h {entry.rate_type.replace('_', ' ')} — {entry.description or 'Time entry'}"

        if entry.expense:
            # Update existing
            expense = entry.expense
            expense.client_id = entry.client_id
            expense.project_id = entry.project_id
            expense.task_id = entry.task_id
            expense.amount = entry.cost
            expense.description = desc
            expense.date = entry.date
        else:
            # Create new
            expense = Expense(
                time_entry_id=entry.id,
                client_id=entry.client_id,
                project_id=entry.project_id,
                task_id=entry.task_id,
                amount=entry.cost,
                description=desc,
                category="billable_time",
                date=entry.date,
            )
            db.session.add(expense)
        return True  # expense was created/updated

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
                    task_id=parent.task_id,
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

    @app.context_processor
    def inject_globals():
        return {
            "now": datetime.now(timezone.utc),
            "asset_version": _asset_version,
            "phase_choices": PHASE_CHOICES,
            "status_choices": PROJECT_STATUS_CHOICES,
            "task_status_choices": TASK_STATUS_CHOICES,
            "priority_choices": PRIORITY_CHOICES,
            "rate_type_choices": RATE_TYPE_CHOICES,
            "expense_category_choices": EXPENSE_CATEGORY_CHOICES,
            "frequency_choices": FREQUENCY_CHOICES,
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
            return redirect(url_for("admin_hub"))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter(User.username.ilike(form.username.data)).first()
            if user and user.check_password(form.password.data):
                login_user(user)
                return redirect(request.args.get("next") or url_for("admin_hub"))
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
                return redirect(url_for("admin_hub"))
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
        return render_template("admin_hub.html")

    # ── Dashboard ────────────────────────────────────────────

    @pm_bp.route("/")
    @login_required
    def dashboard():
        today = date.today()

        # All-time financials
        total_contracted = db.session.query(db.func.sum(Client.contract_revenue)).scalar() or 0
        total_revenue = db.session.query(db.func.sum(Invoice.amount_paid)).filter(
            Invoice.status == "paid"
        ).scalar() or 0
        total_expenses = db.session.query(db.func.sum(Expense.amount)).scalar() or 0

        # Per-client financials
        clients = Client.query.order_by(Client.name).all()
        client_financials = []
        for c in clients:
            c_revenue = sum(inv.amount_paid for inv in c.invoices if inv.status == "paid")
            c_expenses = sum(e.amount for e in Expense.query.filter_by(client_id=c.id).all()) if hasattr(Expense, 'client_id') else 0
            client_financials.append({
                "id": c.id,
                "name": c.name,
                "stage": c.stage or "lead",
                "contracted": c.contract_revenue or 0,
                "revenue": c_revenue,
                "expenses": c_expenses,
            })

        # Upcoming deadlines
        upcoming_tasks = Task.query.filter(
            Task.due_date >= today, Task.status != "done"
        ).order_by(Task.due_date.asc()).limit(10).all()

        return render_template("pm/dashboard/index.html",
            total_contracted=total_contracted,
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            client_financials=client_financials,
            upcoming_tasks=upcoming_tasks,
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
            flash(f"Project '{project.name}' created.", "success")
            return redirect(url_for("pm.project_detail", id=project.id))
        return render_template("pm/projects/form.html", form=form, editing=False)

    @pm_bp.route("/projects/<int:id>")
    @login_required
    def project_detail(id):
        project = db.session.get(Project, id) or abort(404)
        tasks = project.tasks.filter(Task.parent_task_id.is_(None)).order_by(Task.created_at.desc()).all()
        time_entries = project.time_entries.order_by(TimeEntry.date.desc()).all()
        expenses = Expense.query.filter(Expense.project_id == project.id).order_by(Expense.date.desc()).all()
        documents = project.documents.order_by(Document.uploaded_at.desc()).all()
        return render_template("pm/projects/detail.html",
            project=project, tasks=tasks, time_entries=time_entries, expenses=expenses, documents=documents)

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

    # ── Tasks ────────────────────────────────────────────────

    def _propagate_task_completion(task):
        """Walk up the parent chain. If every sibling subtask is done,
        mark the parent done too. Recurse."""
        parent = task.parent_task
        while parent is not None:
            total = parent.subtasks.count()
            done = parent.subtasks.filter(Task.status == "done").count()
            if total > 0 and total == done and parent.status != "done":
                parent.status = "done"
                parent = parent.parent_task
            else:
                break

    def _reopen_task_ancestors(task):
        """If a subtask moves away from 'done', reopen any ancestor that is 'done'."""
        parent = task.parent_task
        while parent is not None:
            if parent.status == "done":
                parent.status = "in_progress"
                parent = parent.parent_task
            else:
                break

    @pm_bp.route("/tasks")
    @login_required
    def tasks_list():
        page = request.args.get("page", 1, type=int)
        search = request.args.get("search", "")
        status = request.args.get("status", "")
        priority = request.args.get("priority", "")
        project_id = request.args.get("project_id", "", type=str)

        query = Task.query.join(Project).join(Client).filter(Task.parent_task_id.is_(None))
        if search:
            query = query.filter(Task.title.ilike(f"%{search}%"))
        if status:
            query = query.filter(Task.status == status)
        if priority:
            query = query.filter(Task.priority == priority)
        if project_id:
            query = query.filter(Task.project_id == int(project_id))

        query = query.order_by(Task.created_at.desc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)
        projects = Project.query.order_by(Project.name).all()
        return render_template("pm/tasks/list.html",
            tasks=pagination.items, pagination=pagination, projects=projects,
            search=search, status=status, priority=priority, project_id=project_id)

    @pm_bp.route("/tasks/quick", methods=["POST"])
    @login_required
    def task_create_quick():
        project_id = request.form.get("project_id", type=int)
        project = db.session.get(Project, project_id) or abort(404)
        title = request.form.get("title", "").strip()
        if not title:
            flash("Task title is required.", "error")
            return redirect(request.form.get("redirect") or url_for("pm.project_detail", id=project_id))
        due_date = None
        raw_date = request.form.get("due_date")
        if raw_date:
            try:
                due_date = date.fromisoformat(raw_date)
            except ValueError:
                pass
        task = Task(
            project_id=project_id,
            title=title,
            description=request.form.get("description", ""),
            status="todo",
            priority=request.form.get("priority", "medium"),
            due_date=due_date,
        )
        db.session.add(task)
        db.session.commit()
        flash(f"Task '{task.title}' created.", "success")
        return redirect(request.form.get("redirect") or url_for("pm.project_detail", id=project_id))

    @pm_bp.route("/tasks/<int:id>/subtasks", methods=["POST"])
    @login_required
    def subtask_create(id):
        parent = db.session.get(Task, id) or abort(404)
        title = request.form.get("title", "").strip()
        if not title:
            flash("Subtask title is required.", "error")
            return redirect(url_for("pm.task_detail", id=parent.id))
        due_date = None
        raw_date = request.form.get("due_date")
        if raw_date:
            try:
                due_date = date.fromisoformat(raw_date)
            except ValueError:
                pass
        sub = Task(
            project_id=parent.project_id,
            parent_task_id=parent.id,
            title=title,
            priority=request.form.get("priority", parent.priority),
            due_date=due_date,
            status="todo",
        )
        db.session.add(sub)
        # A new incomplete child means the parent (and ancestors) can't remain "done"
        _reopen_task_ancestors(sub)
        db.session.commit()
        flash(f"Subtask '{sub.title}' created.", "success")
        return redirect(url_for("pm.task_detail", id=parent.id))

    @pm_bp.route("/tasks/new", methods=["GET", "POST"])
    @login_required
    def task_create():
        form = TaskForm()
        form.project_id.choices = [
            (p.id, f"{p.name} ({p.client.name})") for p in Project.query.join(Client).order_by(Project.name).all()
        ]
        pre_project = request.args.get("project_id", type=int)
        if request.method == "GET" and pre_project:
            form.project_id.data = pre_project
        if form.validate_on_submit():
            task = Task(
                project_id=form.project_id.data,
                title=form.title.data,
                description=form.description.data or "",
                detailed_notes=form.detailed_notes.data or "",
                status=form.status.data,
                priority=form.priority.data,
                due_date=form.due_date.data,
            )
            db.session.add(task)
            db.session.commit()
            flash(f"Task '{task.title}' created.", "success")
            return redirect(url_for("pm.task_detail", id=task.id))
        return render_template("pm/tasks/form.html", form=form, editing=False)

    @pm_bp.route("/tasks/<int:id>")
    @login_required
    def task_detail(id):
        task = db.session.get(Task, id) or abort(404)
        documents = task.documents.order_by(Document.uploaded_at.desc()).all()
        expenses = task.expenses.order_by(Expense.date.desc()).all()
        time_entries = task.time_entries.order_by(TimeEntry.date.desc()).all()
        return render_template("pm/tasks/detail.html",
            task=task, documents=documents, expenses=expenses, time_entries=time_entries)

    @pm_bp.route("/tasks/<int:id>/edit", methods=["GET", "POST"])
    @login_required
    def task_edit(id):
        task = db.session.get(Task, id) or abort(404)
        form = TaskForm(obj=task)
        form.project_id.choices = [
            (p.id, f"{p.name} ({p.client.name})") for p in Project.query.join(Client).order_by(Project.name).all()
        ]
        if form.validate_on_submit():
            form.populate_obj(task)
            db.session.commit()
            flash(f"Task '{task.title}' updated.", "success")
            return redirect(url_for("pm.task_detail", id=task.id))
        return render_template("pm/tasks/form.html", form=form, editing=True, task=task)

    @pm_bp.route("/tasks/<int:id>/delete", methods=["POST"])
    @login_required
    def task_delete(id):
        task = db.session.get(Task, id) or abort(404)
        project_id = task.project_id
        parent_id = task.parent_task_id
        title = task.title
        db.session.delete(task)
        db.session.commit()
        flash(f"Task '{title}' deleted.", "success")
        if parent_id:
            return redirect(url_for("pm.task_detail", id=parent_id))
        return redirect(url_for("pm.project_detail", id=project_id))

    @pm_bp.route("/tasks/<int:id>/status", methods=["POST"])
    @login_required
    def task_status_update(id):
        task = db.session.get(Task, id) or abort(404)
        new_status = request.form.get("status")
        valid = [s[0] for s in TASK_STATUS_CHOICES]
        if new_status in valid:
            task.status = new_status
            if new_status == "done":
                _propagate_task_completion(task)
            else:
                _reopen_task_ancestors(task)
            db.session.commit()
            flash(f"Task status updated to '{dict(TASK_STATUS_CHOICES)[new_status]}'.", "success")
        redirect_to = request.form.get("redirect")
        if redirect_to:
            return redirect(redirect_to)
        if task.parent_task_id:
            return redirect(url_for("pm.task_detail", id=task.parent_task_id))
        return redirect(url_for("pm.task_detail", id=task.id))

    # ── Documents ────────────────────────────────────────────

    @pm_bp.route("/tasks/<int:id>/documents/upload", methods=["POST"])
    @login_required
    def task_upload_document(id):
        task = db.session.get(Task, id) or abort(404)
        files = request.files.getlist("documents")
        count = 0
        for f in files:
            stored_name, original_name, size = save_upload(f, "documents")
            if stored_name:
                doc = Document(
                    task_id=task.id,
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
        return redirect(url_for("pm.task_detail", id=task.id))

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
        task_id = doc.task_id
        project_id = doc.project_id
        client_id = doc.client_id
        delete_upload(doc.filename, "documents")
        db.session.delete(doc)
        db.session.commit()
        flash("Document deleted.", "success")
        if task_id:
            return redirect(url_for("pm.task_detail", id=task_id))
        elif project_id:
            return redirect(url_for("pm.project_detail", id=project_id))
        elif client_id:
            return redirect(url_for("pm.client_detail", id=client_id))
        return redirect(url_for("pm.dashboard"))

    # ── Document Templates ──────────────────────────────────

    @pm_bp.route("/documents/engagement-letter", methods=["GET"])
    @login_required
    def engagement_letter_form():
        return render_template("pm/documents/engagement_letter_form.html", today=date.today().isoformat())

    @pm_bp.route("/documents/engagement-letter", methods=["POST"])
    @login_required
    def generate_engagement_letter():
        from io import BytesIO
        from fpdf import FPDF

        client_name = request.form.get("client_name", "").strip()
        raw_date = request.form.get("date", "")
        project_description = request.form.get("project_description", "").strip()
        mvp_price = "2,500"

        if not client_name or not project_description:
            flash("Client name and project description are required.", "warning")
            return redirect(url_for("pm.engagement_letter_form"))

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
        pdf.cell(0, 6, "Email: MichaelBean21@gmail.com", new_x="LMARGIN", new_y="NEXT")
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

        for label in ["Signature", "Printed Name", "Title", "Date"]:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*BLACK)
            pdf.cell(30, 8, f"{label}:")
            pdf.cell(100, 8, "_" * 50, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

        # Add footers
        for page_num in range(1, pdf.pages_count + 1):
            pdf.page = page_num
            add_footer()

        pdf_bytes = pdf.output()
        safe_name = client_name.replace(" ", "_").replace("&", "and")
        filename = f"{safe_name}_Engagement_Letter.pdf"

        # Auto-save PDF to client
        client = Client.query.filter(Client.name.ilike(client_name)).first()
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

        from flask import make_response as _make_response
        response = _make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @pm_bp.route("/documents/sow", methods=["GET"])
    @login_required
    def sow_form():
        return render_template("pm/documents/sow_form.html", today=date.today().isoformat())

    @pm_bp.route("/documents/sow", methods=["POST"])
    @login_required
    def generate_sow():
        from io import BytesIO
        from fpdf import FPDF

        client_name = request.form.get("client_name", "").strip()
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

        if not client_name or not project_name or not project_description or not features:
            flash("Client name, project name, description, and at least one feature are required.", "warning")
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
            return _build_sow_pdf(client_name, project_name, project_description,
                                  mvp_price, sow_date, delivery_date, maint_days, features,
                                  payment_description, payment_milestones,
                                  hosting_fee, hosting_cycle)
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash(f"PDF generation error: {e}", "error")
            return redirect(url_for("pm.sow_form"))

    def _build_sow_pdf(client_name, project_name, project_description,
                        mvp_price, sow_date, delivery_date, maint_days, features,
                        payment_description, payment_milestones,
                        hosting_fee, hosting_cycle):
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
        for label in ["Signature", "Printed Name", "Title", "Date"]:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*BLACK)
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
        pdf.cell(0, 6, "Email: MichaelBean21@gmail.com", new_x="LMARGIN", new_y="NEXT")

        pdf_bytes = bytes(pdf.output())
        safe_name = client_name.replace(" ", "_").replace("&", "and")
        filename = f"{safe_name}_SOW_{project_name.replace(' ', '_')}.pdf"

        # Auto-save PDF to client and update stage/revenue
        client = Client.query.filter(Client.name.ilike(client_name)).first()
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
        form.task_id.choices = [(0, "— No specific task —")] + [
            (t.id, t.title) for t in Task.query.join(Project).order_by(Task.title).all()
        ]

        pre_project = request.args.get("project_id", type=int)
        pre_task = request.args.get("task_id", type=int)
        if request.method == "GET":
            if pre_project:
                form.project_id.data = pre_project
            if pre_task:
                form.task_id.data = pre_task
            if not form.date.data:
                form.date.data = date.today()

        if form.validate_on_submit():
            project = db.session.get(Project, form.project_id.data)
            entry = TimeEntry(
                project_id=form.project_id.data,
                task_id=form.task_id.data if form.task_id.data != 0 else None,
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
        form.task_id.choices = [(0, "— No specific task —")] + [
            (t.id, t.title) for t in Task.query.join(Project).order_by(Task.title).all()
        ]
        if not entry.task_id:
            form.task_id.data = 0
        if form.validate_on_submit():
            project = db.session.get(Project, form.project_id.data)
            entry.project_id = form.project_id.data
            entry.task_id = form.task_id.data if form.task_id.data != 0 else None
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

    # ── API: Tasks for Project (for dynamic dropdowns) ───────

    @pm_bp.route("/api/projects/<int:project_id>/tasks")
    @login_required
    def api_project_tasks(project_id):
        tasks = Task.query.filter_by(project_id=project_id, parent_task_id=None).order_by(Task.title).all()
        return jsonify([{"id": t.id, "title": t.title} for t in tasks])

    # ── Expenses ─────────────────────────────────────────────

    @pm_bp.route("/expenses")
    @login_required
    def expenses_list():
        generate_due_recurring_expenses()
        page = request.args.get("page", 1, type=int)
        category = request.args.get("category", "")
        project_id = request.args.get("project_id", "", type=str)

        query = Expense.query.outerjoin(Client, Expense.client_id == Client.id).outerjoin(Project, Expense.project_id == Project.id).outerjoin(Task, Expense.task_id == Task.id)
        if category:
            query = query.filter(Expense.category == category)
        if project_id:
            query = query.filter(Expense.project_id == int(project_id))

        query = query.order_by(Expense.date.desc())
        pagination = query.paginate(page=page, per_page=20, error_out=False)

        all_filtered = Expense.query
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
        tasks = Task.query.join(Project).order_by(Project.name, Task.title).all()
        form.client_id.choices = [(0, "— No client —")] + [(c.id, c.name) for c in clients]
        form.project_id.choices = [(0, "— No project —")] + [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.task_id.choices = [(0, "— No task —")] + [(t.id, f"{t.title} ({t.project.name})") for t in tasks]

        pre_task = request.args.get("task_id", type=int)
        if request.method == "GET":
            if pre_task:
                form.task_id.data = pre_task
                task_obj = db.session.get(Task, pre_task)
                if task_obj:
                    form.project_id.data = task_obj.project_id
                    form.client_id.data = task_obj.project.client_id
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
                task_id=form.task_id.data or None,
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
        tasks = Task.query.join(Project).order_by(Project.name, Task.title).all()
        form.client_id.choices = [(0, "— No client —")] + [(c.id, c.name) for c in clients]
        form.project_id.choices = [(0, "— No project —")] + [(p.id, f"{p.name} ({p.client.name})") for p in projects]
        form.task_id.choices = [(0, "— No task —")] + [(t.id, f"{t.title} ({t.project.name})") for t in tasks]

        if request.method == "GET":
            form.client_id.data = expense.client_id or 0
            form.project_id.data = expense.project_id or 0
            form.task_id.data = expense.task_id or 0
            form.is_recurring.data = expense.is_recurring
            form.frequency.data = expense.frequency or ""
            form.recurring_end_date.data = expense.recurring_end_date

        if form.validate_on_submit():
            expense.client_id = form.client_id.data or None
            expense.project_id = form.project_id.data or None
            expense.task_id = form.task_id.data or None
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
            total = sum(e.amount for e in Expense.query.filter_by(category=cat_val).all())
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
