# -*- coding: utf-8 -*-
"""One support board across every business (support_service.py).

Proves, against the real routes:

  1. The hub round trip, both ways: a client app's signed ticket and note land
     here waiting on Michael; his reply goes back down the hub as /api/hub/reply,
     a status as /api/hub/status; a note from the reporter on a resolved ticket
     reopens it and counts the reopen; a note the app marks as its own staff's
     counts as a reply and reopens nothing; a pull upserts.
  2. The desk round trip, against a fake EntertainHQ desk served over real HTTP
     with the door's own shapes (docs/SUPPORT_API.md in EntertainHQ): a pull
     makes the company's ticket, ADOPTS the Talent Booker ticket the board
     already held (J&D, shown once), and mirrors the threads; a reply pressed
     here reaches the desk as Michael's and comes back as the same note, not
     two; Resolve sends the notify choice for a company's own ticket and none
     for another app's; the status is only ever the desk's, read back.
  3. The two never cross: the hub's drains send nothing for a desk ticket, and
     Talent Booker is no longer asked directly.
  4. Who may: only the CEO answers on a desk; the app settings refuse anyone
     else and refuse a javascript: link.
  5. The page: every tab counts exactly what it shows, the sidebar badge is the
     Waiting on you tab, the tiles carry their health and links, filters work,
     and there is no em dash.

Run: python tools/test_support_board.py
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-support-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
for flag in ("HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "DESK_PULL_DISABLED", "STRIPE_IMPORT_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, jsonify, request  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import hub  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Business, Client, SupportApp, Ticket, TicketNote, User  # noqa: E402
import support_service  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# ── A fake EntertainHQ desk, speaking the door's own shapes ─────────────

DESK_KEY = "desk-key-123"
ACTING = "mb@ehq.test"
desk_calls = []
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.isoformat() if dt else None


desk_state = {
    ("jd", 5): {
        "company": "jd", "company_name": "J&D Entertainment", "id": 5, "external": False,
        "type": "bug", "type_label": "Bug Report", "status": "new", "priority": "soon",
        "reporter": "Kenali", "created_at": NOW - timedelta(hours=6),
        "updated_at": NOW - timedelta(hours=5), "resolved_at": None, "waiting_on": "team",
        "waiting_since": NOW - timedelta(hours=5), "description": "The calendar will not load on my phone.",
        "source_label": "Calendar", "source_path": "/calendar",
        "notes": [{"id": 1, "team": False, "by": "Kenali", "at": NOW - timedelta(hours=5),
                   "read": None, "body": "Still broken this morning."}],
    },
    ("hub.talent-booker", 42): {
        "company": "hub.talent-booker", "company_name": "J&D Entertainment", "id": 42, "external": True,
        "type": "feature", "type_label": "Feature Request", "status": "in-progress", "priority": "normal",
        "reporter": "Cason", "created_at": NOW - timedelta(days=3),
        "updated_at": NOW - timedelta(days=1), "resolved_at": None, "waiting_on": "reporter",
        "waiting_since": NOW - timedelta(days=1), "description": "Export the roster as a CSV.",
        "source_label": "Roster", "source_path": "/roster",
        "notes": [{"id": 900, "team": False, "by": "Cason", "at": NOW - timedelta(days=3, hours=-1),
                   "read": iso(NOW - timedelta(days=2)), "body": "Any chance of this soon?"},
                  {"id": 901, "team": True, "by": "Michael Bean", "at": NOW - timedelta(days=1),
                   "read": None, "body": "On the list for next week."}],
    },
}
desk_next_note = [1000]
desk_refuse = [False]


def summary(t, full=False):
    out = {k: t[k] for k in ("company", "company_name", "id", "external", "type", "type_label",
                             "status", "priority", "reporter", "waiting_on")}
    for k in ("created_at", "updated_at", "resolved_at", "waiting_since"):
        out[k] = iso(t[k])
    out.update({"escalated_at": None, "late": False, "followup": False, "out_of_scope": False,
                "awaiting_verification": t.get("awaiting_verification", False),
                "notes_count": len(t["notes"]),
                "desk_url": "https://entertainhq.com/admin/support/%s/%d" % (t["company"], t["id"])})
    if not full:
        out["summary"] = t["description"][:200]
        return out
    out.update({"description": t["description"], "source_label": t["source_label"],
                "source_path": t["source_path"], "reporter_email": "", "reporter_kind": "staff",
                "verification_requested_at": iso(t.get("verify_at")), "verified_at": None,
                "notes": [{"id": n["id"], "team": n["team"], "by": n["by"], "at": iso(n["at"]),
                           "read": n["read"], "body": n["body"], "via_api": False} for n in t["notes"]]})
    return out


fake = Flask("fake-desk")


def door(write=False):
    if desk_refuse[0] or request.headers.get("Authorization") != "Bearer " + DESK_KEY:
        return jsonify({"error": "unauthorised"}), 401
    who = (request.get_json(silent=True) or {}).get("acting_for") if write else request.args.get("acting_for")
    if who != ACTING:
        return jsonify({"error": "name acting_for"}), 400
    return None


@fake.route("/support/api/tickets")
def f_list():
    refused = door()
    if refused:
        return refused
    desk_calls.append(("list", dict(request.args)))
    return jsonify({"ok": True, "tickets": [summary(t) for t in desk_state.values()],
                    "out_of_scope": [], "unreadable": [], "companies": []})


@fake.route("/support/api/tickets/<company>/<int:num>")
def f_show(company, num):
    refused = door()
    if refused:
        return refused
    desk_calls.append(("show", company, num))
    t = desk_state.get((company, num))
    return (jsonify({"ok": True, "ticket": summary(t, full=True)}) if t
            else (jsonify({"error": "no such ticket"}), 404))


@fake.route("/support/api/tickets/<company>/<int:num>/reply", methods=["POST"])
def f_reply(company, num):
    refused = door(write=True)
    if refused:
        return refused
    body = request.get_json()
    desk_calls.append(("reply", company, num, body))
    t = desk_state[(company, num)]
    if t["notes"] and t["notes"][-1]["team"] and t["notes"][-1]["body"] == body["message"]:
        return jsonify({"error": "already the last reply"}), 409
    desk_next_note[0] += 1
    when = datetime.now(timezone.utc).replace(microsecond=0)
    t["notes"].append({"id": desk_next_note[0], "team": True, "by": "Michael Bean", "at": when,
                       "read": None, "body": body["message"]})
    t["waiting_on"], t["waiting_since"], t["updated_at"] = "reporter", when, when
    return jsonify({"ok": True, "words": body["message"]})


@fake.route("/support/api/tickets/<company>/<int:num>/status", methods=["POST"])
def f_status(company, num):
    refused = door(write=True)
    if refused:
        return refused
    body = request.get_json()
    desk_calls.append(("status", company, num, body))
    t = desk_state[(company, num)]
    if body["status"] == "resolved" and not t["external"] and "notify" not in body:
        return jsonify({"error": "a company's Resolve needs notify"}), 400
    if body["status"] == "resolved" and t["external"] and "notify" in body:
        return jsonify({"error": "another app's ticket takes no notify"}), 400
    when = datetime.now(timezone.utc).replace(microsecond=0)
    t["status"], t["updated_at"] = body["status"], when + timedelta(seconds=1)
    t["resolved_at"] = when if body["status"] == "resolved" else None
    t["waiting_on"] = "" if body["status"] in ("resolved", "dismissed") else "team"
    if body.get("notify") == "verify":
        t["awaiting_verification"] = True
        t["verify_at"] = when
    return jsonify({"ok": True, "words": ""})


server = make_server("127.0.0.1", 0, fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
DESK_URL = "http://127.0.0.1:%d" % server.server_port

# ── The board ───────────────────────────────────────────────────────────

application = create_app()
SECRET = "kuper-secret"
with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    cmo = User(username="hb", email="hb@example.test", first_name="Hannah", role="cmo")
    cmo.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq")
    dd = Business(name="Data Dungeon", slug="data-dungeon")
    kuper = Client(name="Cason Kuper", company="Kuper Plumbing", origin_slug="kuper",
                   ingest_secret=SECRET, origin_base_url="https://kuper.example")
    kenali = Client(name="Kenali Kendrick", origin_slug="talent-booker",
                    ingest_secret="tb-secret", origin_base_url="https://staff.jd.example")
    robinson = Client(name="Zachary Robinson", company="Robinson & Co.", origin_slug="robinson",
                      ingest_secret="rb-secret", origin_base_url="https://robinson.example")
    db.session.add_all([boss, cmo, bbb, ehq, dd, kuper, kenali, robinson])
    db.session.commit()
    robinson_id = robinson.id
    for n, who in ((501, "Kenali Kendrick"), (502, "Molly Herring")):
        db.session.add(Ticket(client_id=kenali.id, origin="talent-booker", origin_ticket_id=n,
                              description="Old J&D ticket " + str(n), status="new", reporter_name=who,
                              waiting_on="you", waiting_since=NOW - timedelta(days=66),
                              created_at=NOW - timedelta(days=67)))
    for n in (1, 2):
        db.session.add(Ticket(client_id=robinson.id, origin="robinson", origin_ticket_id=n,
                              description="Test ticket from the build " + str(n), status="new",
                              waiting_on="you", waiting_since=NOW - timedelta(days=54)))
    boss_id, cmo_id, ehq_id, bbb_id = boss.id, cmo.id, ehq.id, bbb.id
    # J&D's ticket 42, as the board held it from Talent Booker before the cutover.
    old = Ticket(client_id=kenali.id, origin="talent-booker", origin_ticket_id=42,
                 description="Export the roster as a CSV.", category="feature", status="in-progress",
                 followup_flagged=True, billing_bucket="new")
    db.session.add(old)
    db.session.flush()
    db.session.add(TicketNote(ticket_id=old.id, origin_note_id=7, body="Any chance of this soon?",
                              author_name="Cason", is_staff_reply=False,
                              created_at=NOW - timedelta(days=3, hours=-1)))
    db.session.commit()
    old_id = old.id

c = application.test_client()


def login(uid):
    with c.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True


def signed(path, payload, slug="kuper", secret=SECRET):
    body = hub.canonical(payload)
    ts, sig = hub.sign(secret, body)
    return c.post(path, data=body, content_type="application/json", headers={
        hub.ORIGIN_HEADER: slug, hub.TIMESTAMP_HEADER: ts, hub.SIGNATURE_HEADER: sig})


sent = []
real_post, real_fetch = hub.post, hub.fetch


def fake_post(base_url, path, payload, *, secret, origin_slug, timeout=10):
    sent.append((base_url, path, payload, origin_slug))
    return 200, "{}"


hub.post = fake_post

# ── 1. The hub ──────────────────────────────────────────────────────────
print("1. The hub, both ways")
r = signed("/admin/api/hub/tickets", {"ticket_id": 11, "description": "Invoice page shows the wrong total.",
                                      "category": "bug", "status": "new", "priority": "urgent",
                                      "source_label": "Invoices", "reporter_name": "Cason"})
check("a signed ticket lands", r.status_code == 201, r.get_data(as_text=True))
with application.app_context():
    t = Ticket.query.filter_by(origin="kuper", origin_ticket_id=11).one()
    check("waiting on Michael from the moment it lands", t.waiting_on == "you" and t.waiting_since is not None)
    kt_id = t.id
r = signed("/admin/api/hub/notes", {"ticket_id": 11, "note_id": 1, "body": "It is $40 too high.", "author_name": "Cason"})
check("the reporter's note lands", r.status_code == 201)

login(boss_id)
c.post(f"/admin/tickets/{kt_id}/reply", data={"body": "Found it, fixing now.", "next": "/admin/tickets"})
with application.app_context():
    t = db.session.get(Ticket, kt_id)
    check("a reply here makes it wait on them and stamps the first reply",
          t.waiting_on == "them" and t.first_reply_at is not None)
    application.deliver_pending_replies()
    application.deliver_pending_statuses()
check("the reply goes down the hub as /api/hub/reply",
      any(p == "/api/hub/reply" and pl["ticket_id"] == 11 and pl["body"] == "Found it, fixing now." for _, p, pl, _ in sent), sent)

c.post(f"/admin/tickets/{kt_id}/triage", data={"status": "resolved", "next": "/admin/tickets"})
with application.app_context():
    application.deliver_pending_statuses()
    t = db.session.get(Ticket, kt_id)
    check("resolving stamps resolved_at and clears the wait", t.resolved_at is not None and t.waiting_on == "")
check("the status goes down the hub as /api/hub/status",
      any(p == "/api/hub/status" and pl == {"ticket_id": 11, "status": "resolved"} for _, p, pl, _ in sent), sent)

signed("/admin/api/hub/notes", {"ticket_id": 11, "note_id": 2, "body": "Still wrong on the PDF.", "author_name": "Cason"})
with application.app_context():
    t = db.session.get(Ticket, kt_id)
    check("the reporter speaking on a resolved ticket reopens it and counts it",
          t.status == "in-progress" and t.reopen_count == 1 and t.waiting_on == "you" and t.resolved_at is None)
signed("/admin/api/hub/notes", {"ticket_id": 11, "note_id": 3, "body": "Looking at the PDF now.",
                                "author_name": "Cason (admin)", "is_staff_reply": True})
with application.app_context():
    t = db.session.get(Ticket, kt_id)
    note = TicketNote.query.filter_by(ticket_id=kt_id, origin_note_id=3).one()
    check("a note the app marks as its staff's is a reply: waits on them, reopens nothing",
          note.is_staff_reply and t.waiting_on == "them" and t.reopen_count == 1)
    n_before = len(sent)
    application.deliver_pending_replies()
    check("and is never sent back to the app it came from", len(sent) == n_before)

signed("/admin/api/hub/tickets", {"ticket_id": 11, "description": "Invoice page shows the wrong total.",
                                  "status": "new", "priority": "urgent", "solved": True})
with application.app_context():
    t = db.session.get(Ticket, kt_id)
    check("a re-push never overwrites the board's status", t.status == "in-progress")
    check("the customer's own 'Did this solve it?' is taken", t.said_solved is True)


def fake_fetch(base_url, path, payload, *, secret, origin_slug, timeout=20):
    sent.append((base_url, path, payload, origin_slug))
    return {"tickets": [{"ticket_id": 12, "description": "Pulled, not pushed.", "status": "new"}]}


hub.fetch = fake_fetch
with application.app_context():
    support_service.ensure_apps()
    results = application.pull_all_tickets()
    asked = [cl.origin_slug for cl, *_ in results]
    check("a pull upserts what the app has", Ticket.query.filter_by(origin="kuper", origin_ticket_id=12).count() == 1)
    check("Talent Booker is no longer asked directly (its tickets come through EntertainHQ)",
          asked == ["kuper"], asked)

# ── 2. The desk ─────────────────────────────────────────────────────────
print("2. The desk, both ways")
with application.app_context():
    app_row = SupportApp.query.filter_by(origin="entertainhq").one()
    check("EntertainHQ's desk is on the board from the defaults, under its business",
          app_row.kind == "desk" and app_row.business_id == ehq_id
          and app_row.support_url == "https://entertainhq.com/admin/support")
    check("as is Data Dungeon's", SupportApp.query.filter_by(origin="data-dungeon").count() == 1)
    app_row.desk_url, app_row.desk_acting_for = DESK_URL, ACTING
    db.session.commit()
    check("no key, not connected", not app_row.desk_ready)
    os.environ["DESK_KEY_ENTERTAINHQ"] = DESK_KEY
    check("a key on the service connects it with nothing typed", app_row.desk_ready and app_row.desk_secret == DESK_KEY)
    os.environ.pop("DESK_KEY_ENTERTAINHQ")
    app_row.desk_key = DESK_KEY
    db.session.commit()
    note = support_service.pull_desk(app_row)
    check("a pull reads the list and every thread", note.startswith("2 read, 1 new, 2 threads"), note)
    jd5 = Ticket.query.filter_by(origin="entertainhq", origin_ref="jd:5").one()
    check("the company's ticket belongs to EntertainHQ, with no client",
          jd5.business_id == ehq_id and jd5.client_id is None and jd5.priority == "soon")
    check("waiting on Michael, as the desk says", jd5.waiting_on == "you")
    check("its thread is mirrored", [n.body for n in jd5.notes] == ["Still broken this morning."])
    adopted = Ticket.query.filter_by(origin="entertainhq", origin_ref="hub.talent-booker:42").one()
    check("J&D's ticket is ADOPTED, not shown twice",
          adopted.id == old_id and Ticket.query.filter_by(origin="talent-booker", origin_ticket_id=42).count() == 0)
    check("keeping the board's own marks", adopted.followup_flagged and adopted.billing_bucket == "new")
    bodies = [(n.body, n.origin_note_id) for n in adopted.notes]
    check("its old note is matched to the desk's by words, the desk's reply added once",
          bodies == [("Any chance of this soon?", 900), ("On the list for next week.", 901)], bodies)
    check("the desk's reply is the first reply", adopted.first_reply_at is not None)
    calls = len(desk_calls)
    support_service.pull_desk(app_row)
    check("a second pull reads only the list when nothing moved", len(desk_calls) == calls + 1, desk_calls[calls:])
    jd5_id, adopted_id = jd5.id, adopted.id

login(cmo_id)
r = c.post(f"/admin/tickets/{jd5_id}/reply", data={"body": "Hannah here", "next": "/admin/tickets"})
check("only the CEO answers on a desk", not any(x[0] == "reply" for x in desk_calls))
with application.app_context():
    check("and nothing is written when refused",
          TicketNote.query.filter_by(ticket_id=jd5_id, body="Hannah here").count() == 0)

login(boss_id)
c.post(f"/admin/tickets/{jd5_id}/reply", data={"body": "Fixed in the update going out tonight.", "next": "/admin/tickets"})
replies = [x for x in desk_calls if x[0] == "reply"]
check("Michael's reply reaches the desk as his", len(replies) == 1 and replies[0][3]["message"] ==
      "Fixed in the update going out tonight." and replies[0][3]["acting_for"] == ACTING, replies)
with application.app_context():
    jd5 = db.session.get(Ticket, jd5_id)
    mine = [n for n in jd5.notes if n.is_staff_reply]
    check("and comes back as the same note, delivered, not two",
          len(mine) == 1 and mine[0].delivered_at is not None and mine[0].origin_note_id == 1001,
          [(n.body, n.origin_note_id) for n in jd5.notes])
    check("now waiting on them, as the desk says", jd5.waiting_on == "them")
    n_before = len(sent)
    application.deliver_pending_replies()
    application.deliver_pending_statuses()
    desk_sends = [x for x in sent[n_before:] if x[0] == "https://staff.jd.example" or x[3] != "kuper"]
    check("the hub's drains never send a desk ticket", not desk_sends, desk_sends)

c.post(f"/admin/tickets/{jd5_id}/triage", data={"status": "resolved", "notify": "verify", "next": "/admin/tickets"})
st = [x for x in desk_calls if x[0] == "status"]
check("Resolve on a company's ticket sends the notify choice", st and st[-1][3] == {
    "status": "resolved", "notify": "verify", "acting_for": ACTING}, st)
with application.app_context():
    jd5 = db.session.get(Ticket, jd5_id)
    check("the status is the desk's, read back, with when it was fixed and that they were asked",
          jd5.status == "resolved" and jd5.resolved_at is not None and jd5.verify_requested_at is not None)

c.post(f"/admin/tickets/{adopted_id}/triage", data={"status": "resolved", "notify": "tell", "next": "/admin/tickets"})
st = [x for x in desk_calls if x[0] == "status"]
check("Resolve on another app's ticket sends no notify", st[-1][3] == {"status": "resolved", "acting_for": ACTING}, st[-1])
c.post(f"/admin/tickets/{adopted_id}/triage", data={"priority": "urgent", "category": "bug", "next": "/admin/tickets"})
with application.app_context():
    a = db.session.get(Ticket, adopted_id)
    check("kind and priority are the desk's, never changed here", a.priority == "normal" and a.category == "feature")
c.post(f"/admin/tickets/{adopted_id}/triage", data={"billing_bucket": "maintenance", "billed_minutes": "30", "next": "/admin/tickets"})
with application.app_context():
    a = db.session.get(Ticket, adopted_id)
    check("billing stays here", a.billing_bucket == "maintenance" and a.billed_minutes == 30)

desk_refuse[0] = True
with application.app_context():
    app_row = SupportApp.query.filter_by(origin="entertainhq").one()
    note = support_service.pull_desk(app_row)
    check("a refused key is said, and nothing is lost", note.startswith("401") and
          Ticket.query.filter_by(origin="entertainhq").count() == 2, note)
r = c.post(f"/admin/tickets/{adopted_id}/reply", data={"body": "Shipping Friday.", "next": "/admin/tickets"})
with application.app_context():
    stuck = TicketNote.query.filter_by(ticket_id=adopted_id, body="Shipping Friday.").one()
    check("a reply the desk refused stays on the thread, not sent", stuck.delivered_at is None)
    n_before = len(sent)
    application.deliver_pending_replies()
    check("and the hub never picks it up for Talent Booker",
          not [x for x in sent[n_before:] if x[0] == "https://staff.jd.example"], sent[n_before:])
desk_refuse[0] = False
with application.app_context():
    s_, f_ = support_service.deliver_desk_replies()
    stuck = TicketNote.query.filter_by(ticket_id=adopted_id, body="Shipping Friday.").one()
    check("the desk retry sends it once the desk answers", s_ == 1 and stuck.delivered_at is not None
          and stuck.origin_note_id is not None, (s_, f_))
    support_service.pull_desk(SupportApp.query.filter_by(origin="entertainhq").one())

# ── 3. Health ───────────────────────────────────────────────────────────
print("3. Health")
with application.app_context():
    rows = support_service.apps()
    h = support_service.health(rows)
    e = h["entertainhq"]
    check("first reply and time to fix are measured", e["first_reply"] is not None and e["fix"] is not None, e)
    check("asked to confirm is counted", e["confirmed"] == (0, 1), e["confirmed"])
    k = h["kuper"]
    check("a reopen shows in the rate", k["reopen"] == 1.0, k)
    check("a said-solved answer shows", k["solved"] == (1, 1), k["solved"])
    check("spans read as people say them", support_service.span(timedelta(minutes=40)) == "40m"
          and support_service.span(timedelta(hours=5)) == "5h" and support_service.span(timedelta(days=3)) == "3d")

# ── 4. Who may ──────────────────────────────────────────────────────────
print("4. Who may")
with application.app_context():
    ehq_app_id = SupportApp.query.filter_by(origin="entertainhq").one().id
login(cmo_id)
r = c.get(f"/admin/tickets/apps/{ehq_app_id}")
check("the app settings refuse anyone but the CEO", r.status_code == 302)
login(boss_id)
r = c.get(f"/admin/tickets/apps/{ehq_app_id}")
page = r.get_data(as_text=True)
check("the CEO sees the settings, and the key is never shown", r.status_code == 200 and DESK_KEY not in page)
c.post(f"/admin/tickets/apps/{ehq_app_id}", data={
    "name": "EntertainHQ", "support_url": "javascript:alert(1)", "admin_url": "https://entertainhq.com/admin",
    "site_url": "https://entertainhq.com", "status_url": "https://status.entertainhq.com",
    "desk_url": DESK_URL, "desk_acting_for": ACTING, "business_id": str(ehq_id), "desk_key": "",
    "supported": "1"})
with application.app_context():
    a = db.session.get(SupportApp, ehq_app_id)
    check("a javascript: link is refused, a blank key keeps the one on file",
          a.support_url == "" and a.desk_key == DESK_KEY)
    a.support_url = "https://entertainhq.com/admin/support"
    db.session.commit()

# ── 5. Off the board ────────────────────────────────────────────────────
print("5. Off the board")
with application.app_context():
    support_service.ensure_apps()
    rob = SupportApp.query.filter_by(origin="robinson").one()
    check("an app wired during a build that was never contracted starts off the board",
          rob.supported is False and not rob.on_board)
    rob_id = rob.id
    check("Talent Booker is off the board, its tickets coming through EntertainHQ's desk",
          not SupportApp.query.filter_by(origin="talent-booker").one().on_board)
    hidden = support_service.on_board(Ticket.query).filter(Ticket.origin.in_(("talent-booker", "robinson"))).count()
    check("their rows are on no tab and in no count", hidden == 0)
    check("but kept", Ticket.query.filter(Ticket.origin.in_(("talent-booker", "robinson"))).count() == 4)
    asked = [cl.origin_slug for cl, *_ in application.pull_all_tickets()]
    check("and neither app is asked for tickets", "robinson" not in asked and "talent-booker" not in asked, asked)
page = c.get("/admin/tickets?status=all").get_data(as_text=True)
check("no Talent Booker or Robinson rows, no Robinson tile",
      "Old J&D ticket" not in page and "Test ticket from the build" not in page and ">Robinson & Co.</span>" not in page)
check("the way back to an off-board app is its settings", f'/admin/tickets/apps/{rob_id}"' in page)
c.post(f"/admin/tickets/apps/{rob_id}", data={"name": "Robinson & Co.", "supported": "1"})
page = c.get("/admin/tickets?status=all").get_data(as_text=True)
check("switching it on brings its tile and rows back", "Test ticket from the build" in page)
c.post(f"/admin/tickets/apps/{rob_id}", data={"name": "Robinson & Co."})
with application.app_context():
    check("and off again", not db.session.get(SupportApp, rob_id).supported)

# ── 6. The row ──────────────────────────────────────────────────────────
print("6. The row")
page = c.get("/admin/tickets?status=all").get_data(as_text=True)
check("no Save button anywhere on the board", ">Save<" not in page)
check("triage applies on the pick", "requestSubmit()" in page)
with application.app_context():
    k13 = Ticket.query.filter_by(origin="kuper", origin_ticket_id=13).first()
    k13_id = k13.id if k13 else None
if k13_id is None:
    signed("/admin/api/hub/tickets", {"ticket_id": 13, "description": "Second open one.", "status": "new"})
    with application.app_context():
        k13_id = Ticket.query.filter_by(origin="kuper", origin_ticket_id=13).one().id
nxt = f"/admin/tickets?status=waiting&keep={k13_id}"
r = c.post(f"/admin/tickets/{k13_id}/triage", data={"priority": "soon", "next": nxt})
check("a pick lands back on the page it was made on", r.status_code == 302 and r.headers["Location"].endswith(nxt))
c.post(f"/admin/tickets/{k13_id}/triage", data={"status": "resolved", "next": nxt})
page = c.get(nxt).get_data(as_text=True)
check("a row whose change took it out of the tab is still in that answer, showing what is now true",
      f'data-live="ticket-{k13_id}"' in page and "Resolved" in page)
plain = c.get("/admin/tickets?status=waiting").get_data(as_text=True)
check("and the next look drops it", f'data-live="ticket-{k13_id}"' not in plain)
c.post(f"/admin/tickets/{k13_id}/triage", data={"status": "new", "next": nxt})

# ── 7. The page ─────────────────────────────────────────────────────────
print("7. The page")
signed("/admin/api/hub/tickets", {"ticket_id": 13, "description": "Second open one.", "status": "new"})
import re  # noqa: E402

for tab in ("waiting", "open", "follow-up", "resolved", "out-of-scope", "all"):
    page = c.get(f"/admin/tickets?status={tab}").get_data(as_text=True)
    cards = page.count('data-live-key="ticket-')
    m = re.search(r'status=' + tab + r'[^"]*"[^>]*>\s*[^<]*?(?:<span class="[^"]*opacity-70">([\d,]+)</span>)?\s*</a>', page)
    shown = int(m.group(1)) if m and m.group(1) else 0
    check(f"the {tab} tab counts exactly what it shows ({cards})", shown == cards, (shown, cards))

page = c.get("/admin/tickets").get_data(as_text=True)
with application.app_context():
    waiting = support_service.waiting_count()
badge = re.search(r'data-live="nav-support"[^>]*>\s*<span[^>]*>(\d+)</span>', page)
check("the sidebar badge is the Waiting on you tab", badge and int(badge.group(1)) == waiting
      == page.count('data-live-key="ticket-'), (badge and badge.group(1), waiting))
check("it opens on Waiting on you", "Waiting on you" in page)
check("a tile per app, not Talent Booker on its own", "EntertainHQ" in page and "Kuper Plumbing" in page
      and "Data Dungeon" in page and 'truncate">Talent Booker</span>' not in page)
check("the tiles carry the quick links", 'href="https://status.entertainhq.com"' in page
      and 'href="https://kuper.example/admin/tickets"' in page)
check("a desk not connected says so", "Desk not connected" in page)

page = c.get(f"/admin/tickets?status=all&business={ehq_id}").get_data(as_text=True)
check("the business filter keeps EntertainHQ's alone", page.count('data-live-key="ticket-') == 2, page.count('data-live-key="ticket-'))
page = c.get(f"/admin/tickets?status=all&business={bbb_id}").get_data(as_text=True)
check("Built by Bean's are its clients' tickets", page.count('data-live-key="ticket-') == 3, page.count('data-live-key="ticket-'))
page = c.get("/admin/tickets?status=all&app=kuper").get_data(as_text=True)
check("the app filter", page.count('data-live-key="ticket-') == 3)

detail = c.get(f"/admin/tickets/{jd5_id}").get_data(as_text=True)
check("a desk ticket's page opens, with its desk's buttons and no edit", "On its desk" in detail and "Edit ticket" not in detail)
r = c.get(f"/admin/tickets/{jd5_id}/edit")
check("and its edit form sends you back", r.status_code == 302)
dash = c.get("/admin/")
check("the dashboard still renders", dash.status_code in (200, 302))

dash_texts = [c.get(u).get_data(as_text=True) for u in ("/admin/tickets", f"/admin/tickets/apps/{ehq_app_id}", f"/admin/tickets/{jd5_id}")]
check("no em dash on any of it", all(chr(0x2014) not in t for t in dash_texts))
src = "".join(open(ROOT / p, encoding="utf-8").read() for p in (
    "support_service.py", "pm/support_routes.py", "templates/pm/tickets/list.html",
    "templates/pm/tickets/app_form.html", "migrations/versions/c6d2a8f41e97_one_support_board.py"))
check("nor in the source", chr(0x2014) not in src)

hub.post, hub.fetch = real_post, real_fetch
server.shutdown()
print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
