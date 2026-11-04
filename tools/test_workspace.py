# -*- coding: utf-8 -*-
"""The Workspace (messages, tasks, projects) and item 11, pinned.

Boots the board on a throwaway SQLite database and proves:

  1. The migration carries every note across as a task with the same id, its
     words, date, links and done day, given to Michael and already seen; drops
     notes; and the downgrade puts every one back. Up, down, up.
  2. The old addresses redirect: /admin/notes, /admin/projects, a project, its
     edit page. Every project url_for still resolves.
  3. The sidebar: Workspace second, right under Needs attention; no Notes and
     no Projects link; Client support is not lit on a task page.
  4. Tasks: a task given to Hannah counts for her until her board shows it,
     then wears New once; the drag's move answers JSON and reorders; the tick
     and the delete work; Mine shows only yours, Everyone shows all.
  5. Messages: a pair has one conversation; the unread count follows; the
     poll answers 204 when nothing is new; only the writer deletes; somebody
     not in a conversation gets a 404 on every door; a link reads live.
  6. Projects: the tab lists cards, the project page carries its task board,
     its messages and the filtered tiles.
  7. Item 11: the repo pair fills both ways, Contracted moves to MVP on the
     first commit after the contract (the Link header's last page is the
     oldest), go-live fills from a real domain that answers, and nothing moves
     a held phase, an archived project, a filled field or a platform address.

Run: python tools/test_workspace.py
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-workspace-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("GITHUB_TOKEN", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import inspect, text  # noqa: E402

from app import create_app  # noqa: E402
from models import (  # noqa: E402
    db, User, Client, Project, AppLink, SignatureRequest, WorkTask, WorkTaskPerson,
    TeamConversation, TeamMessage,
)
import project_autofill as pa  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def load_migration(name="a5d17c3e92b4_the_workspace.py"):
    path = ROOT / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location("ws_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def migrate(direction, name="a5d17c3e92b4_the_workspace.py"):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    mod = load_migration(name)
    with db.engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, direction)()


def tables():
    return set(inspect(db.engine).get_table_names())


class As:
    """A test client signed in as one person. The test runs inside one app
    context, so Flask-Login's cached user on `g` would otherwise answer
    every request as whoever asked first."""

    def __init__(self, user):
        self.c = application.test_client()
        with self.c.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True

    def __getattr__(self, name):
        method = getattr(self.c, name)

        def call(*a, **kw):
            from flask import g
            g.pop("_login_user", None)
            return method(*a, **kw)
        return call


with application.app_context():
    db.create_all()
    boss = User(username="Mbean", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    hannah = User(username="hannah", email="hb@example.test", first_name="Hannah", last_name="Bean", role="cmo")
    ty = User(username="ty", email="ty@example.test", first_name="Ty", last_name="Lane", role="cto")
    for u in (boss, hannah, ty):
        u.set_password("x")
    kuper = Client(name="Kuper Plumbing", email="k@example.test")
    db.session.add_all([boss, hannah, ty, kuper])
    db.session.flush()
    site = Project(name="Kuper site", client_id=kuper.id, status="active", phase="mvp")
    db.session.add(site)
    db.session.commit()
    BOSS, HANNAH, TY, SITE = boss.id, hannah.id, ty.id, site.id

    # ---------------------------------------------------------------- 1
    print("1. the migration carries every note across")
    # The database as production has it before this deploy: a notes table
    # with rows, and the new tables already made (empty) by create_all.
    with db.engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, body TEXT, "
            "done_at DATETIME, due_on DATE, client_id INTEGER, project_id INTEGER, product_id INTEGER, "
            "playbook_id INTEGER, created_at DATETIME, updated_at DATETIME)"))
        conn.execute(text(
            "INSERT INTO notes (id, title, body, done_at, due_on, client_id, project_id, created_at, updated_at) VALUES "
            "(4, 'Chase the deposit', 'before Friday', NULL, '2026-11-07', :c, :p, '2026-10-01 10:00:00', '2026-10-01 10:00:00'), "
            "(9, 'Renew the domain', '', NULL, NULL, NULL, NULL, '2026-10-02 10:00:00', '2026-10-02 10:00:00'), "
            "(12, 'Send the SOW', '', '2026-10-20 15:00:00', NULL, :c, NULL, '2026-10-03 10:00:00', '2026-10-20 15:00:00')"),
            {"c": kuper.id, "p": site.id})
    migrate("upgrade")
    db.session.expire_all()
    check("notes table is gone", "notes" not in tables())
    tasks = {t.id: t for t in WorkTask.query.all()}
    check("three tasks, same ids", sorted(tasks) == [4, 9, 12], sorted(tasks))
    check("open note -> Backlog with its date and links",
          tasks[4].stage == "backlog" and tasks[4].due_on == date(2026, 11, 7)
          and tasks[4].project_id == SITE and tasks[4].client_id == kuper.id and tasks[4].body == "before Friday")
    check("done note -> Done with the day it was done",
          tasks[12].stage == "done" and tasks[12].done_at.date() == date(2026, 10, 20))
    check("each given to Michael and already seen",
          all(t.person_ids == [BOSS] and t.people[0].seen_at for t in tasks.values()))
    check("projects gained build_started_on and go_live_source",
          {"build_started_on", "go_live_source"} <= {c["name"] for c in inspect(db.engine).get_columns("projects")})
    db.session.remove()
    migrate("downgrade")
    with db.engine.connect() as conn:
        rows = conn.execute(text("SELECT id, title, done_at, due_on, project_id FROM notes ORDER BY id")).fetchall()
    check("downgrade puts every note back", [r[0] for r in rows] == [4, 9, 12], rows)
    check("downgrade keeps done and the date",
          rows[2][2] is not None and rows[0][2] is None and str(rows[0][3]) == "2026-11-07" and rows[0][4] == SITE)
    check("downgrade drops the new tables", not ({"work_tasks", "team_messages"} & tables()))
    migrate("upgrade")
    db.session.remove()
    check("up again: tasks back, notes gone",
          "notes" not in tables() and sorted(t.id for t in WorkTask.query.all()) == [4, 9, 12])
    t = WorkTask(title="After the carry", created_by_id=BOSS)
    db.session.add(t)
    db.session.commit()
    check("a new task takes the next id", t.id > 12, t.id)
    db.session.delete(t)
    db.session.commit()

    c = As(db.session.get(User, BOSS))

    # ---------------------------------------------------------------- 2
    print("2. the old addresses redirect")
    for old, new in (("/admin/notes/", "/admin/workspace/tasks"),
                     ("/admin/projects", "/admin/workspace/projects"),
                     (f"/admin/projects/{SITE}", f"/admin/workspace/projects/{SITE}"),
                     (f"/admin/projects/{SITE}/edit", f"/admin/workspace/projects/{SITE}/edit"),
                     ("/admin/projects/new", "/admin/workspace/projects/new")):
        r = c.get(old)
        check(f"{old} -> {new}", r.status_code in (301, 302) and r.headers["Location"].endswith(new),
              (r.status_code, r.headers.get("Location")))
    r = c.get("/admin/projects?search=Kuper")
    check("the old search carries", "q=Kuper" in r.headers.get("Location", ""), r.headers.get("Location"))
    with application.test_request_context():
        from flask import url_for
        check("project endpoints resolve under the Workspace",
              url_for("pm.project_detail", id=SITE) == f"/admin/workspace/projects/{SITE}")
    for path in (f"/admin/workspace/projects/{SITE}", f"/admin/workspace/projects/{SITE}/edit",
                 "/admin/workspace/projects/new", "/admin/workspace/", "/admin/workspace/messages",
                 "/admin/workspace/tasks", "/admin/workspace/projects"):
        r = c.get(path, follow_redirects=True)
        check(f"{path} answers", r.status_code == 200, r.status_code)

    # ---------------------------------------------------------------- 3
    print("3. the sidebar")
    html = c.get("/admin/workspace/tasks").get_data(as_text=True)
    nav = html[html.index("<nav"):html.index("</nav>")]
    i_att, i_ws, i_work = nav.index("Needs attention"), nav.index("Workspace"), nav.index("Work</p>")
    check("Workspace sits between Needs attention and Work", i_att < i_ws < i_work)
    check("no Notes link", "/admin/notes" not in nav and ">Notes<" not in nav.replace("\n", "").replace(" ", ""))
    check("no Projects link", "/admin/projects" not in nav and "/admin/workspace/projects\"" not in nav)
    check("Client support not lit on a task page", "sidebar-link active" not in nav[nav.rindex("<a", 0, nav.index("Client support")):nav.index("Client support")])
    check("Workspace lit", 'sidebar-link active' in nav[nav.rindex("<a", 0, i_ws):i_ws])

    # ---------------------------------------------------------------- 4
    print("4. tasks")
    r = c.post("/admin/workspace/tasks/new", data={"title": "Draft the launch post", "people": [str(HANNAH)],
                                                     "project_id": str(SITE), "next": "/admin/workspace/tasks"})
    check("create answers with the board", r.status_code == 302)
    new = WorkTask.query.filter_by(title="Draft the launch post").one()
    check("task for Hannah, in Backlog, client filled from the project",
          new.person_ids == [HANNAH] and new.stage == "backlog" and new.client_id == kuper.id)
    from pm.workspace_routes import counts
    check("counts for Hannah: 1 new task", counts(HANNAH)["tasks"] == 1, counts(HANNAH))
    check("counts for Michael: none", counts(BOSS)["tasks"] == 0, counts(BOSS))
    h = As(db.session.get(User, HANNAH))
    page = h.get("/admin/workspace/tasks").get_data(as_text=True)
    check("Hannah's board shows it, marked New", "Draft the launch post" in page and ">New<" in page)
    db.session.expire_all()
    check("and it is seen now", counts(HANNAH)["tasks"] == 0)
    page = h.get("/admin/workspace/tasks").get_data(as_text=True)
    check("New only once", ">New<" not in page)
    check("Mine does not show Michael's carried notes", "Renew the domain" not in page)
    page = h.get("/admin/workspace/tasks?who=all").get_data(as_text=True)
    check("Everyone does", "Renew the domain" in page and "Draft the launch post" in page)

    r = c.post(f"/admin/workspace/tasks/{new.id}/move", data={"stage": "in_progress", "order": f"{new.id}"})
    check("move answers JSON", r.status_code == 200 and r.get_json()["stage"] == "in_progress", r.data[:200])
    r = c.post("/admin/workspace/tasks/9/move", data={"stage": "in_progress", "order": f"9,{new.id}"})
    db.session.expire_all()
    check("order lands", db.session.get(WorkTask, 9).position == 0 and db.session.get(WorkTask, new.id).position == 1)
    r = c.post("/admin/workspace/tasks/9/move", data={"stage": "nonsense"})
    check("a bad column is refused", r.status_code == 400)
    c.post("/admin/workspace/tasks/9/toggle", data={})
    db.session.expire_all()
    check("tick: done with a day", db.session.get(WorkTask, 9).stage == "done" and db.session.get(WorkTask, 9).done_at)
    c.post("/admin/workspace/tasks/9/toggle", data={})
    db.session.expire_all()
    check("tick again: back in Backlog", db.session.get(WorkTask, 9).stage == "backlog" and not db.session.get(WorkTask, 9).done_at)
    r = c.post(f"/admin/workspace/tasks/{new.id}", data={"title": "Draft the launch post", "people_present": "1"})
    db.session.expire_all()
    check("a save with nobody ticked is refused", db.session.get(WorkTask, new.id).person_ids == [HANNAH])
    c.post(f"/admin/workspace/tasks/{new.id}", data={"title": "Draft the launch post v2", "people_present": "1",
                                                      "people": [str(HANNAH), str(BOSS)], "stage": "done"})
    db.session.expire_all()
    t = db.session.get(WorkTask, new.id)
    check("save: title, two people, column", t.title.endswith("v2") and sorted(t.person_ids) == sorted([HANNAH, BOSS]) and t.stage == "done")
    r = c.get(f"/admin/workspace/tasks/{new.id}/window")
    check("the window draws", r.status_code == 200 and "Draft the launch post v2" in r.get_data(as_text=True))
    gone = WorkTask(title="Throwaway", created_by_id=BOSS)
    db.session.add(gone)
    db.session.commit()
    c.post(f"/admin/workspace/tasks/{gone.id}/delete", data={})
    check("delete", db.session.get(WorkTask, gone.id) is None)

    # ---------------------------------------------------------------- 5
    print("5. messages")
    r = c.post("/admin/workspace/messages/send", data={"to": [str(HANNAH)], "body": "Kuper wants Friday",
                                                         "link": [f"project:{SITE}", "client:999999", "nonsense"]})
    conv = TeamConversation.query.one()
    check("first send makes the pair and lands on it",
          r.status_code == 302 and r.headers["Location"].endswith(f"/messages/{conv.id}") and conv.pair_key == f"{BOSS}:{HANNAH}")
    msg = TeamMessage.query.one()
    check("only the real link is kept", [(l.kind, l.record_id) for l in msg.links] == [("project", SITE)])
    c.post("/admin/workspace/messages/send", data={"to": [str(HANNAH)], "body": "and Saturday"})
    check("the same pair is the same conversation", TeamConversation.query.count() == 1)
    check("Hannah has 2 unread", counts(HANNAH)["messages"] == 2, counts(HANNAH))
    r = c.get("/admin/workspace/messages/new?to=%d" % HANNAH)
    check("New message to Hannah opens the existing chat", r.status_code == 302 and f"/messages/{conv.id}" in r.headers["Location"])
    page = h.get(f"/admin/workspace/messages/{conv.id}").get_data(as_text=True)
    check("Hannah reads it, with the link chip", "Kuper wants Friday" in page and "Kuper site" in page)
    check("read clears her count", counts(HANNAH)["messages"] == 0)
    last = TeamMessage.query.order_by(TeamMessage.id.desc()).first().id
    r = h.get(f"/admin/workspace/messages/{conv.id}/rows?after={last}")
    check("poll with nothing new is 204", r.status_code == 204)
    r = h.post("/admin/workspace/messages/send", data={"conversation_id": str(conv.id), "body": "On it", "after": str(last)},
               headers={"X-Requested-With": "fetch"})
    body = r.get_data(as_text=True)
    check("a fetch send answers only the new rows", r.status_code == 200 and "On it" in body and "Kuper wants Friday" not in body)
    r = c.get(f"/admin/workspace/messages/{conv.id}/rows?after={last}")
    check("Michael's poll brings it", r.status_code == 200 and "On it" in r.get_data(as_text=True))
    r = h.post(f"/admin/workspace/messages/{conv.id}/delete/{msg.id}")
    check("Hannah cannot delete Michael's message", r.status_code == 404)
    r = c.post(f"/admin/workspace/messages/{conv.id}/delete/{msg.id}", headers={"X-Requested-With": "fetch"})
    check("Michael deletes his own", r.status_code == 200 and "This message was deleted." in r.get_data(as_text=True))
    t_client = As(db.session.get(User, TY))
    for path, method in ((f"/admin/workspace/messages/{conv.id}", "get"),
                         (f"/admin/workspace/messages/{conv.id}/rows", "get"),
                         (f"/admin/workspace/messages/{conv.id}/people", "post")):
        r = getattr(t_client, method)(path)
        check(f"Ty is not in it: {method} {path.rsplit('/', 1)[-1]} is 404", r.status_code == 404, r.status_code)
    r = t_client.post("/admin/workspace/messages/send", data={"conversation_id": str(conv.id), "body": "hi"})
    check("Ty cannot post into it", r.status_code == 404)
    r = c.post(f"/admin/workspace/messages/{conv.id}/people", data={"people": [str(HANNAH), str(TY)]})
    check("adding Ty to a pair starts a group", TeamConversation.query.count() == 2)
    r = c.get("/admin/workspace/links?q=Kup")
    kinds = {row["kind"] for row in r.get_json()}
    check("the link search finds the project and the client", {"project", "client"} <= kinds, kinds)
    r = h.get("/admin/workspace/links?q=Kup")
    check("the link search is open to Hannah too", r.status_code == 200)

    # ---------------------------------------------------------------- 6
    print("6. projects")
    page = c.get("/admin/workspace/projects").get_data(as_text=True)
    check("the tab lists the card", "Kuper site" in page and "Kuper Plumbing" in page)
    page = c.get("/admin/workspace/projects?q=nothing-like-it").get_data(as_text=True)
    check("a search that matches nothing says so", "No projects match that" in page)
    page = c.get(f"/admin/workspace/projects/{SITE}").get_data(as_text=True)
    check("project page: the tab row", 'data-keep="workspace-tabs"' in page)
    check("project page: its task board", 'data-live="board"' in page and "Chase the deposit" in page)
    check("project page: a deleted message about it is not listed", "Kuper wants Friday" not in page and "No messages about this project yet" in page)
    c.post("/admin/workspace/messages/send", data={"conversation_id": str(conv.id), "body": "Proof is ready",
                                                     "link": [f"project:{SITE}"]})
    page = c.get(f"/admin/workspace/projects/{SITE}").get_data(as_text=True)
    check("project page: a message linked to it is listed", "Proof is ready" in page)
    page = t_client.get(f"/admin/workspace/projects/{SITE}").get_data(as_text=True)
    check("project page: not for somebody outside that chat", "Proof is ready" not in page)
    check("project page: tiles open the filtered pages",
          f"/admin/time?project_id={SITE}" in page or f"project_id={SITE}" in page)
    check("project page: playbooks still there", "Playbooks" in page)

    # ---------------------------------------------------------------- 7
    print("7. item 11: what the repo and the domain say")
    today = date(2026, 11, 4)
    contracted = Project(name="Talent site", client_id=kuper.id, status="active", phase="contracted",
                         created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    held = Project(name="Held one", client_id=kuper.id, status="active", phase="contracted",
                   phase_locked=True, repo="mb/held")
    archived = Project(name="Old one", client_id=kuper.id, status="archived", phase="contracted", repo="mb/old")
    live_set = Project(name="Live one", client_id=kuper.id, status="active", phase="mvp", repo="mb/live",
                       go_live_date=date(2026, 3, 1))
    on_railway = Project(name="Railway only", client_id=kuper.id, status="active", phase="mvp", repo="mb/rw")
    db.session.add_all([contracted, held, archived, live_set, on_railway])
    db.session.flush()
    db.session.add(SignatureRequest(envelope_id="env-1", title="SOW", kind="sow", client_id=kuper.id,
                                    project_id=contracted.id, signer_name="K", signer_email="k@example.test",
                                    status="completed", completed_at=datetime(2026, 9, 10, 12, 0)))
    tiles = [AppLink(name="Talent", url="https://talent.example.com", project_id=contracted.id,
                     github_url="https://github.com/mb/talent"),
             AppLink(name="Held", url="https://held.example.com", project_id=held.id),
             AppLink(name="Live", url="https://live.example.com", project_id=live_set.id),
             AppLink(name="RW", url="https://rw-production.up.railway.app", project_id=on_railway.id)]
    db.session.add_all(tiles)
    db.session.commit()

    calls = []

    def fetch(path):
        calls.append(path)
        if "/repos/mb/talent/commits" in path:
            check("asks from the contract date", "since=2026-09-10" in path, path)
            if "&page=7" in path:
                return [{"commit": {"committer": {"date": "2026-09-12T18:00:00Z"}}}], {}
            return [{"commit": {"committer": {"date": "2026-11-01T18:00:00Z"}}}], \
                {"Link": '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=7>; rel="last"'}
        return [{"commit": {"committer": {"date": "2026-10-01T00:00:00Z"}}}], {}

    probed = []

    def probe(url):
        probed.append(url)
        return True

    lines = pa.run(fetch=fetch, probe=probe, today=today)
    db.session.expire_all()
    p = db.session.get(Project, contracted.id)
    check("repo filled from the tile", p.repo == "mb/talent", p.repo)
    check("Contracted -> MVP on the first commit after the contract", p.phase == "mvp")
    check("build_started_on is the OLDEST commit (Link last page)", p.build_started_on == date(2026, 9, 12), p.build_started_on)
    check("go-live filled from the answering domain", p.go_live_date == today and "talent.example.com" in (p.go_live_source or ""),
          (p.go_live_date, p.go_live_source))
    hp = db.session.get(Project, held.id)
    check("a held phase is never moved", hp.phase == "contracted" and not hp.go_live_date)
    check("the held project's tile still gets its GitHub address",
          db.session.get(AppLink, tiles[1].id).github_url == "https://github.com/mb/held")
    check("archived left alone", db.session.get(Project, archived.id).phase == "contracted")
    check("a go-live already typed is never replaced", db.session.get(Project, live_set.id).go_live_date == date(2026, 3, 1))
    check("a platform address never counts as live",
          not db.session.get(Project, on_railway.id).go_live_date and not any("railway.app" in u for u in probed))
    check("no commits asked of a held or archived project",
          not any("/mb/held/" in x or "/mb/old/" in x for x in calls), calls)
    check("the night's record says what changed", any("Talent site" in line for line in lines), lines)
    before = (p.phase, p.build_started_on, p.go_live_date)
    pa.run(fetch=fetch, probe=probe, today=today + timedelta(days=3))
    db.session.expire_all()
    p = db.session.get(Project, contracted.id)
    check("a second night changes nothing", (p.phase, p.build_started_on, p.go_live_date) == before)
    check("pure plan: delivered + live fills go-live",
          pa.plan(Project(phase="delivered", status="active", phase_locked=False, kind="client"), [], None, "https://x.com", today)
          == [("go_live_date", today, "the first day the board saw x.com answer")])
    check("pure plan: contracted + live but no commit fills nothing",
          pa.plan(Project(phase="contracted", status="active", phase_locked=False, kind="client"), [], None, "https://x.com", today) == [])
    check("repo_of / url_of round trip", pa.repo_of(pa.url_of("mb/a.b-c")) == "mb/a.b-c" and pa.repo_of("https://github.com/mb/x.git") == "mb/x")
    check("www is the same host", pa.host_of("https://www.Kuper.com/x") == "kuper.com")


    # ---------------------------------------------------------------- 8
    print("8. kinds: client builds, his own products, personal projects")
    from models import Playbook, ProjectPlaybook, TeamMessageLink, TimeEntry, ProjectFold, PRODUCT_STAGES
    me = Client(name="Michael Bean", email="michael-own@example.test")
    db.session.add(me)
    db.session.flush()
    ehq = Project(name="EntertainHQ", client_id=me.id, status="active", phase="contracted",
                  mvp_date=date(2026, 1, 1))
    piped = Project(name="Piped", client_id=me.id, status="active", phase="mvp")
    cook = Project(name="Lets Cook", client_id=me.id, status="active", phase="mvp", kind="personal")
    db.session.add_all([ehq, piped, cook])
    db.session.commit()
    EHQ = ehq.id
    with application.test_request_context():
        check("his own client row makes a product", ehq.kind_effective == "product" and piped.kind_effective == "product")
        check("anybody else's makes a client build", db.session.get(Project, SITE).kind_effective == "client")
        check("a kind set wins", cook.kind_effective == "personal")
    from project_phases import sync_project_phases
    with application.test_request_context():
        moved = sync_project_phases()
    check("a product is never marched through client phases by a date",
          db.session.get(Project, EHQ).phase == "contracted" and all(m[0].id != EHQ for m in moved))
    page = c.get("/admin/workspace/projects").get_data(as_text=True)
    work = page[page.index('data-live="results"'):]
    check("Work has a Client builds section and a My products section",
          "Client builds" in work and "My products" in work and work.index("Client builds") < work.index("My products"))
    check("a product reads its own stage, not a client phase",
          "Idea" in work[work.index("My products"):] and "Contracted" not in work[work.index("My products"):])
    check("Lets Cook is not on the work list", "Lets Cook" not in work)
    page = c.get("/admin/workspace/projects?view=personal").get_data(as_text=True)
    check("Lets Cook is on Personal", "Lets Cook" in page[page.index('data-live="results"'):])
    page = c.get(f"/admin/workspace/projects/{EHQ}").get_data(as_text=True)
    check("a product's page has the stage bar, not the phase bar",
          "Building" in page and "Free Maint" not in page and "Follow the dates again" not in page)
    check("and no time or revenue tiles", "Total hours" not in page and ">Revenue<" not in page)
    r = c.post(f"/admin/projects/{EHQ}/stage", data={"stage": "live"})
    db.session.expire_all()
    check("pressing a stage sets it", db.session.get(Project, EHQ).stage == "live")
    c.post(f"/admin/projects/{EHQ}/stage", data={"stage": "nonsense"})
    db.session.expire_all()
    check("a stage that is not one is refused", db.session.get(Project, EHQ).stage == "live")
    with application.test_request_context():
        check("a product is never moved to MVP or given a go-live by the night",
              pa.plan(db.session.get(Project, EHQ), [], date(2026, 2, 1), "https://ehq.example.com", today) == [])

    # ---------------------------------------------------------------- 9
    print("9. Workforce folds into EntertainHQ, and the downgrade puts it back")
    kenali = Client(name="Kenali Kendrick", email="kk@example.test")
    db.session.add(kenali)
    db.session.flush()
    wf = Project(name="Workforce: staff time clock, schedules, time off, pay rates and org chart",
                 client_id=kenali.id, status="active", phase="mvp", repo="mb/workforce")
    pb = Playbook(slug="stripe-test", display_name="Stripe test")
    db.session.add_all([wf, pb])
    db.session.flush()
    WF = wf.id
    wtask = WorkTask(title="Clock-in screen", project_id=WF, created_by_id=BOSS)
    db.session.add_all([wtask, ProjectPlaybook(project_id=WF, playbook_id=pb.id)])
    db.session.flush()
    msg = TeamMessage.query.first()
    db.session.add(TeamMessageLink(message_id=msg.id, kind="project", record_id=WF))
    db.session.commit()
    WTASK, PB, KEN = wtask.id, pb.id, kenali.id
    ProjectFold.query.delete()
    db.session.commit()
    db.session.remove()
    FOLD = "d3b8f6a2c915_project_kinds_and_workforce_fold.py"
    migrate("upgrade", FOLD)
    db.session.remove()
    fold = ProjectFold.query.one()
    check("nothing with money on it: Workforce is deleted", db.session.get(Project, WF) is None and fold.outcome == "deleted",
          fold.outcome)
    check("its task moved to EntertainHQ", db.session.get(WorkTask, WTASK).project_id == EHQ)
    check("its playbook checklist moved", ProjectPlaybook.query.filter_by(project_id=EHQ, playbook_id=PB).count() == 1)
    check("messages about it now link EntertainHQ",
          TeamMessageLink.query.filter_by(kind="project", record_id=EHQ).count() >= 1
          and TeamMessageLink.query.filter_by(kind="project", record_id=WF).count() == 0)
    check("the record keeps the row whole", "Workforce" in fold.project_json and str(KEN) in fold.project_json)
    db.session.remove()
    migrate("downgrade", FOLD)
    db.session.remove()
    with db.engine.connect() as conn:
        back = conn.execute(text("SELECT name, client_id, repo, status FROM projects WHERE id = :i"), {"i": WF}).first()
        task_back = conn.execute(text("SELECT project_id FROM work_tasks WHERE id = :i"), {"i": WTASK}).scalar()
        pb_back = conn.execute(text("SELECT COUNT(*) FROM project_playbooks WHERE project_id = :i"), {"i": WF}).scalar()
    check("downgrade: Workforce is back as it was", back is not None and back[1] == KEN
          and back[2] == "mb/workforce" and back[3] == "active", back)
    check("downgrade: its task and checklist went back", task_back == WF and pb_back == 1)
    check("downgrade: the kind columns are gone", "kind" not in {c["name"] for c in inspect(db.engine).get_columns("projects")})

    # Money on it this time: a time entry. Nothing billed may move clients.
    with db.engine.begin() as conn:
        conn.execute(text("INSERT INTO time_entries (project_id, client_id, date, hours, description, rate_type) "
                          "VALUES (:p, :c, '2026-10-01', 2.0, 'clock-in work', 'mvp_build')"),
                     {"p": WF, "c": KEN})
    migrate("upgrade", FOLD)
    db.session.remove()
    fold = ProjectFold.query.one()
    with db.engine.connect() as conn:
        entry_project = conn.execute(text("SELECT project_id FROM time_entries WHERE description = 'clock-in work'")).scalar()
    check("with time on it, Workforce is archived, not deleted",
          fold.outcome == "archived" and db.session.get(Project, WF).status == "archived", fold.outcome)
    check("and the time stays on Workforce, under Kenali", entry_project == WF)
    check("while the work still moved", db.session.get(WorkTask, WTASK).project_id == EHQ)
    check("the record says what stayed", "time_entries" in fold.kept_json, fold.kept_json)
    page = c.get("/admin/workspace/projects").get_data(as_text=True)
    check("an archived Workforce is off the work list", "Workforce" not in page[page.index('data-live="results"'):])
    db.session.remove()
    migrate("downgrade", FOLD)
    db.session.remove()
    with db.engine.connect() as conn:
        st = conn.execute(text("SELECT status FROM projects WHERE id = :i"), {"i": WF}).scalar()
    check("downgrade: the archived one is active again", st == "active")
    migrate("upgrade", FOLD)
    db.session.remove()

    # ---------------------------------------------------------------- 10
    print("10. a card wears its My Apps tile's icon")
    lucas = Client(name="Louis Lucas", email="ll@example.test")
    db.session.add(lucas)
    db.session.flush()
    deed = Project(name="Deed in Hand", client_id=lucas.id, status="active", phase="mvp")
    db.session.add(deed)
    db.session.flush()
    tile = AppLink(name="Deed In Hand", url="https://deedinhand.example.com", icon_file="deed.png")
    db.session.add(tile)
    db.session.commit()
    DEED, TILE = deed.id, tile.id
    page = c.get("/admin/workspace/projects").get_data(as_text=True)
    with application.test_request_context():
        from flask import url_for
        icon_url = url_for("apps.icon", id=TILE)
    check("before the night: the loose tile's icon is already on the card", icon_url in page)
    with application.test_request_context():
        lines = pa.attach_tiles(Project.query.all(), AppLink.query.all())
    db.session.commit()
    t = db.session.get(AppLink, TILE)
    check("the night attaches the tile to its project", t.project_id == DEED, lines)
    check("and keeps it in its half of My Apps", t.board_group == "mine")
    twin = AppLink(name="Deed in Hand", url="https://other.example.com")
    lone = Project(name="Lonely", client_id=lucas.id, status="active")
    db.session.add_all([twin, lone, AppLink(name="Lonely", url="https://a.example.com"),
                        AppLink(name="Lonely", url="https://b.example.com")])
    db.session.commit()
    with application.test_request_context():
        pa.attach_tiles(Project.query.all(), AppLink.query.all())
    db.session.commit()
    check("two matches is a guess, and a guess is never written",
          AppLink.query.filter_by(project_id=lone.id).count() == 0)


print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
