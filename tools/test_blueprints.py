# -*- coding: utf-8 -*-
"""Blueprints: a whole app end to end, written through the door, read back
by a session, shown in Best Practices, and opening a build prompt.

Michael, 2026-11-04: playbooks are one vendor each; a new project shaped like
one already built needs the whole plan lined up first. Proves:

  1. A session creates a blueprint through suggest_update with its build
     order; playbooks and features named by slug OR name resolve, and a name
     that matches nothing is reported back and left out.
  2. It links the My Apps tile and the business of the same name.
  3. Appending to a section and rewriting the build order apply on arrival,
     and Revert puts the build order back exactly.
  4. The door lists it and returns its text with each stage's playbooks.
  5. The Blueprints tab, its page and the Everything search show it.
  6. A package that starts from it opens its build prompt with the whole plan.

Run: python tools/test_blueprints.py
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-blueprints-")
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
from models import (db, AppBlueprint, AppLink, Business, CatalogueProposal, Client,  # noqa: E402
                    Feature, MvpPackage, Playbook, User)

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
    client = Client(name="Acme Events", email="a@example.test")
    db.session.add_all([
        boss, client,
        Playbook(slug="stripe", display_name="Stripe", one_liner="Payments", category="api"),
        Playbook(slug="app-store", display_name="App Store", one_liner="Apple", category="service"),
        Playbook(slug="railway", display_name="Railway", one_liner="Hosting", category="infrastructure"),
        Feature(slug="queue-first-sending", name="Sends that survive the request", kind="rule",
                category="platform", summary="Queue it"),
        Feature(slug="online-booking", name="Online booking", kind="feature", category="scheduling",
                summary="Book online"),
        AppLink(name="EntertainHQ", url="https://entertainhq.example.test"),
        Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub"),
    ])
    db.session.commit()
    ids = {"boss": boss.id, "client": client.id}

c = application.test_client()

print("1. A session writes one")
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "blueprint", "mode": "create", "project": "EntertainHQ",
    "payload": {
        "name": "EntertainHQ", "one_liner": "Multi-tenant booking platform with phone apps",
        "source_repos": "BuiltByBean/EntertainHQ",
        "shape_md": "Companies book talent; each company is a tenant.",
        "parts_md": "- Web app on Railway\n- Phone apps in both stores",
        "connections_md": "- Stripe -> app: a signed webhook marks the tenant paid",
        "tweaks_md": "- Tenancy on or off",
        "traps_md": "- A push token belongs to a tenant",
        "stages": [
            {"title": "Stand up Railway", "detail_md": "Repo, deploy, Postgres.",
             "playbooks": ["railway"], "features": ["Sends that survive the request"]},
            {"title": "Take money", "playbooks": ["Stripe", "Square"], "features": ["online-booking"]},
            {"title": "Ship the phone apps", "playbooks": ["App Store"]},
        ],
    }})
body = r.get_json()
check("the create applies", r.status_code == 200 and body.get("action") == "applied", body)
check("a name that matches nothing is said, not stored", body.get("unmatched") == ["playbook Square"], body)
with application.app_context():
    b = AppBlueprint.query.filter_by(slug="entertainhq").one()
    stages = b.stages.all()
    check("three stages in order", [s.title for s in stages] ==
          ["Stand up Railway", "Take money", "Ship the phone apps"], [s.title for s in stages])
    check("names and slugs both resolve to slugs",
          stages[0].playbook_list == ["railway"] and stages[0].feature_list == ["queue-first-sending"]
          and stages[1].playbook_list == ["stripe"] and stages[1].feature_list == ["online-booking"],
          [(s.playbook_list, s.feature_list) for s in stages])
    check("2. linked to the tile and the business of that name",
          b.app is not None and b.app.name == "EntertainHQ" and b.business is not None)
    check("its playbooks in build order, once each", b.playbook_slugs == ["railway", "stripe", "app-store"])

print("3. It keeps growing, and can be put back")
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "blueprint", "mode": "append", "slug": "entertainhq", "field": "traps_md",
    "text": "Apple reviews the shell, not the site.", "project": "EntertainHQ"})
check("an append to the traps applies", r.get_json().get("action") == "applied", r.get_json())
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "blueprint", "mode": "replace", "slug": "entertainhq", "field": "stages",
    "project": "EntertainHQ", "text": "",
    "payload": {"stages": [{"title": "Only one stage now", "playbooks": ["stripe"]}]}})
check("rewriting the build order applies", r.get_json().get("action") == "applied", r.get_json())
with application.app_context():
    b = AppBlueprint.query.filter_by(slug="entertainhq").one()
    check("and it is one stage", [s.title for s in b.stages.all()] == ["Only one stage now"])
    check("the traps carry the append", "Apple reviews the shell" in b.traps_md)
    pid = CatalogueProposal.query.filter_by(kind="blueprint", field="stages").one().id
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
history = c.get("/admin/features/inbox/").get_data(as_text=True)
check("History names it a Blueprint and its build order", "Blueprint" in history and "the build order" in history)
c.post(f"/admin/features/inbox/{pid}/revert")
with application.app_context():
    b = AppBlueprint.query.filter_by(slug="entertainhq").one()
    check("Revert puts the three stages back exactly",
          [(s.title, s.playbook_list) for s in b.stages.all()] ==
          [("Stand up Railway", ["railway"]), ("Take money", ["stripe"]), ("Ship the phone apps", ["app-store"])],
          [(s.title, s.playbook_list) for s in b.stages.all()])

print("4. A session reads it")
listing = c.get("/api/guidance/blueprints", headers=AUTH).get_json()
check("the door lists it", [x["slug"] for x in listing["blueprints"]] == ["entertainhq"], listing)
text = c.get("/api/guidance/blueprints/entertainhq", headers=AUTH).get_json()["blueprint"]
check("its text has every part in order",
      all(h in text for h in ("WHAT IT IS", "THE PARTS", "HOW THEY TALK", "THE BUILD ORDER",
                              "WHAT CHANGES PER PROJECT", "TRAPS BETWEEN THE SYSTEMS")), text[:400])
check("and each stage names its playbooks to fetch", "Stripe (stripe)" in text and "get_playbook" in text)
check("the door is shut without the key", c.get("/api/guidance/blueprints").status_code == 401)

print("5. Best Practices shows it")
page = c.get("/admin/blueprints/").get_data(as_text=True)
check("the Blueprints tab lists it with its count", 'data-blueprint="entertainhq"' in page
      and re.search(r"Blueprints\s*<span[^>]*>\s*1\s*</span>", page) is not None)
detail = c.get("/admin/blueprints/entertainhq").get_data(as_text=True)
check("its page has the sections and the build order",
      all(f'data-section="{k}"' in detail for k in ("shape_md", "parts_md", "connections_md", "stages",
                                                     "tweaks_md", "traps_md")) and detail.count("data-stage") == 3)
check("a stage links its playbook", "/admin/playbooks/stripe" in detail)
check("and the business map", "/map" in detail)
every = c.get("/admin/practices/").get_data(as_text=True)
check("Everything finds it", 'data-type="blueprint"' in every and "Open the blueprint" in every)
check("no em dash on any of them", all(chr(0x2014) not in x for x in (page, detail, every)))
import app_blueprints  # noqa: E402
check("a list straight under a line of prose still renders as a list",
      app_blueprints.tidy_md("Who uses it.\n- Tenants\n- Talent") == "Who uses it.\n\n- Tenants\n- Talent")

print("6. A build starts from it")
with application.app_context():
    package = MvpPackage(client_id=ids["client"], name="Acme bookings", summary="Book DJs")
    db.session.add(package)
    db.session.commit()
    pkg = package.id
    bid = AppBlueprint.query.filter_by(slug="entertainhq").one().id
form = c.get(f"/admin/mvp/{pkg}").get_data(as_text=True)
check("the package page offers Start from", "Start from" in form and "EntertainHQ" in form)
c.post(f"/admin/mvp/{pkg}", data={"name": "Acme bookings", "summary": "Book DJs", "status": "scoping",
                                 "blueprint_id": str(bid)})
prompt = c.get(f"/admin/mvp/{pkg}/prompt.txt").get_data(as_text=True)
check("the prompt opens with the whole plan, before the stack",
      "START FROM THIS BLUEPRINT" in prompt and "BLUEPRINT: EntertainHQ" in prompt
      and prompt.index("BLUEPRINT: EntertainHQ") < prompt.index("THE STACK"))
c.post(f"/admin/mvp/{pkg}", data={"name": "Acme bookings", "summary": "Book DJs", "status": "scoping",
                                 "blueprint_id": ""})
check("and Nothing takes it off", "START FROM THIS BLUEPRINT" not in
      c.get(f"/admin/mvp/{pkg}/prompt.txt").get_data(as_text=True))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
