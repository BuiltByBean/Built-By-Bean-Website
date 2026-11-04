# -*- coding: utf-8 -*-
"""A payment moves the client, and a Stripe invoice finds its client.

docs/automation_gaps.md item 5 and fault 6. Proves, with Stripe faked:

  1. The six-hourly importer moves a client to Active on a payment it sees
     arrive, and never on an old payment read for the first time.
  2. An orphan customer finds its client by the board's metadata, then by
     email; the email must name exactly one client with no customer yet; a
     customer id somebody typed is never overruled.
  3. An imported invoice takes the client's project when there is exactly one,
     and none when there are two.
  4. The webhook does the same: makes the row, finds the orphan's client,
     moves the stage on the first paid event.
  5. Making a customer looks one up by metadata and email first, and Sync all
     clients links rather than duplicates.

Run: python tools/test_payment_moves_client.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-paid-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "MAIL_SYNC_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import stripe  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Client, Invoice, Project, User  # noqa: E402
import stripe_service  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


NOW = datetime.now(timezone.utc)


def row(sid, customer, status="paid", paid_days_ago=1, email=None, ref=None):
    return {"id": sid, "number": sid.upper(), "status": status, "customer_id": customer,
            "customer_email": email, "customer_client_ref": ref,
            "total": 100.0, "tax": 0.0, "amount_due": 0.0,
            "amount_paid": 100.0 if status == "paid" else 0.0, "refunded": 0.0,
            "issued_at": NOW - timedelta(days=paid_days_ago + 3), "due_date": None,
            "paid_at": (NOW - timedelta(days=paid_days_ago)) if status == "paid" else None,
            "catchup": False}


ROWS = []
stripe_service.get_stripe_invoices = lambda ttl=0: list(ROWS)

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    linked = Client(name="Linked Co", email="a@linked.test", stage="proposal_sent",
                    stripe_customer_id="cus_linked")
    old = Client(name="Old Co", email="o@old.test", stage="follow_up",
                 stripe_customer_id="cus_old")
    by_meta = Client(name="Meta Co", email="m@meta.test", stage="contracted")
    by_mail = Client(name="Mail Co", email="Pay@Mail.test ", stage="contracted")
    twin_a = Client(name="Twin A", email="same@twin.test", stage="lead")
    twin_b = Client(name="Twin B", email="same@twin.test", stage="lead")
    typed = Client(name="Typed Co", email="t@typed.test", stage="lead",
                   stripe_customer_id="cus_typed")
    db.session.add_all([linked, old, by_meta, by_mail, twin_a, twin_b, typed])
    db.session.flush()
    db.session.add(Project(name="Linked app", client_id=linked.id))
    db.session.add_all([Project(name="Mail one", client_id=by_mail.id),
                        Project(name="Mail two", client_id=by_mail.id)])
    db.session.commit()
    ids = {c.name: c.id for c in Client.query.all()}
    linked_project = Project.query.filter_by(name="Linked app").first().id

print("1. The importer moves the stage")
ROWS[:] = [row("in_new", "cus_linked"), row("in_old", "cus_old", paid_days_ago=400)]
with application.app_context():
    stripe_service.import_invoices_from_stripe()
    check("a payment that just arrived moves the client to Active",
          db.session.get(Client, ids["Linked Co"]).stage == "active_client")
    check("an old payment read for the first time does not",
          db.session.get(Client, ids["Old Co"]).stage == "follow_up")
    inv = Invoice.query.filter_by(stripe_invoice_id="in_new").first()
    check("the invoice takes the client's only project", inv.project_id == linked_project)
    # Set back by hand, then read again: a payment already written down is
    # not news a second time.
    c = db.session.get(Client, ids["Linked Co"])
    c.stage = "follow_up"
    db.session.commit()
    stripe_service.import_invoices_from_stripe()
    check("a second read of the same payment does not move it again",
          db.session.get(Client, ids["Linked Co"]).stage == "follow_up")
    check("newly_paid is false once paid_at was set",
          not stripe_service.newly_paid(NOW, NOW))

print("2. Orphans find their client")
ROWS[:] = [
    row("in_meta", "cus_meta", email="nobody@else.test", ref=ids["Meta Co"]),
    row("in_mail", "cus_mail", email="pay@mail.test"),
    row("in_twin", "cus_twin", email="same@twin.test"),
    row("in_typed", "cus_other", email="t@typed.test"),
    row("in_none", "cus_none", email="stranger@x.test"),
]
with application.app_context():
    made, updated, orphans = stripe_service.import_invoices_from_stripe()
    meta = db.session.get(Client, ids["Meta Co"])
    mail = db.session.get(Client, ids["Mail Co"])
    check("matched by the board's metadata, and the empty id is filled",
          meta.stripe_customer_id == "cus_meta"
          and Invoice.query.filter_by(stripe_invoice_id="in_meta").first().client_id == meta.id)
    check("matched by email, case and spaces aside",
          mail.stripe_customer_id == "cus_mail"
          and Invoice.query.filter_by(stripe_invoice_id="in_mail").first().client_id == mail.id)
    check("and both move to Active on the payment",
          meta.stage == "active_client" and mail.stage == "active_client")
    check("two projects: the invoice is left for a person to place",
          Invoice.query.filter_by(stripe_invoice_id="in_mail").first().project_id is None)
    check("an email two clients share matches neither",
          "IN_TWIN" in orphans and not db.session.get(Client, ids["Twin A"]).stripe_customer_id)
    check("a typed customer id is never overruled by an email",
          db.session.get(Client, ids["Typed Co"]).stripe_customer_id == "cus_typed"
          and "IN_TYPED" in orphans)
    check("a stranger stays an orphan, named", "IN_NONE" in orphans)


class Obj(dict):
    """A Stripe object: subscript and attribute both work."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


print("3. The webhook")
with application.app_context():
    fresh = Client(name="Hook Co", email="h@hook.test", stage="proposal_sent")
    db.session.add(fresh)
    db.session.flush()
    db.session.add(Project(name="Hook app", client_id=fresh.id))
    db.session.commit()
    hook_id = fresh.id
    hook_project = Project.query.filter_by(name="Hook app").first().id

stripe.api_key = "sk_test_fake"
stripe.Customer.retrieve = staticmethod(lambda cid: Obj(id=cid, metadata=Obj(pm_client_id=str(hook_id))))


def event(eid, kind):
    return {"id": eid, "type": kind, "data": {"object": Obj(
        id="in_hook", customer="cus_hook", customer_email="other@x.test",
        number="H-1", total=5000, amount_due=0, amount_paid=5000)}}


with application.app_context():
    stripe_service.process_invoice_event(event("evt_1", "invoice.paid"))
    inv = Invoice.query.filter_by(stripe_invoice_id="in_hook").first()
    client = db.session.get(Client, hook_id)
    check("the webhook places an orphan by the customer's metadata",
          inv is not None and inv.client_id == hook_id and client.stripe_customer_id == "cus_hook")
    check("and gives it the only project", inv.project_id == hook_project)
    check("and the payment moves the client to Active", client.stage == "active_client")
    client.stage = "follow_up"
    db.session.commit()
    stripe_service.process_invoice_event(event("evt_2", "invoice.payment_succeeded"))
    check("the second paid event for the same invoice moves nothing",
          db.session.get(Client, hook_id).stage == "follow_up")

print("4. Making a customer finds one first")
calls = {"create": 0, "modify": []}
CUSTOMERS = [Obj(id="cus_found", created=10, metadata=Obj()),
             Obj(id="cus_newer", created=20, metadata=Obj())]
stripe.Customer.search = staticmethod(lambda query: Obj(data=[]))
stripe.Customer.list = staticmethod(lambda email, limit: Obj(data=[c for c in CUSTOMERS if email == "find@me.test"]))


def fake_create(**kw):
    calls["create"] += 1
    return Obj(id=f"cus_made{calls['create']}")


stripe.Customer.create = staticmethod(fake_create)
stripe.Customer.modify = staticmethod(lambda cid, **kw: calls["modify"].append((cid, kw)))
with application.app_context():
    a = Client(name="Find Me", email="find@me.test")
    b = Client(name="Brand New", email="new@me.test")
    db.session.add_all([a, b])
    db.session.commit()
    stripe_service.create_stripe_customer(a)
    stripe_service.create_stripe_customer(b)
    check("an existing customer with the email is adopted, oldest first",
          a.stripe_customer_id == "cus_found" and calls["create"] == 1)
    check("and the board's id is written into its metadata",
          calls["modify"] and calls["modify"][0][0] == "cus_found")
    check("a client Stripe does not know gets a new customer", b.stripe_customer_id == "cus_made1")
    db.session.commit()

    c = Client(name="Find Me Again", email="find@me.test")
    db.session.add(c)
    db.session.commit()
    stripe_service.create_stripe_customer(c)
    check("a customer another client carries is never handed out twice",
          c.stripe_customer_id == "cus_newer")
    db.session.commit()

with application.app_context():
    d = Client(name="Sync Me", email="find@me.test")
    e = Client(name="Sync New", email="other@me.test")
    db.session.add_all([d, e])
    db.session.commit()
    # Every customer with this email is now taken, so d gets a new one.
    CUSTOMERS.append(Obj(id="cus_spare", created=5, metadata=Obj(pm_client_id=str(d.id))))
    d_id, e_id = d.id, e.id
with application.test_client() as http:
    with http.session_transaction() as s:
        with application.app_context():
            s["_user_id"] = str(User.query.filter_by(username="mb").first().id)
        s["_fresh"] = True
    resp = http.post("/admin/stripe/clients/sync-all")
    with http.session_transaction() as s:
        page = " ".join(text for _, text in s.get("_flashes", []))
with application.app_context():
    check("Sync all clients links the client Stripe already has",
          db.session.get(Client, d_id).stripe_customer_id == "cus_spare",
          db.session.get(Client, d_id).stripe_customer_id)
    check("and creates only for the one it does not",
          (db.session.get(Client, e_id).stripe_customer_id or "").startswith("cus_made"))
    # Created 3: Sync New, and the two twins, whom Stripe does not know.
    check("and says which is which", "Linked 1 client(s)" in page and "created 3" in page,
          page)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
