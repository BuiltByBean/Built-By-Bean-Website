"""What a contract changes on the board, applied when it is signed.

Audit item 6, Michael's decision of 2026-11-04: a signed contract does what it
says, and an unsigned one takes nothing. The statement of work used to write
the client's stage, the project's fee, budget and dates the moment it was SENT,
and a hosting agreement its fee; a decline or a void took none of it back, so
the board could hold a fee and a stage nobody agreed to. The package, its
products and the lead were then moved by hand.

Now a document carries its proposal (`SignatureRequest.effects_json`) and three
moments act on it:

- **sent**: the client and their lead move to "proposal sent", if they were
  earlier than that. That is a fact the moment it goes out.
- **completed**: everything the document says. The client and the package to
  contracted, the project made if it does not exist yet and given its fee,
  budget, delivery date and maintenance window, the package's products written
  as `ProductSale` rows with their runbooks put on the project, the lead moved.
- **declined or voided**: what was there is put back (`undo_json`), unless
  something since has moved it on, or another contract for the same client is
  still out or already signed.

A contract downloaded to be signed on paper has no envelope to report back, so
its proposal applies at once (`apply_now`), which is what every contract did
before. The board cannot see paper.

Every write here is to one request's own effects, guarded by
`effects_applied_at` and taken with a compare-and-set, because two gunicorn
workers each run the signature watcher and both can see the same envelope
complete.
"""
import json
from datetime import datetime, timezone

from models import (db, CLIENT_STAGE_CHOICES, Client, Lead, MvpPackage, Playbook, ProductSale,
                    Project, ProjectPlaybook, SignatureRequest)

# How far along a client is. Moves made here go forward only: a client already
# paying is never walked back to contracted by a second statement of work.
# "Follow up later" and "Not interested" rank with a lead: somebody who signs
# has plainly changed their mind.
FUNNEL = ("lead", "contacted", "in_conversation", "proposal_sent",
          "contracted", "active_client")


def _rank(stage):
    try:
        return FUNNEL.index(stage or "lead")
    except ValueError:
        return 0


def _now():
    return datetime.now(timezone.utc)


def _load(raw):
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _date(value):
    from datetime import date
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def apply_default_playbooks(project):
    """Attach every playbook marked default. Returns how many were added.

    The one copy: app.py's project form and the statement of work both call
    it, because a project born from a signature is still a project and GitHub
    and Railway are on every build.
    """
    added = 0
    for pb in Playbook.query.filter_by(is_default=True, is_active=True).all():
        exists = ProjectPlaybook.query.filter_by(
            project_id=project.id, playbook_id=pb.id).first()
        if not exists:
            db.session.add(ProjectPlaybook(project_id=project.id, playbook_id=pb.id))
            added += 1
    return added


# ── Building a proposal ──────────────────────────────────


def find_package(client, package_id=None, project_name=""):
    """The MVP package a statement of work was written from, or None.

    Named on the form when the SOW was opened from the MVP Builder. Without
    that, a client's one open package whose name is the project's counts,
    because that is exactly what the builder hands the form, and anything
    looser would contract a package the SOW never mentioned.
    """
    if client is None:
        return None
    if package_id:
        package = db.session.get(MvpPackage, package_id)
        if package is not None and package.client_id == client.id:
            return package
        return None
    name = (project_name or "").strip().lower()
    if not name:
        return None
    open_ones = [p for p in MvpPackage.query.filter_by(client_id=client.id).all()
                 if p.status in ("scoping", "ready")]
    named = [p for p in open_ones if (p.name or "").strip().lower() == name]
    return named[0] if len(named) == 1 else None


def sow_effects(*, client, project, project_name, price, mvp_date, maintenance_days,
                hosting_fee, hosting_cycle, package=None):
    """The proposal a statement of work carries. Plain values only: it is
    stored as JSON and read back on a later request, maybe a week later."""
    return {
        "kind": "sow",
        "client_id": client.id,
        "client": {"stage": "contracted", "contract_revenue": price},
        "project_id": project.id if project is not None else None,
        "project_name": project_name,
        "project": {
            "budget": price,
            "mvp_date": _iso(mvp_date),
            "maintenance_days": maintenance_days,
            "hosting_fee": hosting_fee,
            "hosting_cycle": hosting_cycle or "monthly",
        },
        "package_id": package.id if package is not None else None,
    }


def hosting_effects(*, client, project, fee, cycle):
    """A hosting agreement, or a fee update: the fee and its cycle."""
    return {
        "kind": "hosting",
        "client_id": client.id if client is not None else None,
        "project_id": project.id if project is not None else None,
        "project": {"hosting_fee": fee, "hosting_cycle": cycle or "monthly"},
    }


def proposal(row):
    return _load(row.effects_json)


# ── Sent ─────────────────────────────────────────────────


def _move_leads(client, stage, undo_list):
    for lead in Lead.query.filter_by(client_id=client.id).all():
        if _rank(lead.stage) < _rank(stage) and lead.stage not in ("active_client",):
            undo_list.append({"id": lead.id, "stage": lead.stage,
                              "stage_changed_at": _iso(lead.stage_changed_at)})
            lead.stage = stage
            lead.stage_changed_at = _now()


def record_sent(row, effects):
    """Store the proposal on a request that has just gone out, and move the
    client to "proposal sent". Commits."""
    row.effects_json = json.dumps(effects)
    undo = _load(row.undo_json)
    client = db.session.get(Client, effects.get("client_id") or 0)
    if client is not None and effects.get("kind") == "sow":
        sent = {"leads": []}
        if _rank(client.stage) < _rank("proposal_sent"):
            sent["client_stage"] = client.stage
            client.stage = "proposal_sent"
        _move_leads(client, "proposal_sent", sent["leads"])
        undo["sent"] = sent
    row.undo_json = json.dumps(undo)
    db.session.commit()


# ── Signed ───────────────────────────────────────────────


def _claim(row):
    """Take this request's effects for this process, or learn another took
    them. A compare-and-set on the row, so of two workers seeing the same
    envelope complete, exactly one applies it."""
    if row.effects_applied_at is not None:
        return False
    stamp = _now()
    done = db.session.execute(
        db.update(SignatureRequest)
        .where(SignatureRequest.id == row.id,
               SignatureRequest.effects_applied_at.is_(None))
        .values(effects_applied_at=stamp)
        .execution_options(synchronize_session=False)
    ).rowcount
    if done != 1:
        return False
    row.effects_applied_at = stamp
    return True


def _project_for(effects, client, undo):
    project = db.session.get(Project, effects.get("project_id") or 0)
    if project is not None and client is not None and project.client_id != client.id:
        project = None
    if project is None and client is not None and effects.get("project_name"):
        project = Project.query.filter(
            Project.client_id == client.id,
            Project.name.ilike(effects["project_name"])).first()
    if project is None and client is not None and effects.get("project_name"):
        project = Project(client_id=client.id, name=effects["project_name"][:200])
        db.session.add(project)
        db.session.flush()
        apply_default_playbooks(project)
        undo["project_created"] = True
    return project


def _set_project(project, values, undo):
    before = {}
    for field in ("budget", "mvp_date", "maintenance_days", "hosting_fee", "hosting_cycle"):
        if field not in values:
            continue
        new = values[field]
        if field == "mvp_date":
            new = _date(new)
            if new is None:
                continue
        if new is None:
            continue
        before[field] = _iso(getattr(project, field))
        setattr(project, field, new)
    undo["project"] = {"id": project.id, "before": before}


def _sell_package(package, client, project, undo):
    """The package's products, written down as sold. Each carries no price of
    its own: the SOW priced the build as a whole, and a product's list price
    is what it costs today, not what this client agreed to."""
    sales, runbooks = [], []
    for item in package.product_items:
        product = item.product
        if product is None:
            continue
        exists = ProductSale.query.filter_by(product_id=product.id,
                                             project_id=project.id).first()
        if exists is None:
            sale = ProductSale(product_id=product.id, client_id=client.id,
                               project_id=project.id, delivery_date=project.mvp_date,
                               notes=(item.notes or "").strip()
                               or "From the signed statement of work.")
            db.session.add(sale)
            db.session.flush()
            sales.append(sale.id)
        if product.playbook_slug:
            playbook = Playbook.query.filter_by(slug=product.playbook_slug,
                                                is_active=True).first()
            if playbook is not None and not ProjectPlaybook.query.filter_by(
                    project_id=project.id, playbook_id=playbook.id).first():
                link = ProjectPlaybook(project_id=project.id, playbook_id=playbook.id)
                db.session.add(link)
                db.session.flush()
                runbooks.append(link.id)
    undo["sales"] = sales
    undo["runbooks"] = runbooks


def _apply(row, effects):
    """Do what the document says. Returns a short summary for the log."""
    undo = _load(row.undo_json)
    signed = {}
    client = db.session.get(Client, effects.get("client_id") or 0)
    done = []

    if effects.get("kind") == "sow" and client is not None:
        values = effects.get("client") or {}
        signed["client"] = {"stage": client.stage,
                            "contract_revenue": client.contract_revenue}
        if _rank(client.stage) < _rank("contracted"):
            client.stage = "contracted"
        if values.get("contract_revenue") is not None:
            client.contract_revenue = values["contract_revenue"]
        signed["leads"] = []
        _move_leads(client, "contracted", signed["leads"])
        done.append(f"{client.name} contracted")

    project = None
    if effects.get("kind") == "sow":
        project = _project_for(effects, client, signed)
    else:
        project = db.session.get(Project, effects.get("project_id") or 0)
    if project is not None:
        _set_project(project, effects.get("project") or {}, signed)
        if row.project_id is None:
            row.project_id = project.id
        done.append(f"{project.name} updated")

    package = db.session.get(MvpPackage, effects.get("package_id") or 0)
    if package is not None and client is not None and package.client_id == client.id:
        signed["package"] = {"id": package.id, "status": package.status}
        package.status = "contracted"
        if project is not None:
            _sell_package(package, client, project, signed)
            if signed.get("sales"):
                done.append(f"{len(signed['sales'])} product sale(s) written")
        done.append(f"{package.name} contracted")

    undo["signed"] = signed
    row.undo_json = json.dumps(undo)
    return ", ".join(done)


def apply_signed(row):
    """Called the moment the portal says `completed`. Applies the proposal
    once, whichever process gets there first. Does not commit: the caller's
    status write and this land in one transaction."""
    effects = proposal(row)
    if not effects or not _claim(row):
        return None
    return _apply(row, effects)


def apply_now(effects):
    """For a contract that will be signed on paper: there is no envelope to
    say when, so it applies as it is downloaded. Returns the project, or None.
    Commits."""
    stub = SignatureRequest(effects_json=json.dumps(effects))
    _apply(stub, effects)
    project = db.session.get(Project, stub.project_id) if stub.project_id else None
    db.session.commit()
    return project


# ── Declined or voided ───────────────────────────────────


def _other_live(row, client_id):
    """Another contract for this client that is still out or already signed.
    Putting their stage back would then be wrong: that one still stands."""
    if not client_id:
        return False
    return SignatureRequest.query.filter(
        SignatureRequest.client_id == client_id,
        SignatureRequest.id != row.id,
        SignatureRequest.status.in_(("draft", "sent", "completed")),
    ).first() is not None


def _put_back_leads(saved, only_if):
    for entry in saved or []:
        lead = db.session.get(Lead, entry.get("id") or 0)
        if lead is not None and lead.stage == only_if:
            lead.stage = entry.get("stage") or "lead"
            stamp = entry.get("stage_changed_at")
            lead.stage_changed_at = (datetime.fromisoformat(stamp) if stamp else None)


def put_back(row):
    """A decline or a void: undo what this request did, as far as nothing has
    moved it on since. Returns a summary, or None when there was nothing.
    Does not commit."""
    undo = _load(row.undo_json)
    if not undo:
        return None
    effects = proposal(row)
    client_id = effects.get("client_id") or row.client_id
    client = db.session.get(Client, client_id or 0)
    others = _other_live(row, client_id)
    done = []

    signed = undo.get("signed") or {}
    if signed:
        for sale_id in signed.get("sales") or []:
            sale = db.session.get(ProductSale, sale_id)
            if sale is not None:
                db.session.delete(sale)
        for link_id in signed.get("runbooks") or []:
            link = db.session.get(ProjectPlaybook, link_id)
            if link is not None:
                db.session.delete(link)
        saved = signed.get("project") or {}
        project = db.session.get(Project, saved.get("id") or 0)
        if project is not None:
            for field, value in (saved.get("before") or {}).items():
                setattr(project, field, _date(value) if field == "mvp_date" else value)
            if signed.get("project_created"):
                # Never deleted: time or tickets may hang on it by now. It is
                # taken off the active list, where a project nobody agreed to
                # does not belong.
                project.status = "archived"
            done.append(f"{project.name} put back")
        pkg = signed.get("package") or {}
        package = db.session.get(MvpPackage, pkg.get("id") or 0)
        if package is not None and package.status == "contracted":
            package.status = pkg.get("status") or "ready"
            done.append(f"{package.name} back to {package.status_label}")
        if client is not None and not others:
            before = signed.get("client") or {}
            if client.stage == "contracted" and before.get("stage"):
                client.stage = before["stage"]
            client.contract_revenue = before.get("contract_revenue") or 0.0
            _put_back_leads(signed.get("leads"), "contracted")
        row.effects_applied_at = None

    sent = undo.get("sent") or {}
    if sent and client is not None and not others:
        if client.stage == "proposal_sent" and sent.get("client_stage"):
            client.stage = sent["client_stage"]
            done.append(f"{client.name} back to {dict(CLIENT_STAGE_CHOICES).get(client.stage, client.stage)}")
        _put_back_leads(sent.get("leads"), "proposal_sent")

    row.undo_json = None
    return ", ".join(done) or None
