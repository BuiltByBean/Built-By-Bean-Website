# -*- coding: utf-8 -*-
"""A contract's values apply when it is SIGNED, not sent (audit item 6), and
signatures are read every fifteen minutes whoever is looking (item 4).

  1. Sending a statement of work writes nothing it proposes: no project, no
     fee, no budget, no package move, no sale. The client and their lead move
     to "proposal sent" and no further. The proposal is kept on the request.
  2. The portal saying completed applies all of it: the client and the lead
     to contracted, the project made with its fee, budget, delivery date and
     default runbooks, the package to contracted, its products written as
     sales with their runbooks on the project, and the signed copy filed.
  3. A second refresh, or a second worker, applies nothing twice.
  4. A declined SOW puts the client and the lead back where they were.
  5. A hosting fee update changes the fee when signed, not when sent, and a
     voided one leaves the old fee.
  6. A paper copy (downloaded, not sent) applies at once, as before.
  7. A second worker that read the row before the first moved it acts on
     nothing (the compare-and-set).
  8. The watcher thread asks the portal on its own, and app.py starts it.

Run: python tools/test_signed_not_sent.py
"""
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-signed-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["SIGNATURE_REFRESH_SECONDS"] = "0"  # this test starts its own

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Client, Document, Lead, MvpPackage, MvpPackageItem,  # noqa: E402
                    Playbook, Product, ProductSale, Project, ProjectPlaybook,
                    SignatureRequest, User)
import pm.contract_routes as contract_routes  # noqa: E402
import signadoc_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


class Portal:
    """The signing portal, stubbed: every envelope it is sent, and whatever
    status each test sets on it."""

    def __init__(self):
        self.envelopes = {}
        self.n = 0

    def __getattr__(self, name):
        return getattr(signadoc_service, name)

    def configured(self):
        return True

    def send_for_signature(self, pdf_bytes, **kw):
        self.n += 1
        env = f"env-{self.n}"
        self.envelopes[env] = {"id": env, "status": "sent"}
        return {"id": env, "status": "sent", "mailMode": "smtp",
                "links": [{"signerId": "bbb", "url": "https://sign.test/bbb"},
                          {"signerId": "client", "url": "https://sign.test/c"}]}

    def list_envelopes(self):
        return list(self.envelopes.values())

    def sealed_pdf(self, envelope_id):
        return b"%PDF-1.4 signed"

    def void_envelope(self, envelope_id, reason=""):
        self.envelopes[envelope_id]["status"] = "voided"
        return {"status": "voided"}


portal = Portal()
contract_routes.signadoc = portal


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    acme = Client(name="Acme Hauling", email="acme@example.test", stage="in_conversation")
    zed = Client(name="Zed Bakery", email="zed@example.test", stage="contacted")
    host = Client(name="Hosted Co", email="host@example.test", stage="active_client")
    db.session.add_all([boss, acme, zed, host])
    db.session.flush()
    db.session.add_all([
        Playbook(slug="github", display_name="GitHub", is_default=True, is_active=True),
        Playbook(slug="twilio", display_name="Twilio", is_active=True),
    ])
    texting = Product(slug="texting", name="Texting", playbook_slug="twilio", price=500)
    db.session.add(texting)
    db.session.flush()
    package = MvpPackage(client_id=acme.id, name="Acme Dispatch", status="ready")
    db.session.add(package)
    db.session.flush()
    db.session.add(MvpPackageItem(package_id=package.id, kind="product",
                                  product_id=texting.id, name="Texting",
                                  notes="Drivers get their loads by text"))
    db.session.add_all([
        Lead(name="Acme Hauling", dedupe_key="acme", client_id=acme.id, stage="in_conversation"),
        Lead(name="Zed Bakery", dedupe_key="zed", client_id=zed.id, stage="contacted"),
    ])
    hosted = Project(client_id=host.id, name="Hosted App", hosting_fee=50.0,
                     hosting_cycle="monthly")
    db.session.add(hosted)
    db.session.commit()
    ids = dict(boss=boss.id, acme=acme.id, zed=zed.id, host=host.id,
               package=package.id, texting=texting.id, hosted=hosted.id)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True


def sow(client_id, name, action="send", **extra):
    form = {
        "previewed": "1", "preview_action": action,
        "client_id": str(client_id), "project_name": name,
        "project_description": "Dispatch for a hauling firm.",
        "features": ["Loads by text", "Driver list"],
        "mvp_price": "4,500", "sow_date": "2026-11-04", "delivery_date": "2026-12-15",
        "maintenance_days": "30", "hosting_fee": "60", "hosting_cycle": "monthly",
        "signer_name": "Pat Acme", "signer_email": "pat@example.test",
    }
    form.update(extra)
    return c.post("/admin/contracts/new/statement-of-work", data=form)


def get(model, pk):
    return db.session.get(model, pk)


print("1. SENDING TAKES NOTHING")
r = sow(ids["acme"], "Acme Dispatch", package_id=str(ids["package"]))
check("the SOW goes out", r.status_code == 302, r.status_code)
with application.app_context():
    req = SignatureRequest.query.filter_by(kind="sow").first()
    acme = get(Client, ids["acme"])
    check("a request was written", req is not None)
    check("no project exists yet", Project.query.filter_by(client_id=ids["acme"]).count() == 0)
    check("no contract revenue booked", not acme.contract_revenue, acme.contract_revenue)
    check("the client is at proposal sent", acme.stage == "proposal_sent", acme.stage)
    check("their lead too", Lead.query.filter_by(dedupe_key="acme").one().stage == "proposal_sent")
    check("the package is not contracted", get(MvpPackage, ids["package"]).status == "ready")
    check("nothing is sold", ProductSale.query.count() == 0)
    effects = json.loads(req.effects_json or "{}")
    check("the proposal is kept on the request",
          effects.get("project", {}).get("hosting_fee") == 60.0
          and effects.get("package_id") == ids["package"], effects)
    check("and nothing is applied", req.effects_applied_at is None)
    sow_env, sow_id = req.envelope_id, req.id

print("2. SIGNING APPLIES IT")
portal.envelopes[sow_env]["status"] = "completed"
with application.app_context():
    changed = contract_routes.refresh_open_requests()
    check("the refresh saw it", changed == 1, changed)
    req = get(SignatureRequest, sow_id)
    acme = get(Client, ids["acme"])
    project = Project.query.filter_by(client_id=ids["acme"]).one_or_none()
    check("the client is contracted", acme.stage == "contracted", acme.stage)
    check("with the price as contract revenue", acme.contract_revenue == 4500.0, acme.contract_revenue)
    check("the lead is contracted", Lead.query.filter_by(dedupe_key="acme").one().stage == "contracted")
    check("the project now exists", project is not None)
    if project is not None:
        check("with the fee", project.hosting_fee == 60.0, project.hosting_fee)
        check("the budget", project.budget == 4500.0, project.budget)
        check("the delivery date", str(project.mvp_date) == "2026-12-15", project.mvp_date)
        check("and the request points at it", req.project_id == project.id)
        books = {pp.playbook.slug for pp in ProjectPlaybook.query.filter_by(project_id=project.id)}
        check("default and product runbooks are on it", books == {"github", "twilio"}, books)
        sales = ProductSale.query.filter_by(project_id=project.id).all()
        check("the package's product is sold", [s.product_id for s in sales] == [ids["texting"]])
        check("carrying its note", sales and "by text" in sales[0].notes)
        check("the signed copy is filed against the project",
              req.signed_document_id and get(Document, req.signed_document_id).project_id == project.id)
    check("the package is contracted", get(MvpPackage, ids["package"]).status == "contracted")
    check("it is marked applied", req.effects_applied_at is not None)

print("3. NOTHING TWICE")
with application.app_context():
    import contract_effects
    req = get(SignatureRequest, sow_id)
    check("a second apply does nothing", contract_effects.apply_signed(req) is None)
    contract_routes.refresh_open_requests()
    db.session.commit()
    check("still one sale", ProductSale.query.count() == 1, ProductSale.query.count())
    check("still one project", Project.query.filter_by(client_id=ids["acme"]).count() == 1)

print("4. A DECLINE PUTS IT BACK")
r = sow(ids["zed"], "Zed Ordering")
with application.app_context():
    zreq = SignatureRequest.query.filter_by(client_id=ids["zed"]).one()
    check("Zed is at proposal sent", get(Client, ids["zed"]).stage == "proposal_sent")
    portal.envelopes[zreq.envelope_id].update(
        status="declined", signers=[{"id": "client", "declineReason": "Too dear"}])
    contract_routes.refresh_open_requests()
    zed = get(Client, ids["zed"])
    check("Zed is back to contacted", zed.stage == "contacted", zed.stage)
    check("their lead too", Lead.query.filter_by(dedupe_key="zed").one().stage == "contacted")
    check("no project was made", Project.query.filter_by(client_id=ids["zed"]).count() == 0)
    check("the reason is kept", get(SignatureRequest, zreq.id).decline_reason == "Too dear")

print("5. A HOSTING FEE UPDATE WAITS FOR ITS SIGNATURE")


def hosting(fee, action="send"):
    return c.post("/admin/contracts/new/hosting", data={
        "previewed": "1", "preview_action": action,
        "client_id": str(ids["host"]), "project_id": str(ids["hosted"]),
        "application": "Hosted App", "fee": fee, "cycle": "monthly",
        "previous_fee": "50", "effective": "2026-12-01", "date": "2026-11-04",
        "signer_name": "Host", "signer_email": "host@example.test"})


hosting("75")
with application.app_context():
    check("the fee is unchanged on sending", get(Project, ids["hosted"]).hosting_fee == 50.0)
    check("an active client stays active",
          get(Client, ids["host"]).stage == "active_client")
    hreq = SignatureRequest.query.filter_by(kind="hosting").one()
    portal.envelopes[hreq.envelope_id]["status"] = "completed"
    contract_routes.refresh_open_requests()
    check("the fee moves when signed", get(Project, ids["hosted"]).hosting_fee == 75.0)
hosting("99")
with application.app_context():
    vreq = (SignatureRequest.query.filter_by(kind="hosting")
            .order_by(SignatureRequest.id.desc()).first())
    vid = vreq.id
r = c.post(f"/admin/contracts/{vid}/void", data={"reason": "Changed my mind"})
with application.app_context():
    check("a voided update leaves the agreed fee", get(Project, ids["hosted"]).hosting_fee == 75.0)
    check("and is voided", get(SignatureRequest, vid).status == "voided")

print("6. PAPER APPLIES AT ONCE")
with application.app_context():
    paper = Client(name="Paper Co", email="paper@example.test")
    db.session.add(paper)
    db.session.commit()
    paper_id = paper.id
r = sow(paper_id, "Paper Build", action="download")
with application.app_context():
    check("the download is the PDF", r.mimetype == "application/pdf", r.mimetype)
    proj = Project.query.filter_by(client_id=paper_id).one_or_none()
    check("its project is made at once", proj is not None and proj.budget == 4500.0)
    check("and the client contracted", get(Client, paper_id).stage == "contracted")
    check("no request, so nothing waits", SignatureRequest.query.filter_by(client_id=paper_id).count() == 0)

print("7. A SECOND WORKER ACTS ON NOTHING")
r = sow(ids["zed"], "Zed Ordering")
with application.app_context():
    z2 = (SignatureRequest.query.filter_by(client_id=ids["zed"])
          .order_by(SignatureRequest.id.desc()).first())
    z2_id, z2_env = z2.id, z2.envelope_id
# Worker A reads the row; worker B moves it first; A then sees the envelope.
with application.app_context():
    stale = get(SignatureRequest, z2_id)
    _ = stale.status  # loaded as "sent"
    with application.app_context():
        pass
    db.session.execute(db.update(SignatureRequest).where(SignatureRequest.id == z2_id)
                       .values(status="completed"))
    acted = contract_routes._apply(stale, {"id": z2_env, "status": "completed"})
    db.session.commit()
    check("the stale worker does not act", acted is False)
    check("and applies nothing", Project.query.filter_by(client_id=ids["zed"]).count() == 0)

print("8. THE WATCHER ASKS ON ITS OWN")
calls = []
real_refresh = contract_routes.refresh_open_requests
contract_routes.refresh_open_requests = lambda: calls.append(1) or 0
os.environ["SIGNATURE_REFRESH_SECONDS"] = "1"
thread = contract_routes.start_signature_watcher(application)
deadline = time.time() + 5
while not calls and time.time() < deadline:
    time.sleep(0.1)
contract_routes.refresh_open_requests = real_refresh
check("the thread started", thread is not None and thread.is_alive())
check("and asked the portal without a page being opened", bool(calls))
check("it records when", contract_routes.watcher_state["last_run"] is not None)
os.environ["SIGNATURE_REFRESH_SECONDS"] = "0"
check("0 switches it off", contract_routes.start_signature_watcher(application) is None)
src = (ROOT / "app.py").read_text(encoding="utf-8")
check("app.py starts it", "start_signature_watcher(app)" in src)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all passed")
