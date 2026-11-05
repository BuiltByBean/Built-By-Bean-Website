# -*- coding: utf-8 -*-
"""retire_app: something torn down comes off the board through the door.

2026-11-05: Personal Trainer and Dom's Painting were deleted on Railway and
their My Apps tiles stayed, because only a signed-in press could take a tile
off. This boots the board on a throwaway SQLite database and proves:

  1. The door refuses without a reason, without anything to match, with a
     Railway project that is not an id, and without the key.
  2. By Railway project id: the tile whose railway_url names it is deleted with
     its site check and icon file, the hosting mapping is switched off (not
     deleted), the Railway rows go, and the board project is untouched.
  3. By url and by name: the matching tile goes and every other tile stays.
  4. The answer carries the removed tile whole.
  5. Nothing matching is a 404 that changes nothing.
  6. The nightly site check drops an address no tile points at any more.

Run: python tools/test_retire_app.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-retire-")
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
from models import (db, AppLink, Client, Project, RailwayService, ServiceMapping,  # noqa: E402
                    ServiceProvider, SiteCheck)
from pm.apps_routes import _icon_folder  # noqa: E402
import live_watch  # noqa: E402

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["GUIDANCE_API_KEY"] = "test-key"
FAIL = []
PT = "b92c8fd3-7681-4bb8-aa1a-28c6eded811f"
H = {"Authorization": "Bearer test-key"}


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    me = Client(name="Michael Bean", email="m@example.test")
    db.session.add(me)
    db.session.flush()
    gym = Project(name="Gym Ecosystem", client_id=me.id, status="active")
    db.session.add(gym)
    rail = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    db.session.add(rail)
    db.session.flush()
    os.makedirs(_icon_folder(), exist_ok=True)
    with open(os.path.join(_icon_folder(), "pt.png"), "wb") as fh:
        fh.write(b"png")
    db.session.add_all([
        AppLink(name="Personal Trainer", url="https://personal-trainer-production.up.railway.app",
                railway_url=f"https://railway.com/project/{PT}", project_id=gym.id, icon_file="pt.png",
                github_url="https://github.com/BuiltByBean/Personal-Trainer"),
        AppLink(name="Dom's Painting", url="https://web-production-683cb.up.railway.app"),
        AppLink(name="Gym Ecosystem", url="https://gym-ecosystem-production.up.railway.app"),
        AppLink(name="Kuper Plumbing", url="https://kuperplumbing.com"),
        ServiceMapping(provider_id=rail.id, resource_identifier=f"railway:{PT}",
                       resource_label="Personal Trainer", client_id=me.id, is_active=True),
        ServiceMapping(provider_id=rail.id, resource_identifier="railway:1cc3acfd-f801-4fc2-8c4a-13f4f42945e1",
                       resource_label="Gym Ecosystem", client_id=me.id, is_active=True),
        RailwayService(provider_id=rail.id, project_ref=PT, project_name="Personal Trainer",
                       service_ref="s-pt", service_name="Personal-Trainer"),
        RailwayService(provider_id=rail.id, project_ref=PT, project_name="Personal Trainer",
                       service_ref="s-pt-db", service_name="Postgres"),
        RailwayService(provider_id=rail.id, project_ref="p-gym", project_name="Gym Ecosystem",
                       service_ref="s-gym", service_name="gym-ecosystem"),
        SiteCheck(url="https://personal-trainer-production.up.railway.app", host="personal-trainer-production.up.railway.app",
                  fail_nights=3),
        SiteCheck(url="https://kuperplumbing.com", host="kuperplumbing.com"),
    ])
    db.session.commit()
    gym_id = gym.id

c = application.test_client()


def post(body, headers=H):
    r = c.post("/api/guidance/apps/retire", json=body, headers=headers)
    return r.status_code, r.get_json(silent=True) or {}


print("1. REFUSALS")
code, _ = post({"railway_project": PT}, headers={})
check("no key, no door", code == 401, code)
code, out = post({"railway_project": PT})
check("a reason is required", code == 400 and "reason" in out.get("error", ""), out)
code, out = post({"reason": "gone"})
check("something to match is required", code == 400, out)
code, out = post({"railway_project": "not-an-id", "reason": "gone"})
check("a Railway project must be an id", code == 400, out)
with application.app_context():
    check("and none of that changed anything", AppLink.query.count() == 4)

print("\n2. BY RAILWAY PROJECT")
code, out = post({"railway_project": PT, "reason": "deleted on Railway, folded into Gym Ecosystem"})
check("answers 200", code == 200, (code, out))
with application.app_context():
    check("the tile that named the project is gone",
          AppLink.query.filter_by(name="Personal Trainer").count() == 0)
    check("its icon file went with it", not os.path.exists(os.path.join(_icon_folder(), "pt.png")))
    check("its site check went with it, so no 'down' row is left",
          SiteCheck.query.filter(SiteCheck.url.like("%personal-trainer%")).count() == 0)
    m = ServiceMapping.query.filter_by(resource_identifier=f"railway:{PT}").one()
    check("its hosting mapping is switched off, not deleted", m.is_active is False)
    check("another project's mapping is untouched",
          ServiceMapping.query.filter_by(resource_label="Gym Ecosystem").one().is_active is True)
    check("the Railway rows for that project are gone, and only those",
          RailwayService.query.filter_by(project_ref=PT).count() == 0
          and RailwayService.query.filter_by(project_ref="p-gym").count() == 1)
    check("the board project the tile hung on is untouched", db.session.get(Project, gym_id) is not None)
    check("every other tile stays", AppLink.query.count() == 3)
removed = (out.get("removed_apps") or [{}])[0]
check("the answer carries the tile whole, enough to register it again",
      removed.get("name") == "Personal Trainer" and removed.get("github_url", "").endswith("Personal-Trainer")
      and removed.get("project") == "Gym Ecosystem" and out.get("railway_rows_removed"), out)

print("\n3. BY URL AND BY NAME")
code, out = post({"url": "web-production-683cb.up.railway.app/", "reason": "Railway project deleted"})
with application.app_context():
    check("by url: the tile on that host is gone",
          code == 200 and AppLink.query.filter_by(name="Dom's Painting").count() == 0, out)
    check("and Gym Ecosystem, another Railway address, stays",
          AppLink.query.filter_by(name="Gym Ecosystem").count() == 1)
code, out = post({"name": "kuper plumbing", "reason": "test"})
with application.app_context():
    check("by name, any case", code == 200 and AppLink.query.filter_by(name="Kuper Plumbing").count() == 0, out)

print("\n4. NOTHING MATCHES")
code, out = post({"url": "https://nowhere.example.test", "reason": "test"})
with application.app_context():
    check("is a 404 and changes nothing", code == 404 and AppLink.query.count() == 1, (code, out))

print("\n5. THE NIGHTLY SITE CHECK FORGETS AN ADDRESS NOTHING POINTS AT")
with application.app_context():
    db.session.add(SiteCheck(url="https://orphan.example.test", host="orphan.example.test", fail_nights=5))
    db.session.commit()
    answer = type("Answer", (), {"status_code": 200, "url": None})
    live_watch.check_sites(get=lambda url: answer(), cert=lambda host: None)
    left = sorted(s.url for s in SiteCheck.query.all())
    check("only the tile still on the board keeps a check",
          left == ["https://gym-ecosystem-production.up.railway.app"], left)

print()
print(f"{len(FAIL)} FAILED: " + "; ".join(FAIL) if FAIL else "ALL PASS")
sys.exit(1 if FAIL else 0)
