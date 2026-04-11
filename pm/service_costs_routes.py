import json
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, jsonify,
)
from flask_login import login_required

from models import db, Client, Project, ServiceProvider, ServiceMapping, ServiceCostEntry
from service_costs_service import (
    sync_provider, list_provider_resources, get_cost_summary,
)

service_costs_bp = Blueprint("service_costs", __name__, url_prefix="/admin/pm/service-costs")

PROVIDER_TYPES = [
    ("aws", "Amazon Web Services"),
    ("railway", "Railway"),
    ("twilio", "Twilio"),
    ("cloudflare", "Cloudflare"),
]


def _extract_credentials(name):
    if name == "aws":
        return {
            "aws_access_key_id": request.form.get("aws_access_key_id", "").strip(),
            "aws_secret_access_key": request.form.get("aws_secret_access_key", "").strip(),
            "region": request.form.get("region", "us-east-2").strip(),
        }
    elif name == "railway":
        return {"api_token": request.form.get("railway_api_token", "").strip()}
    elif name == "twilio":
        return {
            "account_sid": request.form.get("twilio_account_sid", "").strip(),
            "auth_token": request.form.get("twilio_auth_token", "").strip(),
        }
    elif name == "cloudflare":
        return {
            "api_token": request.form.get("cf_api_token", "").strip(),
            "account_id": request.form.get("cf_account_id", "").strip(),
        }
    return {}


# ── Dashboard ───────────────────────────────────────────────


@service_costs_bp.route("/")
@login_required
def service_costs_dashboard():
    summary = get_cost_summary(months=6)
    providers = ServiceProvider.query.filter_by(is_active=True).all()
    recent_entries = ServiceCostEntry.query.order_by(
        ServiceCostEntry.created_at.desc()
    ).limit(20).all()

    return render_template("pm/service_costs/dashboard.html",
        summary=summary,
        providers=providers,
        recent_entries=recent_entries,
    )


# ── Providers ───────────────────────────────────────────────


@service_costs_bp.route("/providers")
@login_required
def providers_list():
    providers = ServiceProvider.query.order_by(ServiceProvider.display_name).all()
    return render_template("pm/service_costs/providers/list.html",
        providers=providers,
        provider_types=PROVIDER_TYPES,
    )


@service_costs_bp.route("/providers/new", methods=["GET", "POST"])
@login_required
def provider_create():
    if request.method == "POST":
        name = request.form.get("name", "")
        display_name = dict(PROVIDER_TYPES).get(name, name)

        creds = _extract_credentials(name)

        provider = ServiceProvider(
            name=name,
            display_name=display_name,
            credentials_json=json.dumps(creds),
        )
        db.session.add(provider)
        db.session.commit()
        flash(f"{display_name} provider added.", "success")
        return redirect(url_for("service_costs.providers_list"))

    return render_template("pm/service_costs/providers/form.html",
        provider_types=PROVIDER_TYPES,
        editing=False,
        provider=None,
    )


@service_costs_bp.route("/providers/<int:id>/edit", methods=["GET", "POST"])
@login_required
def provider_edit(id):
    provider = db.session.get(ServiceProvider, id) or abort(404)

    if request.method == "POST":
        creds = _extract_credentials(provider.name)
        provider.credentials_json = json.dumps(creds)
        provider.is_active = "is_active" in request.form
        db.session.commit()
        flash(f"{provider.display_name} updated.", "success")
        return redirect(url_for("service_costs.providers_list"))

    creds = json.loads(provider.credentials_json) if provider.credentials_json else {}
    return render_template("pm/service_costs/providers/form.html",
        provider_types=PROVIDER_TYPES,
        editing=True,
        provider=provider,
        creds=creds,
    )


@service_costs_bp.route("/providers/<int:id>/delete", methods=["POST"])
@login_required
def provider_delete(id):
    provider = db.session.get(ServiceProvider, id) or abort(404)
    name = provider.display_name
    db.session.delete(provider)
    db.session.commit()
    flash(f"{name} removed.", "success")
    return redirect(url_for("service_costs.providers_list"))


@service_costs_bp.route("/providers/<int:id>/sync", methods=["POST"])
@login_required
def provider_sync(id):
    try:
        count, error = sync_provider(id)
        if error:
            flash(f"Sync error: {error}", "error")
        else:
            flash(f"Synced {count} cost entries.", "success")
    except Exception as e:
        flash(f"Sync failed: {e}", "error")
    return redirect(url_for("service_costs.providers_list"))


@service_costs_bp.route("/sync-all", methods=["POST"])
@login_required
def sync_all():
    providers = ServiceProvider.query.filter_by(is_active=True).all()
    total = 0
    errors = []
    for provider in providers:
        try:
            count, error = sync_provider(provider.id)
            if error:
                errors.append(f"{provider.display_name}: {error}")
            else:
                total += count
        except Exception as e:
            errors.append(f"{provider.display_name}: {e}")

    if errors:
        flash(f"Synced {total} entries with errors: {'; '.join(errors)}", "warning")
    else:
        flash(f"Synced {total} cost entries from {len(providers)} provider(s).", "success")
    return redirect(url_for("service_costs.service_costs_dashboard"))


# ── Mappings ────────────────────────────────────────────────


@service_costs_bp.route("/mappings")
@login_required
def mappings_list():
    provider_id = request.args.get("provider_id", "", type=str)
    query = ServiceMapping.query
    if provider_id:
        query = query.filter(ServiceMapping.provider_id == int(provider_id))
    mappings = query.order_by(ServiceMapping.created_at.desc()).all()
    providers = ServiceProvider.query.order_by(ServiceProvider.display_name).all()
    return render_template("pm/service_costs/mappings/list.html",
        mappings=mappings,
        providers=providers,
        provider_id=provider_id,
    )


@service_costs_bp.route("/mappings/new", methods=["GET", "POST"])
@login_required
def mapping_create():
    if request.method == "POST":
        provider_id = request.form.get("provider_id", type=int)
        resource_identifier = request.form.get("resource_identifier", "").strip()
        resource_label = request.form.get("resource_label", "").strip()
        client_id = request.form.get("client_id", type=int) or None
        project_id = request.form.get("project_id", type=int) or None
        split_percentage = request.form.get("split_percentage", 100.0, type=float)

        monthly_cost = request.form.get("monthly_cost", type=float) or None

        mapping = ServiceMapping(
            provider_id=provider_id,
            resource_identifier=resource_identifier,
            resource_label=resource_label or resource_identifier,
            client_id=client_id,
            project_id=project_id,
            split_percentage=split_percentage,
            monthly_cost=monthly_cost,
        )
        db.session.add(mapping)
        db.session.commit()
        flash("Mapping created.", "success")
        return redirect(url_for("service_costs.mappings_list"))

    providers = ServiceProvider.query.filter_by(is_active=True).all()
    clients = Client.query.order_by(Client.name).all()
    projects = Project.query.order_by(Project.name).all()
    return render_template("pm/service_costs/mappings/form.html",
        editing=False,
        mapping=None,
        providers=providers,
        clients=clients,
        projects=projects,
    )


@service_costs_bp.route("/mappings/<int:id>/edit", methods=["GET", "POST"])
@login_required
def mapping_edit(id):
    mapping = db.session.get(ServiceMapping, id) or abort(404)

    if request.method == "POST":
        mapping.resource_identifier = request.form.get("resource_identifier", "").strip()
        mapping.resource_label = request.form.get("resource_label", "").strip()
        mapping.client_id = request.form.get("client_id", type=int) or None
        mapping.project_id = request.form.get("project_id", type=int) or None
        mapping.split_percentage = request.form.get("split_percentage", 100.0, type=float)
        mapping.monthly_cost = request.form.get("monthly_cost", type=float) or None
        mapping.is_active = "is_active" in request.form
        db.session.commit()
        flash("Mapping updated.", "success")
        return redirect(url_for("service_costs.mappings_list"))

    providers = ServiceProvider.query.filter_by(is_active=True).all()
    clients = Client.query.order_by(Client.name).all()
    projects = Project.query.order_by(Project.name).all()
    return render_template("pm/service_costs/mappings/form.html",
        editing=True,
        mapping=mapping,
        providers=providers,
        clients=clients,
        projects=projects,
    )


@service_costs_bp.route("/mappings/<int:id>/delete", methods=["POST"])
@login_required
def mapping_delete(id):
    mapping = db.session.get(ServiceMapping, id) or abort(404)
    db.session.delete(mapping)
    db.session.commit()
    flash("Mapping deleted.", "success")
    return redirect(url_for("service_costs.mappings_list"))


# ── API: Resources for a provider ───────────────────────────


@service_costs_bp.route("/api/resources/<int:provider_id>")
@login_required
def api_provider_resources(provider_id):
    provider = db.session.get(ServiceProvider, provider_id)
    if not provider:
        return jsonify([])
    try:
        resources = list_provider_resources(provider)
        return jsonify(resources)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Dashboard data ────────────────────────────────────


@service_costs_bp.route("/api/costs-by-client")
@login_required
def api_costs_by_client():
    summary = get_cost_summary()
    return jsonify(summary["by_client"])


@service_costs_bp.route("/api/costs-by-provider")
@login_required
def api_costs_by_provider():
    summary = get_cost_summary()
    return jsonify(summary["by_provider"])
