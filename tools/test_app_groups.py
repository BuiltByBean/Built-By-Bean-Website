# -*- coding: utf-8 -*-
"""Which half of My Apps a tile sits in, pinned.

The board split by project: attached was Client work. On 2026-11-01 Michael
moved four attached tiles to Mine (not current client work) and Data Dungeon,
which has no client, to Client work. This boots the board on a throwaway SQLite
database and proves:

  1. A tile with no choice follows its project, as every tile did before.
  2. A choice on the tile wins over the project, both ways, on the page itself.
  3. The edit form saves the choice, and a blank puts it back on the project.
  4. register_app re-attaching the project does not move the tile back.
  5. The migration picks the five by project or by name, leaves everything
     else alone, and leaves a choice already made untouched.
  6. The halves are named "Makes money" and "Personal projects" (2026-11-04),
     a tile dragged across is saved by one POST, and a bad group is refused.

Run: python tools/test_app_groups.py
"""
import importlib.util
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-groups-")
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
from models import db, Client, Project, AppLink, User  # noqa: E402

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["GUIDANCE_API_KEY"] = "test-key"
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    zach = Client(name="Zachary Robinson", email="z@example.test")
    lucas = Client(name="Lucas Miller", email="l@example.test")
    me = Client(name="Michael Bean", email="m@example.test")
    db.session.add_all([boss, zach, lucas, me])
    db.session.flush()
    projects = {n: Project(name=n, client_id=c.id, status="active") for n, c in (
        ("Robinsonandco Project Manager", zach), ("Christ Community Church", lucas),
        ("Lets Cook", me), ("Piped", me), ("EntertainHQ", me))}
    db.session.add_all(projects.values())
    db.session.flush()
    tiles = {
        "Robinson & Co.": AppLink(name="Robinson & Co.", url="https://robinsonandco.example.test",
                                  project_id=projects["Robinsonandco Project Manager"].id),
        "Christ Community Church": AppLink(name="Christ Community Church", url="https://ccc.example.test",
                                           project_id=projects["Christ Community Church"].id),
        "Let's Cook": AppLink(name="Let's Cook", url="https://letscook.example.test",
                              project_id=projects["Lets Cook"].id),
        "Piped Dev": AppLink(name="Piped Dev", url="https://piped.example.test",
                             project_id=projects["Piped"].id),
        "EntertainHQ": AppLink(name="EntertainHQ", url="https://entertainhq.example.test",
                               project_id=projects["EntertainHQ"].id),
        "Data Dungeon": AppLink(name="Data Dungeon", url="https://datadungeon.io"),
        "Bible Study": AppLink(name="Bible Study", url="/Bible-Study"),
    }
    db.session.add_all(tiles.values())
    db.session.commit()
    ids = {k: v.id for k, v in tiles.items()}
    boss_id = boss.id

    print("Before any choice")
    check("an attached tile is client work", tiles["Robinson & Co."].is_client_work)
    check("an unattached tile is mine", not tiles["Data Dungeon"].is_client_work)

    print("The migration")
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/a4c8e1f37b25_which_half_of_my_apps.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    db.session.get(AppLink, ids["Bible Study"]).board_group = "client"  # a choice made by hand
    db.session.commit()
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()
    got = {k: db.session.get(AppLink, i).board_group for k, i in ids.items()}
    check("the four go to Mine", all(got[k] == "mine" for k in
                                     ("Robinson & Co.", "Christ Community Church", "Let's Cook", "Piped Dev")), got)
    check("Data Dungeon goes to Client work", got["Data Dungeon"] == "client", got)
    check("EntertainHQ is left to follow its project", got["EntertainHQ"] is None, got)
    check("a choice already made is left alone", got["Bible Study"] == "client", got)
    db.session.get(AppLink, ids["Bible Study"]).board_group = None
    db.session.commit()

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True


def halves():
    html = c.get("/admin/apps/").data.decode("utf-8", "replace")
    out, current = {}, None
    for m in re.finditer(r"uppercase tracking-wider text-white/40\">([^<]+)<|aria-label=\"Edit ([^\"]+)\"", html):
        if m.group(1):
            current = m.group(1)
        else:
            out[m.group(2).replace("&amp;", "&").replace("&#39;", "'")] = current
    return out


print("The page")
h = halves()
check("Data Dungeon shows under Makes money", h.get("Data Dungeon") == "Makes money", h)
check("Robinson & Co. shows under Personal projects", h.get("Robinson & Co.") == "Personal projects", h)
check("EntertainHQ still shows under Client work", h.get("EntertainHQ") == "Makes money", h)
check("Bible Study still shows under Mine", h.get("Bible Study") == "Personal projects", h)

print("The edit form")


def save(name, group):
    with application.app_context():
        link = db.session.get(AppLink, ids[name])
        form = {"name": link.name, "url": link.url, "project_id": link.project_id or "",
                "board_group": group}
    return c.post(f"/admin/apps/{ids[name]}/edit", data=form)


r = save("EntertainHQ", "mine")
check("choosing Mine saves", r.status_code in (302, 303) and halves().get("EntertainHQ") == "Personal projects", r.status_code)
save("EntertainHQ", "")
check("a blank puts it back on its project", halves().get("EntertainHQ") == "Makes money")
form_html = c.get(f"/admin/apps/{ids['Robinson & Co.']}/edit").data.decode("utf-8", "replace")
check("the form offers the choice", "Shows under" in form_html and "Follows the project" in form_html)

print("register_app")
r = c.post("/api/guidance/apps", headers={"Authorization": "Bearer test-key"},
           json={"name": "Robinson & Co.", "url": "https://robinsonandco.example.test",
                 "client": "Zachary Robinson", "project": "Robinsonandco Project Manager"})
check("re-registering with its project answers 200", r.status_code == 200, r.get_json())
check("and the tile stays under Mine", halves().get("Robinson & Co.") == "Personal projects", halves())

print("Dragging a tile across")
r = c.post(f"/admin/apps/{ids['Data Dungeon']}/group", data={"group": "mine"})
check("the move answers ok", r.status_code == 200 and r.get_json() == {"ok": True, "group": "mine"}, r.data)
check("and the tile is under Personal projects", halves().get("Data Dungeon") == "Personal projects", halves())
r = c.post(f"/admin/apps/{ids['Bible Study']}/group", data={"group": "client"})
check("and back the other way", halves().get("Bible Study") == "Makes money", halves())
r = c.post(f"/admin/apps/{ids['Bible Study']}/group", data={"group": "elsewhere"})
check("a group that does not exist is refused", r.status_code == 400 and halves().get("Bible Study") == "Makes money")
page = c.get("/admin/apps/").data.decode("utf-8", "replace")
check("each tile has a grip that says where it goes",
      'aria-label="Move Data Dungeon to Makes money"' in page and 'aria-label="Move Bible Study to Personal projects"' in page)
check("no em dash", chr(0x2014) not in page)
c2 = application.test_client()
check("signed out, nothing moves", c2.post(f"/admin/apps/{ids['Bible Study']}/group", data={"group": "mine"}).status_code in (302, 401))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
