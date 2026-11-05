# -*- coding: utf-8 -*-
"""Which half of My Apps a tile sits in, pinned.

The board split by project: attached was Client work. On 2026-11-01 Michael
moved four attached tiles to Mine (not current client work) and Data Dungeon,
which has no client, to Client work. This boots the board on a throwaway SQLite
database and proves:

  1. A tile with no choice follows its project, as every tile did before.
  2. A choice on the tile wins over the project, both ways, on the page itself.
  3. A blank choice puts it back on the project; the edit form is gone
     (2026-11-05, "nothing should be manual"), so the drag is the way.
  4. register_app re-attaching the project does not move the tile back.
  5. The migration picks the five by project or by name, leaves everything
     else alone, and leaves a choice already made untouched.
  6. The sections are Live and earning, Building to earn and Personal
     projects (2026-11-05, three where there were two halves), in that order,
     all drawn even when empty; a tile dragged across is saved by one POST,
     and a bad group is refused.
  7. A tile dropped anywhere (2026-11-05, "move it up a row into the middle"):
     apps.order saves the half's order and the page draws it that way; a tile
     that crossed has its half written and no other tile does; bad ids and an
     unknown half are refused; signed out, nothing moves.

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
    for m in re.finditer(r"data-label=\"([^\"]+)\"|data-app-name=\"([^\"]+)\"", html):
        if m.group(1):
            current = m.group(1)
        else:
            out[m.group(2).replace("&amp;", "&").replace("&#39;", "'")] = current
    return out


print("The page")
h = halves()
check("Data Dungeon shows under Makes money", h.get("Data Dungeon") == "Live and earning", h)
check("Robinson & Co. shows under Personal projects", h.get("Robinson & Co.") == "Personal projects", h)
check("EntertainHQ still shows under Client work", h.get("EntertainHQ") == "Live and earning", h)
check("Bible Study still shows under Mine", h.get("Bible Study") == "Personal projects", h)

print("No edit form")


def choose(name, group):
    with application.app_context():
        db.session.get(AppLink, ids[name]).board_group = group
        db.session.commit()


choose("EntertainHQ", "mine")
check("a choice on the tile moves it", halves().get("EntertainHQ") == "Personal projects")
choose("EntertainHQ", None)
check("a blank puts it back on its project", halves().get("EntertainHQ") == "Live and earning")
check("the edit form is gone", c.get(f"/admin/apps/{ids['Robinson & Co.']}/edit").status_code == 404
      and c.post(f"/admin/apps/{ids['Robinson & Co.']}/edit", data={"name": "x", "url": "https://x.test"}).status_code == 404)

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
check("and back the other way", halves().get("Bible Study") == "Live and earning", halves())
r = c.post(f"/admin/apps/{ids['Bible Study']}/group", data={"group": "elsewhere"})
check("a group that does not exist is refused", r.status_code == 400 and halves().get("Bible Study") == "Live and earning")
page = c.get("/admin/apps/").data.decode("utf-8", "replace")
check("each tile has a grip that says where Enter sends it: the next section, the last wrapping",
      'aria-label="Move Data Dungeon, or press Enter to move it to Live and earning"' in page
      and 'aria-label="Move Bible Study, or press Enter to move it to Building to earn"' in page, page[:0])
check("the board posts its order to apps.order", 'data-order-url="/admin/apps/order"' in page)
check("no em dash", chr(0x2014) not in page)
c2 = application.test_client()
check("signed out, nothing moves", c2.post(f"/admin/apps/{ids['Bible Study']}/group", data={"group": "mine"}).status_code in (302, 401))

print("Three sections")
page = c.get("/admin/apps/").data.decode("utf-8", "replace")
labels = re.findall(r'data-group-section data-group="([^"]+)" data-label="([^"]+)"', page)
check("three sections, in order", labels == [("client", "Live and earning"), ("building", "Building to earn"),
                                             ("mine", "Personal projects")], labels)
check("an empty Building to earn is still drawn, as somewhere to drop",
      'data-group="building" data-label="Building to earn" data-empty' in page)
r = c.post(f"/admin/apps/{ids['Piped Dev']}/group", data={"group": "building"})
check("a tile sent to Building to earn is there", r.status_code == 200 and halves().get("Piped Dev") == "Building to earn", halves())
r = c.post("/admin/apps/order", data={"group": "building", "moved": ids["Let's Cook"],
                                      "ids": f"{ids['Let' + chr(39) + 's Cook']},{ids['Piped Dev']}"})


def in_section(label):
    html = c.get("/admin/apps/").data.decode("utf-8", "replace")
    out, current = [], None
    for m in re.finditer(r'data-label="([^"]+)"|data-app-name="([^"]+)"', html):
        if m.group(1):
            current = m.group(1)
        elif current == label:
            out.append(m.group(2).replace("&amp;", "&").replace("&#39;", "'"))
    return out


check("a tile dropped into it lands first, and the one there stays",
      r.status_code == 200 and in_section("Building to earn") == ["Let's Cook", "Piped Dev"],
      in_section("Building to earn"))
with application.app_context():
    check("and is stored as building, a value the column holds",
          db.session.get(AppLink, ids["Let's Cook"]).board_group == "building"
          and db.session.get(AppLink, ids["Let's Cook"]).section == "building")
for n in ("Let's Cook", "Piped Dev"):
    c.post(f"/admin/apps/{ids[n]}/group", data={"group": "mine"})

print("Dropping a tile anywhere")


def order(half):
    return [n for n, h in halves_in_order() if h == half]


def halves_in_order():
    html = c.get("/admin/apps/").data.decode("utf-8", "replace")
    out, current = [], None
    for m in re.finditer(r"data-label=\"([^\"]+)\"|data-app-name=\"([^\"]+)\"", html):
        if m.group(1):
            current = m.group(1)
        else:
            out.append((m.group(2).replace("&amp;", "&").replace("&#39;", "'"), current))
    return out


money = order("Live and earning")
check("there is a half to reorder", len(money) >= 2, money)
wanted = [money[-1]] + money[:-1]
r = c.post("/admin/apps/order", data={"group": "client", "moved": ids[wanted[0]],
                                      "ids": ",".join(str(ids[n]) for n in wanted)})
check("the order answers ok", r.status_code == 200 and r.get_json() == {"ok": True}, r.data)
check("and the page draws that order", order("Live and earning") == wanted, (order("Live and earning"), wanted))
with application.app_context():
    before = {a.name: a.board_group for a in AppLink.query.all()}
mine = order("Personal projects")
moving = wanted[1]
across = mine[:1] + [moving] + mine[1:]
r = c.post("/admin/apps/order", data={"group": "mine", "moved": ids[moving],
                                      "ids": ",".join(str(ids[n]) for n in across)})
check("a tile dropped in the other half lands where it was dropped",
      r.status_code == 200 and order("Personal projects") == across, (order("Personal projects"), across))
with application.app_context():
    after = {a.name: a.board_group for a in AppLink.query.all()}
check("only the tile that crossed has its half written",
      after[moving] == "mine" and all(after[n] == before[n] for n in after if n != moving),
      {n: (before[n], after[n]) for n in after if before[n] != after[n]})
check("the half it left keeps its order", order("Live and earning") == [n for n in wanted if n != moving])
bad = [{"group": "client", "ids": "999999"}, {"group": "client", "ids": "a,b"},
       {"group": "nowhere", "ids": str(ids[moving])}, {"group": "client", "ids": ""},
       {"group": "client", "ids": f"{ids[moving]},{ids[moving]}"}]
check("bad ids, an unknown half or a repeat are refused",
      all(c.post("/admin/apps/order", data=b).status_code == 400 for b in bad))
check("signed out, no order is saved",
      application.test_client().post("/admin/apps/order", data={"group": "mine", "ids": str(ids[moving])}).status_code in (302, 401))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
