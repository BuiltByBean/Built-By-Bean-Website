# -*- coding: utf-8 -*-
"""The Tend run's half of the board: what it reads, the maps it changes, the
gaps it files, and the run it records.

Michael, 2026-11-04: Best Practices should keep itself current and say where
one app has fallen behind another, run on his plan rather than a paid API key.
Proves:

  1. The brief carries the notes, the rules, the blueprints and the gaps he
     closed.
  2. A note is closed once, as folded, added or set aside.
  3. A map changes by a list of operations, all or nothing, lands on History
     as a Map change, and Revert puts every node and line back.
  4. Gaps are filed per app and upserted; one he closed stays closed; the Gaps
     tab, the blueprint page and the presses work.
  5. A Tend run is on History as Tend on the Max plan; a paid one says what it
     cost.

Run: python tools/test_tend.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-tend-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None

from app import create_app  # noqa: E402
from models import (db, AppBlueprint, AppGap, Business, BusinessEdge, BusinessNode,  # noqa: E402
                    CatalogueProposal, CuratorRun, Feature, Playbook, User)

application = create_app()
application.config["GUIDANCE_API_KEY"] = "test-key"
application.config["WTF_CSRF_ENABLED"] = False
AUTH = {"Authorization": "Bearer test-key"}
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq", sales_source="hub")
    db.session.add_all([
        boss, ehq,
        Feature(slug="queue-first-sending", name="Sends that survive the request", kind="rule",
                category="platform", summary="Queue it"),
        Playbook(slug="cloudflare", display_name="Cloudflare", category="infrastructure"),
        Playbook(slug="railway", display_name="Railway", category="infrastructure"),
    ])
    db.session.flush()
    site = BusinessNode(business_id=ehq.id, kind="surface", name="Marketing site", status="live",
                        surface_kind="site", role="A Next app on Railway")
    rail = BusinessNode(business_id=ehq.id, kind="service", name="Railway", status="running")
    android = BusinessNode(business_id=ehq.id, kind="surface", name="Android app", status="planned",
                           surface_kind="phone")
    db.session.add_all([site, rail, android])
    db.session.flush()
    db.session.add(BusinessEdge(business_id=ehq.id, from_node_id=site.id, to_node_id=rail.id, why="hosted"))
    e = AppBlueprint(slug="entertainhq", name="EntertainHQ", business_id=ehq.id, source_repos="BuiltByBean/EntertainHQ")
    k = AppBlueprint(slug="kuper-plumbing", name="Kuper Plumbing", source_repos="BuiltByBean/KuperPlumbing")
    db.session.add_all([e, k])
    db.session.flush()
    db.session.add(AppGap(blueprint_id=k.id, key="a-help-bot", title="A help bot", status="dismissed"))
    note = CatalogueProposal(kind="rule", mode="create", field="*", project="BuiltByBean/KuperPlumbing (swept)",
                             status="candidate", proposed="",
                             payload_json=json.dumps({"name": "Webhooks skip CSRF",
                                                      "what_went_wrong": "Twilio STOP got a 400."}))
    db.session.add(note)
    db.session.commit()
    ids = {"boss": boss.id, "note": note.id, "k": k.id}

c = application.test_client()

print("1. The brief")
brief = c.get("/api/guidance/tend", headers=AUTH).get_json()["brief"]
check("carries the note", f"NOTE #{ids['note']}" in brief and "Twilio STOP" in brief)
check("the rules and playbooks", "queue-first-sending" in brief and "cloudflare | Cloudflare" in brief)
check("the blueprints with their repos and maps", "entertainhq | EntertainHQ" in brief and "BuiltByBean/KuperPlumbing" in brief)
check("and what he closed, so it is not suggested again", "A help bot (not wanted)" in brief)
check("the door is shut without the key", c.get("/api/guidance/tend").status_code == 401)

print("2. Closing a note")
r = c.post(f"/api/guidance/notes/{ids['note']}", headers=AUTH, json={"outcome": "added", "reason": "new rule"})
check("closes as added", r.status_code == 200)
with application.app_context():
    check("and is curated", db.session.get(CatalogueProposal, ids["note"]).status == "curated")
r = c.post(f"/api/guidance/notes/{ids['note']}", headers=AUTH, json={"outcome": "discarded"})
check("a closed note is not closed twice", r.status_code == 400)

print("3. The map")
text = c.get("/api/guidance/maps/entertainhq", headers=AUTH).get_json()["map"]
check("reads as text with its lines", "Marketing site -> Railway: hosted" in text)
bad = c.post("/api/guidance/maps/entertainhq", headers=AUTH, json={"project": "tend", "changes": [
    {"op": "update_node", "node": "Android app", "status": "live"},
    {"op": "update_node", "node": "Marketing site", "status": "shipped"}]})
with application.app_context():
    android_status = BusinessNode.query.filter_by(name="Android app").one().status
check("a bad change refuses the lot", bad.status_code == 400 and android_status == "planned", (bad.get_json(), android_status))
r = c.post("/api/guidance/maps/entertainhq", headers=AUTH, json={"project": "tend", "reason": "repo", "changes": [
    {"op": "update_node", "node": "Android app", "status": "live"},
    {"op": "update_node", "node": "Marketing site", "role": "Static pages on Cloudflare"},
    {"op": "add_node", "kind": "service", "name": "Cloudflare", "playbook": "cloudflare", "status": "running"},
    {"op": "remove_edge", "from": "Marketing site", "to": "Railway"},
    {"op": "add_edge", "from": "Marketing site", "to": "Cloudflare", "why": "Pages hosts it"}]})
check("a good list applies", r.status_code == 200 and len(r.get_json()["changed"]) == 5, r.get_json())
with application.app_context():
    b = Business.query.filter_by(slug="entertainhq").one()
    names = {n.display_name: n for n in BusinessNode.query.filter_by(business_id=b.id).all()}
    edges = {(e.from_node_id, e.to_node_id) for e in BusinessEdge.query.filter_by(business_id=b.id).all()}
    check("the map says what the code says",
          names["Android app"].status == "live" and names["Cloudflare"].playbook is not None
          and (names["Marketing site"].id, names["Cloudflare"].id) in edges
          and (names["Marketing site"].id, names["Railway"].id) not in edges)
    pid = CatalogueProposal.query.filter_by(kind="map").one().id
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
history = c.get("/admin/features/inbox/").get_data(as_text=True)
check("History shows it as a Map change", "EntertainHQ map" in history and ">Map<" in history.replace(" ", ""))
c.post(f"/admin/features/inbox/{pid}/revert")
with application.app_context():
    b = Business.query.filter_by(slug="entertainhq").one()
    nodes = {n.display_name: n for n in BusinessNode.query.filter_by(business_id=b.id).all()}
    lines = {(db.session.get(BusinessNode, e.from_node_id).name, db.session.get(BusinessNode, e.to_node_id).name, e.why)
             for e in BusinessEdge.query.filter_by(business_id=b.id).all()}
    check("Revert puts every node and line back",
          set(nodes) == {"Marketing site", "Railway", "Android app"} and nodes["Android app"].status == "planned"
          and nodes["Marketing site"].role == "A Next app on Railway"
          and lines == {("Marketing site", "Railway", "hosted")}, (set(nodes), lines))

print("4. Gaps")
r = c.post("/api/guidance/gaps", headers=AUTH, json={"blueprint": "Kuper Plumbing", "project": "tend", "gaps": [
    {"title": "An outage notice to customers", "detail_md": "EntertainHQ's status Worker does it.",
     "kind": "gap", "from": "EntertainHQ"},
    {"title": "A help bot", "detail_md": "again"},
    {"title": "Offline job notes", "kind": "enhancement"}]})
body = r.get_json()
check("filed, with the closed one left closed", body.get("added") == 2 and body.get("left_closed") == 1, body)
r = c.post("/api/guidance/gaps", headers=AUTH, json={"blueprint": "kuper-plumbing", "gaps": [
    {"title": "An outage notice to customers", "detail_md": "Updated wording.", "from": "entertainhq"}]})
with application.app_context():
    g = AppGap.query.filter_by(blueprint_id=ids["k"], key="an-outage-notice-to-customers").one()
    check("a second run updates rather than duplicates", r.get_json().get("updated") == 1
          and g.detail_md == "Updated wording." and g.source.name == "EntertainHQ")
    gid = g.id
page = c.get("/admin/blueprints/gaps").get_data(as_text=True)
check("the Gaps tab lists them by app, with its count",
      'data-gap-app="kuper-plumbing"' in page and "EntertainHQ has it" in page and "Offline job notes" in page
      and "A help bot" not in page)
detail = c.get("/admin/blueprints/kuper-plumbing").get_data(as_text=True)
check("the blueprint page shows its own", 'data-section="gaps"' in detail and "An outage notice" in detail)
c.post(f"/admin/blueprints/gaps/{gid}/done", data={"next": "/admin/blueprints/gaps"})
with application.app_context():
    check("Done closes it", db.session.get(AppGap, gid).status == "done")
closed = c.get("/admin/blueprints/gaps?view=closed").get_data(as_text=True)
check("and it is on the closed view with Reopen", "An outage notice" in closed and "Reopen" in closed)
c.post("/api/guidance/gaps", headers=AUTH, json={"blueprint": "kuper-plumbing", "gaps": [
    {"title": "An outage notice to customers"}]})
with application.app_context():
    check("a later run does not reopen it", db.session.get(AppGap, gid).status == "done")

print("5. The runs")
c.post("/api/guidance/tend/runs", headers=AUTH, json={"counts": {"added": 1, "folded": 3}, "note": "maps: 1"})
with application.app_context():
    db.session.add(CuratorRun(model="claude-opus-5-5", status="ok", input_tokens=500000, output_tokens=100000))
    db.session.commit()
history = c.get("/admin/features/inbox/").get_data(as_text=True)
check("a Tend run reads as Tend on the Max plan", "Tend, Max plan" in history and "1 added, 3 folded in" in history)
check("a paid run says about what it cost", "about $4.00" in history)
check("no em dash", chr(0x2014) not in history + page + detail)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
