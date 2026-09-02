import json
from datetime import datetime, timezone, date, timedelta
from types import SimpleNamespace

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, jsonify,
)
from flask_login import login_required

from models import db, Client, Project, ServiceProvider, ServiceMapping, ServiceCostEntry
from service_costs_service import (
    sync_provider, list_provider_resources, get_cost_summary,
    _record_cost_entry, _month_bounds, _find_mapping,
)


# Providers whose per-resource costs can only be entered by hand, because the
# vendor has no billing API. Kept as a list so a second such vendor is a
# one-line add rather than a hunt through templates.
MANUAL_MONTHLY_PROVIDERS = {"railway"}


def _safe_next(fallback):
    """A redirect target from ?next=, only if it stays on this admin.

    A raw redirect to whatever the URL says is an open redirect: someone can
    hand out a link that goes through the site to an outside page they own.
    Constraining to /admin/ is enough here because nothing outside the
    admin ever links back into this flow.
    """
    nxt = (request.args.get("next") or request.form.get("next") or "").strip()
    if nxt.startswith("/admin/"):
        return nxt
    return fallback


def _parse_month(raw):
    """A YYYY-MM string to the first day of that month, or today's month."""
    raw = (raw or "").strip()
    if raw:
        try:
            return date.fromisoformat(f"{raw}-01")
        except ValueError:
            pass
    return date.today().replace(day=1)


def _recent_months(count=6):
    months = []
    cursor = date.today().replace(day=1)
    for _ in range(count):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return months


def _normalize(name):
    return " ".join((name or "").split()).casefold()


def _amount_str(value):
    """A cost as the vendor writes it: 22.30, or 0.9258 when it needs it.

    Padding everything to four places turns $22.30 into 22.3000, which reads
    as a different number from the one on the vendor's screen and makes the
    column hard to scan. Trailing zeros go, but never below cents.
    """
    if value is None:
        return ""
    trimmed = f"{value:.4f}".rstrip("0")
    whole, _, frac = trimmed.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def _historical_label(provider, resource_id):
    """The best readable name for a resource the vendor no longer lists.

    A mapping's label first, then the label typed on the last manual entry,
    then the raw id. The raw id is a UUID for Railway, so falling straight to
    it would make an old row both unreadable and unmatchable by name.
    """
    m = ServiceMapping.query.filter_by(
        provider_id=provider.id, resource_identifier=resource_id
    ).first()
    if m and m.resource_label:
        return m.resource_label

    entry = (ServiceCostEntry.query
             .filter_by(provider_id=provider.id, resource_identifier=resource_id)
             .filter(ServiceCostEntry.raw_data_json.isnot(None))
             .order_by(ServiceCostEntry.period_start.desc()).first())
    if entry:
        try:
            label = (json.loads(entry.raw_data_json) or {}).get("label")
        except (json.JSONDecodeError, TypeError):
            label = None
        if label:
            return label
    return resource_id


def _project_name_index():
    """Projects keyed by normalized name, with ambiguous names dropped.

    Two projects sharing a name cannot be told apart from a vendor's project
    name alone. An unattributed cost is a small problem; one confidently
    billed to the wrong client is a much worse one, so a collision is left
    for a human rather than guessed at.
    """
    index = {}
    for p in Project.query.all():
        key = _normalize(p.name)
        index[key] = None if key in index else p
    return {k: v for k, v in index.items() if v is not None}

service_costs_bp = Blueprint("service_costs", __name__, url_prefix="/admin/service-costs")

PROVIDER_TYPES = [
    ("aws", "Amazon Web Services"),
    ("railway", "Railway"),
    ("twilio", "Twilio"),
    ("cloudflare", "Cloudflare"),
    # Anything that bills a fixed amount and offers no API to ask about it.
    # Anthropic is the first, and there will be more: a display name and a
    # billing day are supplied on the form rather than fixed by the type.
    ("flat", "Flat monthly (no API)"),
    # Uses the app's own STRIPE_SECRET_KEY, so there is nothing to enter
    # and no second copy of the key to leak or rotate.
    ("stripe", "Stripe (processing fees)"),
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


def _billing_day():
    """Day of the month a flat provider is charged, or None."""
    raw = (request.form.get("billing_day") or "").strip()
    if not raw:
        return None
    try:
        return min(31, max(1, int(raw)))
    except ValueError:
        return None


def _monthly_cost(provider_name=None):
    """The flat monthly figure, or None when the field is left blank.

    None and 0 mean different things here: None is "this vendor reports its
    own spend", 0 would be "this vendor costs nothing", and storing the second
    when the user meant the first books a zero every month.

    Always None for a manual-monthly vendor. Railway spent months booked as a
    flat twenty because a number sat in this field: it charged a different
    amount every month, spread across a dozen projects, and a single unallocated
    line of the same size forever was wrong in the total and useless per client.
    Those vendors get their real numbers from the Monthly Costs page, so this
    field has nothing left to mean for them and refusing it here is what stops
    it coming back.
    """
    if provider_name in MANUAL_MONTHLY_PROVIDERS:
        return None
    raw = (request.form.get("monthly_cost") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


# ── Dashboard ───────────────────────────────────────────────


@service_costs_bp.route("/")
@login_required
def service_costs_dashboard():
    """Kept as a redirect.

    Service costs are not a page any more. A vendor charge writes an expense,
    so it is a row in the expense ledger like everything else that went out,
    and the vendor breakdown is a way of reading that ledger rather than a
    second one beside it. This route still exists because bookmarks, the Sync
    All redirect and the provider and mapping pages all point at it, and a dead
    link is a worse answer than a hop.
    """
    return redirect(url_for("pm.expenses_list"))


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
        if name == "flat":
            # "Flat monthly (no API)" is a category, not a vendor. Several of
            # these will exist and they need telling apart.
            display_name = (request.form.get("display_name") or "").strip() or "Flat monthly"

        creds = _extract_credentials(name)

        provider = ServiceProvider(
            name=name,
            display_name=display_name,
            credentials_json=json.dumps(creds),
            monthly_cost=_monthly_cost(name),
            billing_day=_billing_day(),
        )
        db.session.add(provider)
        db.session.commit()
        flash(f"{display_name} provider added.", "success")
        return redirect(url_for("service_costs.providers_list"))

    return render_template("pm/service_costs/providers/form.html",
        provider_types=PROVIDER_TYPES,
        editing=False,
        provider=None,
        manual_monthly=sorted(MANUAL_MONTHLY_PROVIDERS),
    )


@service_costs_bp.route("/providers/<int:id>/edit", methods=["GET", "POST"])
@login_required
def provider_edit(id):
    provider = db.session.get(ServiceProvider, id) or abort(404)

    if request.method == "POST":
        creds = _extract_credentials(provider.name)
        provider.credentials_json = json.dumps(creds)
        provider.monthly_cost = _monthly_cost(provider.name)
        provider.billing_day = _billing_day()
        if provider.name == "flat":
            provider.display_name = (
                (request.form.get("display_name") or "").strip() or provider.display_name
            )
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
        manual_monthly=sorted(MANUAL_MONTHLY_PROVIDERS),
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
        return redirect(_safe_next(url_for("service_costs.mappings_list")))

    # A monthly page linking a row's "Map" action passes the ids it already
    # knows on the query string. Handing them through as a synthetic mapping
    # keeps the template one shape rather than two.
    prefill = None
    prefill_pid = request.args.get("provider_id", type=int)
    prefill_rid = (request.args.get("resource_identifier") or "").strip()
    if prefill_pid or prefill_rid:
        prefill = SimpleNamespace(
            provider_id=prefill_pid,
            resource_identifier=prefill_rid,
            resource_label=(request.args.get("resource_label") or "").strip(),
            client_id=None,
            project_id=None,
            split_percentage=100.0,
            monthly_cost=None,
            is_active=True,
        )

    providers = ServiceProvider.query.filter_by(is_active=True).all()
    clients = Client.query.order_by(Client.name).all()
    projects = Project.query.order_by(Project.name).all()
    return render_template("pm/service_costs/mappings/form.html",
        editing=False,
        mapping=prefill,
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


# ── Manual monthly entry ────────────────────────────────────


@service_costs_bp.route("/providers/<int:id>/monthly", methods=["GET", "POST"])
@login_required
def provider_monthly(id):
    """Enter what a vendor's resources actually cost this month.

    Railway is the case that made this: the API will not report money, so once
    a month the numbers get copied off the Railway usage screen. One input per
    project, saving upserts a ServiceCostEntry keyed on the calendar month and
    the resource so a second save this month corrects rather than doubles.
    """
    provider = db.session.get(ServiceProvider, id) or abort(404)
    target = _parse_month(request.args.get("month") or request.form.get("month"))
    p_start, p_end = _month_bounds(target)

    if request.method == "POST":
        _save_monthly_entries(provider, p_start, p_end)
        flash(f"{provider.display_name} costs for {p_start:%b %Y} saved.", "success")
        return redirect(url_for("service_costs.provider_monthly",
                                id=id, month=p_start.strftime("%Y-%m")))

    # Row set: live resources from the vendor, plus any resource_id that has
    # ever been billed against this provider so a project deleted from Railway
    # after the fact is still editable in its historical months.
    try:
        live = list_provider_resources(provider)
    except Exception:
        live = []
    seen = {r["id"] for r in live}

    historical = (
        db.session.query(ServiceCostEntry.resource_identifier)
        .filter_by(provider_id=provider.id).distinct().all()
    )
    for (rid,) in historical:
        if rid in seen:
            continue
        # "historical" is a flag, not part of the name. Appending it to the
        # label pushed the actual project name out of a truncated row, which
        # is the one thing the row has to show.
        live.append({"id": rid, "label": _historical_label(provider, rid),
                     "historical": True})
        seen.add(rid)

    # Pre-fill: the raw amount is what was typed last time this month was
    # saved. Sum across mappings when a resource is split, so the input shows
    # the bill total rather than one client's share.
    prefill_by_rid = {}
    for e in ServiceCostEntry.query.filter_by(
        provider_id=provider.id, period_start=p_start, period_end=p_end,
    ).all():
        # Multiple entries per resource can exist when a resource is split
        # across mappings. raw_amount is the same on each (the bill total),
        # so picking one is right, not summing.
        prefill_by_rid.setdefault(e.resource_identifier, e.raw_amount)

    mappings_by_rid = {}
    for m in provider.mappings:
        mappings_by_rid.setdefault(m.resource_identifier, []).append(m)

    # An unmapped resource whose name matches a project exactly is almost
    # certainly that project, since the vendor's project names were renamed
    # to line up for this reason. Offered, never applied silently.
    by_name = _project_name_index()

    rows = []
    for r in live:
        existing = mappings_by_rid.get(r["id"], [])
        suggestion = None
        if not existing:
            suggestion = by_name.get(_normalize(r["label"]))
        amount = prefill_by_rid.get(r["id"])
        rows.append({
            "id": r["id"],
            "label": r["label"],
            "historical": r.get("historical", False),
            "amount": amount,
            "amount_str": _amount_str(amount),
            "mappings": existing,
            "suggestion": suggestion,
        })
    rows.sort(key=lambda r: (r["amount"] is None, -(r["amount"] or 0), r["label"].lower()))

    total = sum(r["amount"] or 0 for r in rows)
    suggested = [r for r in rows if r["suggestion"]]

    return render_template("pm/service_costs/monthly.html",
        provider=provider,
        rows=rows,
        month=p_start,
        recent_months=_recent_months(),
        total=total,
        suggested=suggested,
    )


@service_costs_bp.route("/providers/<int:id>/monthly/automap", methods=["POST"])
@login_required
def provider_automap(id):
    """Create mappings for resources whose name matches a project exactly.

    Acts only on the pairs the page submitted, so what happens is what was
    on screen when the button was pressed rather than whatever the vendor's
    API says a second later. Skips any resource that has picked up a mapping
    in the meantime.
    """
    provider = db.session.get(ServiceProvider, id) or abort(404)
    month = _parse_month(request.form.get("month"))

    created = 0
    for key, raw_pid in request.form.items():
        if not key.startswith("map:"):
            continue
        rid = key[4:]
        project = db.session.get(Project, int(raw_pid)) if raw_pid.isdigit() else None
        if project is None:
            continue
        if ServiceMapping.query.filter_by(
            provider_id=provider.id, resource_identifier=rid
        ).first():
            continue
        db.session.add(ServiceMapping(
            provider_id=provider.id,
            resource_identifier=rid,
            resource_label=project.name,
            client_id=project.client_id,
            project_id=project.id,
            split_percentage=100.0,
            is_active=True,
        ))
        created += 1

    db.session.commit()
    flash(f"Mapped {created} resource{'' if created == 1 else 's'} by name.", "success")
    return redirect(url_for("service_costs.provider_monthly",
                            id=id, month=month.strftime("%Y-%m")))


def _save_monthly_entries(provider, p_start, p_end):
    """Upsert one ServiceCostEntry per submitted resource, delete on blank/0.

    The form submits `amt:<resource_id>` for every row shown. A number > 0
    upserts through _record_cost_entry, which already handles the per-mapping
    split. A blank or 0 removes the entry and its Expense for this month, so
    a mistaken save is not one-way.

    Also clears the legacy `railway:account` unallocated row for this month
    if present, so the old flat booking is not left doubling up under a
    per-project entry set.
    """
    labels = {}
    submitted = {}
    for key, val in request.form.items():
        if key.startswith("amt:"):
            submitted[key[4:]] = (val or "").strip()
        elif key.startswith("lbl:"):
            labels[key[4:]] = (val or "").strip()

    for rid, raw in submitted.items():
        label = labels.get(rid, rid) or rid
        amt = None
        if raw:
            try:
                amt = float(raw)
            except ValueError:
                amt = None

        if amt is None or amt <= 0:
            _delete_entries_for(provider, rid, p_start, p_end)
            continue

        # The typed label is kept on the entry so a resource the vendor's API
        # stops listing still shows its name in later months, instead of
        # falling back to a raw id nobody can read or name-match.
        # Four places, because that is what Railway reports and what gets
        # typed in. The expense that comes off this still rounds to cents;
        # keeping the raw figure exact is what lets the field round-trip the
        # number instead of showing back something the vendor never said.
        _record_cost_entry(
            provider, rid, p_start, p_end, round(amt, 4),
            f"{provider.display_name} - {label}",
            {"source": "manual", "label": label},
        )
        _prune_stale_allocations(provider, rid, p_start, p_end)

    # A month that used to be booked as one flat "Railway (Aug 2026)" row and
    # is now being restated as per-project entries has to lose the flat one,
    # or the total for the month reads as double.
    if provider.name == "railway":
        _delete_entries_for(provider, "railway:account", p_start, p_end)

    db.session.commit()


def _discard_entry(entry):
    """Remove a cost entry and the expense it created.

    An expense that has been put on an invoice is left alone and merely
    detached. Deleting it would silently change an invoice that has already
    gone to a client, which is a worse outcome than an orphan row.
    """
    expense = entry.expense
    if expense is not None and not expense.invoice_line_items:
        db.session.delete(expense)
    entry.expense_id = None
    db.session.delete(entry)


def _delete_entries_for(provider, resource_id, p_start, p_end):
    for e in ServiceCostEntry.query.filter_by(
        provider_id=provider.id,
        resource_identifier=resource_id,
        period_start=p_start,
        period_end=p_end,
    ).all():
        _discard_entry(e)


def _prune_stale_allocations(provider, resource_id, p_start, p_end):
    """Drop rows for an allocation that no longer exists.

    mapping_id is part of the cost entry's unique key, so a resource that was
    unallocated when it was first entered keeps that no-mapping row forever.
    Map it to a client afterwards and the next save writes a second row
    beside the first rather than replacing it, and the month reads double.
    Same story when a mapping is deleted and its row is left behind.
    """
    valid = {m.id for m in _find_mapping(provider.id, resource_id)}
    for e in ServiceCostEntry.query.filter_by(
        provider_id=provider.id,
        resource_identifier=resource_id,
        period_start=p_start,
        period_end=p_end,
    ).all():
        if e.mapping_id in valid:
            continue
        # Nothing to prune when the resource has no mappings at all: the
        # no-mapping row is then the correct and only row.
        if valid or e.mapping_id is not None:
            _discard_entry(e)


def months_missing_manual_costs(providers, lookback=1):
    """Which of the given providers have no entries for recent past months.

    Returns [(provider, month_start), ...] for months where a manual-entry
    provider has zero cost entries. Feeds the nudge banner on Expenses.
    """
    out = []
    today = date.today().replace(day=1)
    for provider in providers:
        if provider.name not in MANUAL_MONTHLY_PROVIDERS:
            continue
        for i in range(1, lookback + 1):
            month = today
            for _ in range(i):
                month = (month - timedelta(days=1)).replace(day=1)
            p_start, p_end = _month_bounds(month)
            exists = db.session.query(ServiceCostEntry.id).filter_by(
                provider_id=provider.id, period_start=p_start, period_end=p_end,
            ).first()
            if not exists:
                out.append((provider, p_start))
    return out
