# -*- coding: utf-8 -*-
"""The My Apps gap, pinned (rule: a build is not stood up until it is in My Apps).

`register_hosting_resource` used to write the cost mapping and nothing else, so every call
returned green while My Apps stayed empty - the failure the 2026-09-05 lesson describes and
the one that hid EntertainHQ on 2026-09-09. This boots the board on a throwaway SQLite
database and proves, through the same JSON door the bridge uses:

  1. register_app creates the tile, with the project attached and the repo linked.
  2. A second call for the same address UPDATES it - one tile, never two.
  3. register_hosting_resource WITH a url creates the tile (and derives the Railway link).
  4. register_hosting_resource WITHOUT a url leaves My Apps alone and SAYS SO in the reply.
  5. A tile typed in by hand earlier (same name, no project) is adopted, not duplicated.

Run: python tools/test_register_app.py
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-apps-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None          # never touch the network from a test

from app import create_app  # noqa: E402
from models import db, Client, Project, AppLink, ServiceProvider, ServiceMapping  # noqa: E402

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["GUIDANCE_API_KEY"] = "test-key"
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    client = Client(name="Test Owner", email="owner@example.test")
    db.session.add(client)
    db.session.flush()
    project = Project(name="Widget", client_id=client.id, status="active")
    db.session.add(project)
    if not ServiceProvider.query.filter_by(name="railway").first():
        db.session.add(ServiceProvider(name="railway", display_name="Railway"))
    db.session.add(AppLink(name="Old Hand-Typed", url="https://old.example.test"))
    db.session.commit()

c = application.test_client()
H = {"Authorization": "Bearer test-key"}


def post(path, body):
    r = c.post("/api/guidance/" + path, json=body, headers=H)
    return r.status_code, (r.get_json() or {})

print("REGISTER_APP:")
code, d = post("apps", {"name": "Widget", "url": "widget.example.test", "client": "Test Owner",
                        "project": "Widget", "repo": "BuiltByBean/Widget",
                        "description": "the widget"})
check("creates the tile", code == 200 and d.get("action") == "created", (code, d))
with application.app_context():
    row = AppLink.query.filter_by(name="Widget").first()
    check("with https, the project attached and the repo as a link",
          row is not None and row.url == "https://widget.example.test" and row.project_id is not None
          and row.github_url == "https://github.com/BuiltByBean/Widget", row and (row.url, row.project_id, row.github_url))
code, d = post("apps", {"name": "Widget renamed", "url": "https://widget.example.test/", "client": "Test Owner",
                        "project": "Widget"})
with application.app_context():
    n = AppLink.query.filter(AppLink.url.ilike("%widget.example.test%")).count()
check("THE POINT: the same address updates the one tile, never a second", code == 200 and d.get("action") == "updated" and n == 1, (code, d, n))

print("\nREGISTER_HOSTING_RESOURCE:")
code, d = post("hosting-resources", {"provider": "railway", "resource_identifier": "12345678-1234-1234-1234-123456789abc",
                                     "client": "Test Owner", "project": "Widget", "label": "Widget on Railway",
                                     "url": "https://gadget.example.test"})
check("with a url it creates the tile in the same call", code == 200 and (d.get("app") or {}).get("action") == "created", (code, d))
with application.app_context():
    row = AppLink.query.filter(AppLink.url.ilike("%gadget.example.test%")).first()
    check("and derives the Railway project link from the id",
          row is not None and row.railway_url == "https://railway.com/project/12345678-1234-1234-1234-123456789abc",
          row and row.railway_url)
    before = AppLink.query.count()
code, d = post("hosting-resources", {"provider": "railway", "resource_identifier": "zone-only", "client": "Test Owner",
                                     "project": "Widget", "label": "a resource with no address"})
with application.app_context():
    after = AppLink.query.count()
check("without a url My Apps is untouched", code == 200 and after == before, (code, before, after))
check("...and the reply SAYS so, instead of reading as done", "My Apps" in (d.get("note") or ""), d)

print("\nADOPTING A HAND-TYPED TILE:")
code, d = post("apps", {"name": "Old Hand-Typed", "url": "https://old.example.test", "client": "Test Owner", "project": "Widget"})
with application.app_context():
    n = AppLink.query.filter(AppLink.name.ilike("Old Hand-Typed")).count()
    row = AppLink.query.filter(AppLink.name.ilike("Old Hand-Typed")).first()
check("the existing row is updated and attached, not duplicated", d.get("action") == "updated" and n == 1 and row.project_id is not None, (d, n))

print("\nTHE DOOR:")
r = c.post("/api/guidance/apps", json={"name": "x", "url": "https://x.test", "client": "Test Owner"})
check("no bearer token, no write", r.status_code == 401, r.status_code)
code, d = post("apps", {"name": "x", "client": "Test Owner"})
check("no url, no tile - a tile without an address is not a deployed thing", code == 400, (code, d))

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
