import json
from datetime import datetime, timezone, date, timedelta
from types import SimpleNamespace

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    abort, jsonify,
)

from models import (db, Client, Project, ServiceProvider, ServiceMapping,
                    ServiceCostEntry, ProviderInvoice)
from service_costs_service import (
    discard_entry as _discard_entry, prune_stale_allocations as _prune_stale_allocations,
    sync_provider, list_provider_resources, get_cost_summary, railway_token,
    _record_cost_entry, _month_bounds, _find_mapping,
)
import provider_bills
# Vendors recorded month by month (provider_bills says why). Imported here as
# well because the expenses page and the door read it from this module.
from provider_bills import MANUAL_MONTHLY_PROVIDERS  # noqa: F401
from pm.users_routes import ceo_required

# The row that catches everything the vendor's per-project screen does not
# account for, so a month can reconcile to the invoice instead of to the sum of
# its projects. Three things land here and all of them are real money:
#
#   the plan or seat fee, which is a cost of being in business rather than a
#   cost of any one client; usage by projects since deleted, which Railway
#   reports as a single figure with no owner; and whole months from before the
#   per-project breakdown was being kept, where the invoice total is all there
#   is.
#
# Deliberately unallocatable. Splitting a seat fee across clients would bill
# them for the privilege of being hosted alongside each other.
OTHER_LABEL = "Not broken down"


def _other_resource(provider):
    return f"{provider.name}:other"


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


@service_costs_bp.context_processor
def _hosting_tabs():
    """Every page here is a tab of Hosting (or a form under one), so its tab
    row's counts are on hand; asked only by the templates that draw it."""
    from pm.hosting_routes import tab_counts
    return {"hosting_counts": tab_counts}

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
        # The workspace says which Railway account's bills this provider books;
        # two providers can hold the same account token (Built by Bean's
        # workspace and EntertainHQ's, one login).
        return {"api_token": request.form.get("railway_api_token", "").strip(),
                "workspace_id": request.form.get("railway_workspace_id", "").strip()}
    elif name == "twilio":
        # An API key made on the account (Twilio's own advice, and the
        # playbook's) is the way in; the main auth token still works for an
        # account set up before, and is what Twilio's Auth Token rotation breaks.
        return {
            "account_sid": request.form.get("twilio_account_sid", "").strip(),
            "api_key_sid": request.form.get("twilio_api_key_sid", "").strip(),
            "api_key_secret": request.form.get("twilio_api_key_secret", "").strip(),
            "auth_token": request.form.get("twilio_auth_token", "").strip(),
        }
    elif name == "cloudflare":
        return {
            "api_token": request.form.get("cf_api_token", "").strip(),
            "account_id": request.form.get("cf_account_id", "").strip(),
        }
    return {}


# A saved secret is never drawn back into a page (the form wrote the auth
# token into the HTML as an input's value until 2026-11-05). A field left
# blank on edit keeps what was saved.
SECRET_FIELDS = ("aws_secret_access_key", "api_token", "auth_token", "api_key_secret")


def _keep_secrets(creds, saved):
    for k in SECRET_FIELDS:
        if k in creds and not creds[k] and saved.get(k):
            creds[k] = saved[k]
    return creds


def _account_client_id():
    """Whose account the credentials open, or None for Built by Bean's own.
    The Billed to picker carries a client as its id and a company as "b:<id>"."""
    raw = (request.form.get("account_client_id") or "").strip()
    if not raw or raw.startswith("b:"):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _account_business_id():
    """Another of Michael's companies that pays for the account, or None."""
    raw = (request.form.get("account_client_id") or "").strip()
    if not raw.startswith("b:"):
        return None
    try:
        return int(raw[2:])
    except ValueError:
        return None


def _payer_choices():
    """Billed to: Built by Bean, the other companies, then the clients."""
    import books_service
    from models import Business
    home = books_service.board_business()
    companies = [b for b in Business.query.filter(Business.parent_id.is_(None)).order_by(Business.name).all()
                 if not home or b.id != home.id]
    return ([["", "Built by Bean (my own card)"]]
            + [[f"b:{b.id}", f"{b.name} (its own card)"] for b in companies]
            + [[c.id, f"{c.name} (their card)"] for c in Client.query.order_by(Client.name).all()])


def _reconcile_ownership(provider):
    """Make the ledger agree with whose account this turned out to be.

    Waiting for the nightly sync would leave a client's spending sitting in
    Michael's ledger until tomorrow, and the whole point of the setting is the
    number it takes out of his totals today. Returns how many expenses moved.
    """
    from service_costs_service import _drop_expense, _sync_expense, writes_expenses
    touched = 0
    for entry in provider.cost_entries.all():
        # Who the cost is attributed to moves with the account, so the row
        # stops reading "[unallocated]" the moment there is somebody it plainly
        # belongs to. Without this it kept the label it was written with until
        # the next nightly sync happened to rewrite it.
        base = (entry.description or "").replace(" [unallocated]", "")
        attributed = ((entry.mapping.client_id if entry.mapping else None)
                      or provider.account_client_id)
        entry.description = base if attributed else base + " [unallocated]"
        if not writes_expenses(provider):
            if entry.expense_id:
                _drop_expense(entry)
                touched += 1
        elif entry.expense_id is None:
            _sync_expense(entry, entry.mapping)
            touched += 1
    db.session.commit()
    return touched


def _prefill():
    """What a link to Add account fills in, so a session that has found the
    account opens the form with everything but the key typed (Michael,
    2026-11-05: get me to the page, or do it). Only known types, payers from
    the picker's own list, and an id shaped like Twilio's: nothing here is
    written into the page unless it is one of those."""
    import re
    name = request.args.get("type", "")
    payer = request.args.get("billed_to", "")
    sid = request.args.get("sid", "")
    return {
        "name": name if name in dict(PROVIDER_TYPES) else "",
        "payer": payer if payer in {str(v) for v, _ in _payer_choices()} else "",
        "account_sid": sid if re.fullmatch(r"AC[0-9a-f]{32}", sid) else "",
        "vendor": (request.args.get("vendor", "") if re.fullmatch(r"[\w .&'-]{1,60}", request.args.get("vendor", "")) else ""),
    }


def _try_key(provider):
    """A Twilio account is read the moment its key is saved, so the press
    says whether the key works rather than tomorrow's night. A note for the
    flash, in the page's own words."""
    if provider.name != "twilio" or not provider.is_active:
        return ""
    import vendor_discovery
    count, error = sync_provider(provider.id)
    if error:
        return " " + (vendor_discovery.plain_error(provider) or error)
    label = f" ({provider.account_label})" if provider.account_label else ""
    return f" Twilio answered{label}: {count} cost entr{'ies' if count != 1 else 'y'} this month."


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
    when the user meant the first records a zero every month.

    Always None for a by-the-month vendor. Railway spent months recorded as a
    flat twenty because a number sat in this field: it charged a different
    amount every month, spread across a dozen projects, and a single unallocated
    line of the same size forever was wrong in the total and useless per client.
    Its real numbers come from its bills, pulled with an account token or typed
    on the Railway months tab of Hosting, so this field has nothing left to
    mean for it and refusing it here is what stops it coming back.
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
@ceo_required
def service_costs_dashboard():
    """The old Service costs address, for bookmarks only: nothing on the board
    links here any more. The vendor pages are tabs of Hosting now (Fees,
    Mappings, Railway months, Vendors; docs/finances_plan.md item 9), so the
    old front door opens Hosting. Gated like the pages, so a redirect is never
    a way round the gate."""
    return redirect(url_for("hosting.hosting_index"), code=301)


# ── Providers ───────────────────────────────────────────────


def invoice_for(provider_id, month_start):
    """The recorded invoice for one provider and month, or None."""
    return ProviderInvoice.query.filter_by(
        provider_id=provider_id, period_month=month_start).first()


def _save_invoice(provider, month_start):
    """The single number the vendor actually charged for this month.

    Separate from the per-resource entries on purpose. Those say how to SPLIT
    a month between clients; this says what the month cost. Deriving the
    second from the first is what read $231.65 against $136.90 of real
    invoices, because two different things were writing rows that both looked
    like Railway spend.

    Blank removes it, the same way a blank resource amount does, so a wrong
    number can be walked back rather than only overwritten.
    """
    raw = (request.form.get("invoice_amount") or "").strip()
    raw = raw.replace(",", "").replace("$", "").strip()
    row = invoice_for(provider.id, month_start)
    if raw == "":
        if row:
            db.session.delete(row)
        return None
    try:
        amount = float(raw)
    except ValueError:
        return "That invoice amount is not a number."
    if amount < 0:
        return "An invoice cannot be negative."
    if row is None:
        row = ProviderInvoice(provider_id=provider.id, period_month=month_start)
        db.session.add(row)
    row.amount = round(amount, 2)
    return None


@service_costs_bp.route("/providers")
@ceo_required
def providers_list():
    """Vendors has its own page now (Michael, 2026-11-05: "it doesnt even
    make sense to be there"). The old address lands on it."""
    return redirect(url_for("vendors.index", **request.args), 301)


# Vendors: its own Finances page, one tile per vendor with its accounts under
# it (vendor_discovery.groups). The endpoint lives here because every form and
# press for an account is this blueprint's.
vendors_bp = Blueprint("vendors", __name__, url_prefix="/admin/vendors")
VENDOR_VIEWS = (("in_use", "In use"), ("not_in_use", "Not in use"))


@vendors_bp.route("/")
@ceo_required
def index():
    import vendor_discovery
    view = request.args.get("view") or "in_use"
    view = view if view in dict(VENDOR_VIEWS) else "in_use"
    every = vendor_discovery.groups(ServiceProvider.query.order_by(ServiceProvider.display_name).all())
    counts = {"in_use": sum(1 for g in every if g["in_use"]),
              "not_in_use": sum(1 for g in every if not g["in_use"])}
    shown = [g for g in every if g["in_use"] == (view == "in_use")]
    return render_template("pm/service_costs/providers/list.html",
        groups=shown, view=view, views=VENDOR_VIEWS, counts=counts,
        provider_types=PROVIDER_TYPES)


@service_costs_bp.route("/providers/new", methods=["GET", "POST"])
@ceo_required
def provider_create():
    if request.method == "POST":
        name = request.form.get("name", "")
        display_name = dict(PROVIDER_TYPES).get(name, name)
        if name == "flat":
            # "Flat monthly (no API)" is a category, not a vendor. Several of
            # these will exist and they need telling apart.
            display_name = (request.form.get("display_name") or "").strip() or "Flat monthly"

        creds = _extract_credentials(name)

        import vendor_discovery
        provider = ServiceProvider(
            name=name,
            display_name=display_name,
            vendor=(request.form.get("vendor") or "").strip()[:100] or vendor_discovery.bare(display_name),
            credentials_json=json.dumps(creds),
            monthly_cost=_monthly_cost(name),
            billing_day=_billing_day(),
            account_client_id=_account_client_id(),
            account_business_id=_account_business_id(),
        )
        db.session.add(provider)
        db.session.flush()
        import vendor_discovery
        vendor_discovery.replace_found(provider)
        db.session.commit()
        note = _try_key(provider)
        flash(f"{display_name} account added.{note}", "warning" if "turned" in note or "did not" in note else "success")
        return redirect(url_for("vendors.index"))

    return render_template("pm/service_costs/providers/form.html",
        provider_types=PROVIDER_TYPES,
        editing=False,
        provider=None,
        prefill=_prefill(),
        manual_monthly=sorted(MANUAL_MONTHLY_PROVIDERS),
        payer_choices=_payer_choices(),
    )


@service_costs_bp.route("/providers/<int:id>/edit", methods=["GET", "POST"])
@ceo_required
def provider_edit(id):
    provider = db.session.get(ServiceProvider, id) or abort(404)

    if request.method == "POST":
        saved = json.loads(provider.credentials_json) if provider.credentials_json else {}
        creds = _keep_secrets(_extract_credentials(provider.name), saved)
        provider.credentials_json = json.dumps(creds)
        provider.monthly_cost = _monthly_cost(provider.name)
        provider.billing_day = _billing_day()
        if provider.name == "flat":
            provider.display_name = (
                (request.form.get("display_name") or "").strip() or provider.display_name
            )
        provider.is_active = "is_active" in request.form
        provider.vendor = (request.form.get("vendor") or "").strip()[:100] or provider.vendor
        was = (provider.account_client_id, provider.account_business_id)
        provider.account_client_id = _account_client_id()
        provider.account_business_id = _account_business_id()
        db.session.commit()
        note = ""
        if (provider.account_client_id, provider.account_business_id) != was:
            # Only an expense this vendor wrote before the bank took over (and
            # Stripe's fees, which never cross a bank) can move here; a bank
            # line's expense stays with the bank line.
            moved = _reconcile_ownership(provider)
            if provider.account_client_id and moved:
                who = provider.account_client.name if provider.account_client else "the client"
                note = (f" {moved} charge{'s' if moved != 1 else ''} came off your ledger: "
                        f"that account is on {who}'s card.")
            elif moved:
                note = f" {moved} charge{'s' if moved != 1 else ''} back on your ledger."
        # A Railway account that can read its own bills pulls them on the
        # press, so the months it fills are there before anybody looks again.
        if provider.name == "railway" and creds.get("workspace_id") and railway_token(creds):
            count, error = sync_provider(provider.id)
            note += (f" Railway could not be read: {error}" if error
                     else f" Bills pulled from Railway, {count} project entr{'ies' if count != 1 else 'y'} written.")
        if provider.name == "twilio":
            note += _try_key(provider)
        flash(f"{provider.display_name} updated.{note}",
              "success" if not any(w in note for w in ("could not", "turned", "did not")) else "warning")
        return redirect(url_for("vendors.index"))

    creds = json.loads(provider.credentials_json) if provider.credentials_json else {}
    return render_template("pm/service_costs/providers/form.html",
        provider_types=PROVIDER_TYPES,
        editing=True,
        provider=provider,
        creds=creds,
        manual_monthly=sorted(MANUAL_MONTHLY_PROVIDERS),
        payer_choices=_payer_choices(),
    )


@service_costs_bp.route("/providers/<int:id>/delete", methods=["POST"])
@ceo_required
def provider_delete(id):
    provider = db.session.get(ServiceProvider, id) or abort(404)
    name = provider.display_name
    db.session.delete(provider)
    db.session.commit()
    flash(f"{name} removed.", "success")
    return redirect(url_for("vendors.index"))


@service_costs_bp.route("/providers/<int:id>/sync", methods=["POST"])
@ceo_required
def provider_sync(id):
    try:
        count, error = sync_provider(id)
        if error:
            flash(f"Sync error: {error}", "error")
        else:
            flash(f"Synced {count} cost entries.", "success")
    except Exception as e:
        flash(f"Sync failed: {e}", "error")
    return redirect(url_for("vendors.index"))


@service_costs_bp.route("/sync-all", methods=["POST"])
@ceo_required
def sync_all():
    providers = ServiceProvider.query.filter_by(is_active=True).all()
    total = 0
    errors = []
    import vendor_discovery
    for provider in providers:
        try:
            count, error = sync_provider(provider.id)
            if error:
                # In words a person can act on, as the page says it.
                errors.append(vendor_discovery.plain_error(provider) or f"{provider.display_name}: {error}")
            else:
                total += count
        except Exception as e:
            errors.append(f"{provider.display_name}: {e}")

    # The night's bank half too, so a vendor the bank pays is on the page
    # after the press rather than after tonight (vendor_discovery).
    found = []
    try:
        found = [line for line in vendor_discovery.from_bank() if "found on the bank" in line]
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        errors.append(f"Finding vendors on the bank failed: {e}")
    more = f" Found {len(found)} new vendor account{'s' if len(found) != 1 else ''} on the bank." if found else ""
    if errors:
        flash(f"Synced {total} entries.{more} {' '.join(errors)}", "warning")
    else:
        flash(f"Synced {total} cost entries from {len(providers)} account(s).{more}", "success")
    # Back to the page it was pressed on (the Vendors tab, or the Books page
    # that carries the vendors), never the retired Service costs address.
    return redirect(_safe_next(url_for("vendors.index")))


# ── Mappings ────────────────────────────────────────────────


@service_costs_bp.route("/mappings")
@ceo_required
def mappings_list():
    provider_id = request.args.get("provider_id", type=int) or ""
    query = ServiceMapping.query
    if provider_id:
        query = query.filter(ServiceMapping.provider_id == provider_id)
    mappings = query.order_by(ServiceMapping.created_at.desc()).all()
    providers = ServiceProvider.query.order_by(ServiceProvider.display_name).all()
    return render_template("pm/service_costs/mappings/list.html",
        mappings=mappings,
        providers=providers,
        provider_id=provider_id,
    )


@service_costs_bp.route("/mappings/new", methods=["GET", "POST"])
@ceo_required
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
    # Hosting's "Map it" on a priced project with no mapping names the
    # project, so the form opens with it and its client already chosen.
    prefill_project = db.session.get(Project, request.args.get("project_id", type=int) or 0)
    if prefill_pid or prefill_rid or prefill_project:
        prefill = SimpleNamespace(
            provider_id=prefill_pid,
            resource_identifier=prefill_rid,
            resource_label=(request.args.get("resource_label") or "").strip(),
            client_id=prefill_project.client_id if prefill_project else None,
            project_id=prefill_project.id if prefill_project else None,
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
@ceo_required
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
@ceo_required
def mapping_delete(id):
    mapping = db.session.get(ServiceMapping, id) or abort(404)
    db.session.delete(mapping)
    db.session.commit()
    flash("Mapping deleted.", "success")
    # Back to the filtered page it was pressed on, not every provider.
    nxt = request.form.get("next") or ""
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("service_costs.mappings_list"))


# ── API: Resources for a provider ───────────────────────────


@service_costs_bp.route("/api/resources/<int:provider_id>")
@ceo_required
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
@ceo_required
def api_costs_by_client():
    summary = get_cost_summary()
    return jsonify(summary["by_client"])


@service_costs_bp.route("/api/costs-by-provider")
@ceo_required
def api_costs_by_provider():
    summary = get_cost_summary()
    return jsonify(summary["by_provider"])


# ── A vendor's month: Railway months ────────────────────────


def _railway_providers():
    """Every Railway account, Built by Bean's own first (the tab opens on it),
    then by name. Inactive ones too: their months are still correctable."""
    rows = ServiceProvider.query.filter_by(name="railway").all()
    return sorted(rows, key=lambda p: (not p.is_ours, not p.is_active,
                                       (p.display_name or "").casefold(), p.id))


def _last_finished_month():
    return (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)


def _month_choices(providers):
    """Every month a bill could be recorded for, newest first: from the
    earliest any of these accounts has a cost or a bill (at least a year
    back) to the month in progress. One list for every account, so changing
    the account keeps the month that was picked."""
    this_month = date.today().replace(day=1)
    first = this_month
    for _ in range(11):
        first = (first - timedelta(days=1)).replace(day=1)
    ids = [p.id for p in providers]
    if ids:
        for column, model in ((ServiceCostEntry.period_start, ServiceCostEntry),
                              (ProviderInvoice.period_month, ProviderInvoice)):
            earliest = (db.session.query(db.func.min(column))
                        .filter(model.provider_id.in_(ids)).scalar())
            if earliest and earliest.replace(day=1) < first:
                first = earliest.replace(day=1)
    months = provider_bills.month_starts(first, this_month) + [this_month]
    return list(reversed(months))


def _month_context(provider, target):
    """Everything the month page draws for one vendor and one month."""
    p_start, p_end = _month_bounds(target)

    # Row set: live resources from the vendor, plus any resource_id that has
    # ever been billed against this provider so a project deleted from Railway
    # after the fact is still editable in its historical months.
    try:
        live = list_provider_resources(provider)
    except Exception:
        live = []
    other_id = _other_resource(provider)
    seen = {r["id"] for r in live} | {other_id}

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
    # Suggestions are read before the catch-all is appended, so it can never be
    # offered a project to map to.
    suggested = [r for r in rows if r["suggestion"]]

    # Pinned last whatever it holds. It is the remainder, and a remainder that
    # sorted itself to the top by being the largest number would read as the
    # most important line on the page.
    other_amount = prefill_by_rid.get(other_id)
    rows.append({
        "id": other_id,
        "label": OTHER_LABEL,
        "historical": False,
        "amount": other_amount,
        "amount_str": _amount_str(other_amount),
        "mappings": [],
        "suggestion": None,
        "is_other": True,
    })

    return dict(
        provider=provider,
        rows=rows,
        month=p_start,
        total=sum(r["amount"] or 0 for r in rows),
        suggested=suggested,
        other_id=other_id,
        invoice=invoice_for(provider.id, p_start),
    )


def month_url(provider, month):
    """Where one vendor's month lives: a Railway account's on the Railway
    months tab, any other vendor's on its own address."""
    key = month.strftime("%Y-%m")
    if provider.name == "railway":
        return url_for("service_costs.railway_months", provider=provider.id, month=key)
    return url_for("service_costs.provider_monthly", id=provider.id, month=key)


@service_costs_bp.route("/railway")
@ceo_required
def railway_months():
    """The Railway months tab of Hosting: pick the account and the month, and
    correct what each project cost and what the bill was.

    A Railway account that names its workspace fills its months itself
    (service_costs_service._sync_railway); one that does not is typed here off
    Railway's usage screen. Either way the month's rows are how the bank's
    Railway charge splits across projects (bank_feed.split): only the bank
    line is an expense. The account and month are the query string, so the bar
    over the page applies itself (liveFilter) and only the month swaps."""
    providers = _railway_providers()
    bills = provider_bills.missing_bills()
    if not providers:
        return render_template("pm/service_costs/monthly.html", provider=None,
                               railway=True, providers=[], bills=bills)
    wanted = request.args.get("provider", type=int)
    provider = next((p for p in providers if p.id == wanted), providers[0])
    target = (_parse_month(request.args["month"]) if request.args.get("month")
              else _last_finished_month())
    missing = {m for b in bills if b["provider"].id == provider.id for m in b["missing"]}
    month_opts = [(m.strftime("%Y-%m"), m.strftime("%b %Y") + (" (no bill)" if m in missing else ""))
                  for m in _month_choices(providers)]
    return render_template("pm/service_costs/monthly.html", railway=True,
                           providers=providers, bills=bills, month_opts=month_opts,
                           month_url=month_url,
                           **_month_context(provider, target))


@service_costs_bp.route("/providers/<int:id>/monthly", methods=["GET", "POST"])
@ceo_required
def provider_monthly(id):
    """Save one vendor's month; and the month page of a vendor that is not
    Railway (a Railway account's opens on the Railway months tab, where
    Needs attention's "Put it in" and the Expenses page's links land).

    One input per project, saving upserts a ServiceCostEntry keyed on the
    calendar month and the resource so a second save this month corrects
    rather than doubles.
    """
    provider = db.session.get(ServiceProvider, id) or abort(404)
    target = _parse_month(request.args.get("month") or request.form.get("month"))
    p_start, p_end = _month_bounds(target)

    if request.method == "POST":
        _save_monthly_entries(provider, p_start, p_end)
        problem = _save_invoice(provider, p_start)
        if problem:
            db.session.rollback()
            flash(problem, "error")
        else:
            db.session.commit()
            _forget_bills()
            flash(f"{provider.display_name} costs for {p_start:%b %Y} saved.", "success")
        return redirect(month_url(provider, p_start))

    if provider.name == "railway":
        return redirect(month_url(provider, p_start))

    return render_template("pm/service_costs/monthly.html", railway=False,
                           providers=[provider], bills=[], month_url=month_url,
                           month_opts=[(m.strftime("%Y-%m"), m.strftime("%b %Y"))
                                       for m in _month_choices([provider])],
                           **_month_context(provider, target))


def _forget_bills():
    """A bill just recorded comes off Needs attention now, not when its ten
    minute cache runs out, so the tab and the row agree."""
    try:
        from pm import attention_routes
        attention_routes._BILLS_CACHE["value"] = None
    except Exception:
        pass


@service_costs_bp.route("/providers/<int:id>/monthly/automap", methods=["POST"])
@ceo_required
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
    return redirect(month_url(provider, month))


def _save_monthly_entries(provider, p_start, p_end):
    """Upsert one ServiceCostEntry per submitted resource, delete on blank/0.

    The form submits `amt:<resource_id>` for every row shown. A number > 0
    upserts through _record_cost_entry, which already handles the per-mapping
    split. A blank or 0 removes the entry for this month, so a mistaken save
    is not one-way. No expense comes or goes with it: the bank line is the
    expense, and the resplit at the end moves its shares to match the rows
    (discard_entry only drops an expense the old sync wrote, never a bank
    line's).

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
        # typed in. The bank line's share of it still rounds to cents;
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

    # The month's rows are how its bank charge splits across projects.
    import bank_feed
    bank_feed.resplit(provider_id=provider.id, days=400)
    db.session.commit()


def _delete_entries_for(provider, resource_id, p_start, p_end):
    for e in ServiceCostEntry.query.filter_by(
        provider_id=provider.id,
        resource_identifier=resource_id,
        period_start=p_start,
        period_end=p_end,
    ).all():
        _discard_entry(e)


STALE_AFTER_DAYS = 3


def pulls_itself(provider):
    """A Railway account that names its workspace reads its own bills
    (service_costs_service._sync_railway) and is not typed in by hand, so it
    is a synced vendor like any other: healthy when its last pull worked."""
    return provider.name == "railway" and provider_bills.pulls_its_bills(provider)


def vendor_health(providers):
    """Which vendors need something, and a count for the ones that do not.

    A healthy vendor is a number, not a chip: one bordered pill per vendor gave
    a failed sync the same weight as three vendors that were fine. Only the
    ones with something to do come back individually, each with the reason and
    where to go about it. The Vendors tab of Hosting counts the ones whose
    sync is the trouble (`sync_trouble`); a month to type is the Railway
    months tab's.
    """
    attention, healthy, oldest = [], 0, None
    now = datetime.now(timezone.utc)

    for p in providers:
        if not p.syncs:
            continue  # found on the bank or in the code: nothing to sync
        # 2026-11-03: the page still said "enter monthly" for both Railway
        # accounts a day after their bills began pulling themselves.
        if p.name in MANUAL_MONTHLY_PROVIDERS and not pulls_itself(p):
            attention.append({
                "provider": p, "tone": "manual", "note": "enter monthly",
                "href": url_for("service_costs.railway_months", provider=p.id),
            })
            continue
        if p.sync_error:
            attention.append({
                "provider": p, "tone": "failed", "note": "sync failed",
                "href": url_for("vendors.index"),
            })
            continue

        last = p.last_sync_at
        if last is None:
            attention.append({
                "provider": p, "tone": "stale", "note": "never synced",
                "href": url_for("vendors.index"),
            })
            continue
        # Stored through a column with no timezone, so it can come back naive
        # even though it was written aware. Comparing the two raises.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).days >= STALE_AFTER_DAYS:
            attention.append({
                "provider": p, "tone": "stale",
                "note": f"last synced {last:%b %d}",
                "href": url_for("vendors.index"),
            })
            continue

        healthy += 1
        if oldest is None or last < oldest:
            oldest = last

    if healthy == 0:
        summary = "" if attention else "No vendors yet"
    elif oldest is not None and oldest.date() == now.date():
        summary = f"{healthy} synced today"
    else:
        summary = f"{healthy} synced, oldest {oldest:%b %d}"

    return {"attention": attention, "healthy": healthy, "summary": summary}


def sync_trouble(providers):
    """{provider id: note} for every active vendor whose sync failed, never
    ran, or has not run in STALE_AFTER_DAYS: the Vendors tab's count and the
    note each of those vendors' cards carries, from one reading."""
    return {a["provider"].id: a["note"]
            for a in vendor_health([p for p in providers if p.is_active])["attention"]
            if a["tone"] != "manual"}

