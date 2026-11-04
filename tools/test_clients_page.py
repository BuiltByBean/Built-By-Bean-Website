# -*- coding: utf-8 -*-
"""The Clients pages after the 2026-11-04 cleanup, and item 16's mail rules.

Michael: "make them more user friendly and dont have unused features". The
hand-typed contact log had no rows on any client, so it went, and mail became
the record of contact. This boots the board on a throwaway SQLite database
and proves:

  1. A client is matched on their address, then on their business domain; a
     free mail domain, the board's own domain, or a domain two clients share
     never matches.
  2. The mail sync searches a client's whole domain, not their one address.
  3. A reply from a client at Lead or Contacted moves them to In conversation;
     one further along does not move; a reply sent from the board moves Lead
     to Contacted.
  4. A contact form enquiry from a stranger writes a lead with the enquiry as
     a touch; a second one finds the same lead; one from a lead's address or
     website domain links that lead.
  5. A converted lead follows its client's stage, whichever side moves it.
  6. Mail filed to nobody is filed to a client added afterwards.
  7. The pages: no contact log, no channel filters, Last contact from mail,
     contracts and apps on the client page, delete in the edit page's header
     behind the client's name typed (and checked again on the server), the
     app fields folded, counts with commas, and the old contact routes gone.

Run: python tools/test_clients_page.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-clients-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ["MAIL_USERNAME"] = "michael@builtbybean.com"
os.environ["OWN_EMAILS"] = "mbean@entertainhq.com"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Client, Project, AppLink, User, Lead, LeadPerson,  # noqa: E402
                    LeadTouch, Message, SignatureRequest)
from pm import mail_service, contact_matching  # noqa: E402

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["WTF_CSRF_ENABLED"] = False
application.config["MAIL_USERNAME"] = "michael@builtbybean.com"
application.config["OWN_EMAILS"] = "mbean@entertainhq.com"
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def mail(frm, subject, body="Hello", msg_id=None, reply_to=None):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "michael@builtbybean.com"
    m["Subject"] = subject
    m["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    if msg_id:
        m["Message-ID"] = msg_id
    if reply_to:
        m["In-Reply-To"] = reply_to
    m.set_content(body)
    return m


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    kenali = Client(name="Kenali Kendrick", company="J&D Entertainment Company",
                    email="kkendrick@jdentertain.com", stage="contracted")
    cason = Client(name="Cason Kuper", email="cason@kuperplumbing.com", stage="contacted")
    lucas = Client(name="Lucas Miller", email="lucas@gmail.com", stage="lead")
    me = Client(name="Michael Bean", email="mbean@entertainhq.com", stage="contracted")
    twin_a = Client(name="Twin A", email="a@twins.example", stage="lead")
    twin_b = Client(name="Twin B", email="b@twins.example", stage="lead")
    db.session.add_all([boss, kenali, cason, lucas, me, twin_a, twin_b])
    db.session.flush()
    proj = Project(name="Talent Booker", client_id=kenali.id, status="active")
    db.session.add(proj)
    db.session.flush()
    db.session.add(AppLink(name="Talent Booker", url="https://staff.jdentertain.com", project_id=proj.id))
    db.session.add(SignatureRequest(envelope_id="env-1", title="Statement of Work",
                                    client_id=kenali.id, signer_name="Kenali",
                                    signer_email="kkendrick@jdentertain.com", status="completed"))
    db.session.add(SignatureRequest(envelope_id="env-2", title="Hidden test contract",
                                    client_id=kenali.id, signer_name="Kenali",
                                    signer_email="kkendrick@jdentertain.com", status="voided",
                                    archived_at=datetime.now(timezone.utc)))
    open_lead = Lead(name="Paris Paint Co", dedupe_key="parispaint|1main", email="",
                     website="https://www.parispaint.example/", stage="lead")
    person_lead = Lead(name="Blossom Bakery", dedupe_key="blossom|2main", stage="contacted")
    db.session.add_all([open_lead, person_lead])
    db.session.flush()
    db.session.add(LeadPerson(lead_id=person_lead.id, name="Ann Baker", email="ann@blossom.example"))
    converted = Lead(name="Kuper Plumbing", dedupe_key="kuper|3main", stage="in_conversation",
                     client_id=cason.id)
    db.session.add(converted)
    db.session.commit()
    ids = dict(boss=boss.id, kenali=kenali.id, cason=cason.id, lucas=lucas.id, me=me.id,
               twin_a=twin_a.id, open_lead=open_lead.id, person_lead=person_lead.id,
               converted=converted.id)

    print("1. matching")
    m = contact_matching.match_client
    check("exact address", m("KKendrick@jdentertain.com").id == ids["kenali"])
    check("a colleague on the client's domain", (m("loui@jdentertain.com") or Client()).id == ids["kenali"])
    check("a free mail domain never matches", m("someone@gmail.com") is None)
    check("his own domain never matches his own row", m("partner@entertainhq.com") is None)
    check("a shared domain is a tie, so nobody", m("c@twins.example") is None)
    check("the exact address still wins on a shared domain", m("a@twins.example").id == ids["twin_a"])

    print("2. what the sync searches")
    senders = mail_service.watched_senders()
    check("the client's domain is searched", "@jdentertain.com" in senders, senders)
    check("an address the domain covers is not searched twice", "kkendrick@jdentertain.com" not in senders)
    check("a gmail client is searched by address", "lucas@gmail.com" in senders)
    check("no free domain is searched", "@gmail.com" not in senders)
    check("his own address is never searched", "mbean@entertainhq.com" not in senders)

    print("3. a reply moves the stage")
    mail_service.ingest(mail("Cason <cason@kuperplumbing.com>", "Re: quote", msg_id="<a1@x>"))
    mail_service.ingest(mail("Loui <loui@jdentertain.com>", "App build", msg_id="<a2@x>"))
    lucas_row = mail_service.ingest(mail("lucas@gmail.com", "Hi", msg_id="<a3@x>"))
    db.session.commit()
    check("Contacted -> In conversation", db.session.get(Client, ids["cason"]).stage == "in_conversation")
    check("Contracted stays Contracted", db.session.get(Client, ids["kenali"]).stage == "contracted")
    check("a colleague's mail is filed to the client",
          Message.query.filter_by(external_id="<a2@x>").first().client_id == ids["kenali"])
    check("Lead -> In conversation", db.session.get(Client, ids["lucas"]).stage == "in_conversation")
    twin = db.session.get(Client, ids["twin_a"])
    from pm.contact_matching import advance_client
    check("mail sent from the board moves Lead to Contacted",
          advance_client(twin, "out") == "contacted" and twin.stage == "contacted")
    check("and never walks a stage back", advance_client(db.session.get(Client, ids["kenali"]), "out") is None)
    db.session.commit()

    print("4. contact form enquiries and leads")
    row = mail_service.record_contact("Dana Ortiz", "dana@ortizfarms.example", "Website", "I need a site")
    new_lead = Lead.query.filter_by(email="dana@ortizfarms.example").first()
    check("a stranger's enquiry writes a lead", new_lead is not None)
    check("with the enquiry as a touch", new_lead and len(new_lead.touches) == 1
          and "Website enquiry" in new_lead.touches[0].note, new_lead and [t.note for t in new_lead.touches])
    check("at In conversation", new_lead and new_lead.stage == "in_conversation")
    check("and the message is still kept, unfiled to a client", row.client_id is None and row.id)
    mail_service.record_contact("Dana Ortiz", "dana@ortizfarms.example", "Website", "Following up")
    check("a second enquiry finds the same lead",
          Lead.query.filter_by(email="dana@ortizfarms.example").count() == 1
          and len(Lead.query.filter_by(email="dana@ortizfarms.example").first().touches) == 2)
    mail_service.record_contact("Ann", "ann@blossom.example", "", "Do you do menus?")
    pl = db.session.get(Lead, ids["person_lead"])
    check("a lead person's address links their lead", len(pl.touches) == 1 and pl.stage == "in_conversation")
    mail_service.record_contact("Pat", "pat@parispaint.example", "", "Quote please")
    ol = db.session.get(Lead, ids["open_lead"])
    check("a lead's website domain links that lead", len(ol.touches) == 1)
    mail_service.record_contact("Kenali", "kkendrick@jdentertain.com", "", "Another app")
    check("a client's enquiry is filed to the client, not a lead",
          Message.query.filter_by(source="contact_form", from_email="kkendrick@jdentertain.com").first().client_id == ids["kenali"]
          and Lead.query.filter_by(email="kkendrick@jdentertain.com").count() == 0)
    # A lead's later Gmail reply, once the form put their address on the watch list.
    mail_service.ingest(mail("dana@ortizfarms.example", "Re: your site", msg_id="<a4@x>"))
    db.session.commit()
    check("a lead's mail later on is logged as a touch",
          len(Lead.query.filter_by(email="dana@ortizfarms.example").first().touches) == 3)

    print("5. a converted lead follows its client")
    cason = db.session.get(Client, ids["cason"])
    cason.stage = "active_client"
    db.session.commit()
    check("client moved, lead follows", db.session.get(Lead, ids["converted"]).stage == "active_client")

    print("6. mail that arrived before its client")
    mail_service.ingest(mail("ops@newco.example", "Hello", msg_id="<a5@x>"))
    db.session.commit()
    newco = Client(name="New Co", email="boss@newco.example", stage="lead")
    db.session.add(newco)
    db.session.commit()
    filed = contact_matching.relink_unmatched()
    db.session.commit()
    check("filed to the client added afterwards",
          filed >= 1 and Message.query.filter_by(external_id="<a5@x>").first().client_id == newco.id)
    check("without moving their stage", db.session.get(Client, newco.id).stage == "lead")

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("7. the pages")
html = c.get("/admin/clients").data.decode("utf-8", "replace")
check("list renders", "Kenali Kendrick" in html)
check("no channel filters", 'name="tried"' not in html and 'name="not_tried"' not in html)
check("Last contact from mail", "Last contact" in html and "They wrote" in html)
check("a client with no mail says so", "No mail yet" in html)
html = c.get(f"/admin/clients/{ids['kenali']}").data.decode("utf-8", "replace")
check("client page renders", "Kenali Kendrick" in html)
check("no contact log", "Log contact" not in html and "Contact log" not in html)
check("their mail is on it", "App build" in html and "last contact" in html)
check("their contracts are on it", "Statement of Work" in html and "Signed" in html)
check("a hidden contract stays hidden", "Hidden test contract" not in html)
check("their apps are on it", "staff.jdentertain.com" in html)
check("an invoices link took the Stripe pill's place",
      f"client_id={ids['kenali']}" in html and "Not synced" not in html and "Synced" not in html)
check("email and phone are tappable", "mailto:kkendrick@jdentertain.com" in html)
check("no delete on the page", "Delete client" not in html)
html = c.get(f"/admin/clients/{ids['kenali']}/edit").data.decode("utf-8", "replace")
head = html.split('id="pm-actions"', 1)[1].split("</span>", 1)[0]
check("delete is in the page header, not under the form", 'aria-label="Delete client"' in head, head[:300])
check("it asks for the name typed", 'name="confirm_name"' in html and "Type <strong" in html)
check("the dialog is a real modal", 'role="dialog"' in html and 'aria-modal="true"' in html
      and '@keydown.tab="trap($event)"' in html)
check("the app fields are folded", "Their app" in html and "open: false" in html)
check("old contact routes are gone",
      c.post(f"/admin/clients/{ids['kenali']}/contacts").status_code == 404
      and c.post("/admin/contacts/1/delete").status_code == 404)
# Type the name to confirm, held on the server: nothing, the wrong name and
# half the name are refused; the right name in the wrong case deletes.
with application.app_context():
    doomed = Client(name="Doomed Client Co", email="d@doomed.example")
    db.session.add(doomed)
    db.session.flush()
    db.session.add(Project(name="Doomed build", client_id=doomed.id, status="active"))
    db.session.commit()
    doomed_id = doomed.id
for label, typed in (("nothing typed", None), ("the wrong name", "Kenali Kendrick"),
                     ("half the name", "Doomed")):
    data = {} if typed is None else {"confirm_name": typed}
    r = c.post(f"/admin/clients/{doomed_id}/delete", data=data)
    with application.app_context():
        check(f"delete refused with {label}", db.session.get(Client, doomed_id) is not None
              and r.status_code == 302 and "/edit" in r.headers.get("Location", ""))
r = c.post(f"/admin/clients/{doomed_id}/delete", data={"confirm_name": "  doomed   CLIENT co "})
with application.app_context():
    check("the right name in the wrong case deletes", db.session.get(Client, doomed_id) is None)

# Numbers wear their commas, the stage counts in the filter included.
with application.app_context():
    for i in range(1000):
        db.session.add(Client(name=f"Bulk {i:04d}", stage="follow_up"))
    db.session.commit()
html = c.get("/admin/clients").data.decode("utf-8", "replace")
check("stage counts wear their commas", "Follow up later (1,000)" in html)

r = c.post(f"/admin/leads/{ids['converted']}/stage", data={"stage": "contracted"})
with application.app_context():
    check("moving a converted lead's stage moves the client",
          db.session.get(Client, ids["cason"]).stage == "contracted"
          and db.session.get(Lead, ids["converted"]).stage == "contracted")
html = c.get("/admin/leads/?q=Kuper").data.decode("utf-8", "replace")
check("a converted lead shows the client's stage", "Contracted" in html)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All checks passed.")
sys.exit(1 if FAIL else 0)
