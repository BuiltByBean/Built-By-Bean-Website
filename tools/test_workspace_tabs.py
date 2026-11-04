# -*- coding: utf-8 -*-
"""Pressing a Workspace tab swaps the panel under it and nothing else.

Michael, 2026-11-04: the Messages / Tasks / Projects switch "reloads parts of
the page that do not change", against his rule "Only the thing that changed
re-renders". This drives a real browser, the way test_shell_stays_put does,
because after the dust settles the page is right either way: what is being
tested is whether the SAME ELEMENTS are still there.

What is proved, at 1600 and at 375 wide:

  1. A tab press keeps the tab row, the banner's title and subtitle, the page
     (#pm-main, so its entry animation does not play again), the sidebar and
     the window, and slides the tab row's mark; the URL and the panel change.
  2. Mine / Everyone and Work / Personal / Archived keep their own switch and
     the bar it sits in; only the rows move.
  3. Opening a project from its card keeps the tab row and the page.
  4. A project's Tasks / Playbooks / Messages switch fetches nothing.
  5. Picking another chat keeps the conversation list.

Run: python tools/test_workspace_tabs.py
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-wstabs-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("RAILWAY_ENVIRONMENT", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("  FAIL playwright is installed, so the Workspace was actually driven")
    print("\n1 FAILED: this suite tests a browser and could not start one")
    sys.exit(1)

from app import create_app  # noqa: E402
from models import (  # noqa: E402
    db, Client, Project, User, WorkTask, WorkTaskPerson, TeamConversation,
    TeamConversationMember, TeamMessage,
)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", last_name="Bean", role="cmo")
    boss.set_password("password")
    hannah.set_password("password")
    client = Client(name="Tabs Test Ltd", email="tabs@example.test")
    db.session.add_all([boss, hannah, client])
    db.session.flush()
    project = Project(name="Tabs Test Site", client_id=client.id, phase="mvp",
                      created_at=datetime.now(timezone.utc))
    db.session.add(project)
    db.session.flush()
    for n in range(4):
        t = WorkTask(title=f"Probe task {n}", created_by_id=boss.id, project_id=project.id)
        db.session.add(t)
        db.session.flush()
        db.session.add(WorkTaskPerson(task_id=t.id, user_id=boss.id if n % 2 else hannah.id,
                                      seen_at=datetime.now(timezone.utc)))
    convs = []
    for title in ("First chat", "Second chat"):
        c = TeamConversation(title=title, created_by_id=boss.id, last_message_at=datetime.now(timezone.utc))
        db.session.add(c)
        db.session.flush()
        for uid in (boss.id, hannah.id):
            db.session.add(TeamConversationMember(conversation_id=c.id, user_id=uid))
        db.session.add(TeamMessage(conversation_id=c.id, author_id=hannah.id, body=f"Hello in {title}"))
        convs.append(c.id)
    db.session.commit()
    PROJECT, CONVS = project.id, convs

threading.Thread(
    target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
    daemon=True).start()

STAMP = """() => {
  const mark = (el, v) => { if (el) el.__witness = v; };
  mark(document.querySelector('[data-keep="workspace-tabs"]'), 'TABS');
  mark(document.getElementById('pm-main'), 'MAIN');
  mark(document.getElementById('pm-page-title'), 'TITLE');
  mark(document.getElementById('pm-page-subtitle'), 'SUBTITLE');
  mark(document.querySelector('aside'), 'SIDEBAR');
  window.__ctx = 'ALIVE';
  return true;
}"""

READ = """() => {
  const nav = document.querySelector('[data-keep="workspace-tabs"]');
  const mark = nav && nav.querySelector('[aria-hidden="true"]');
  return {
    url: location.pathname + location.search,
    tabs: nav ? nav.__witness || null : null,
    main: document.getElementById('pm-main').__witness || null,
    title: document.getElementById('pm-page-title').__witness || null,
    subtitle: document.getElementById('pm-page-subtitle').__witness || null,
    sidebar: document.querySelector('aside').__witness || null,
    ctx: window.__ctx || null,
    markAt: mark ? mark.style.transform : null,
    lit: [...document.querySelectorAll('[data-keep="workspace-tabs"] [aria-current="page"]')].map(a => a.dataset.tab),
  };
}"""


def press_tab(page, key):
    page.evaluate(f"""() => document.querySelector('[data-keep="workspace-tabs"] [data-tab="{key}"]').click()""")
    page.wait_for_function(f"() => location.pathname.startsWith('/admin/workspace/{key}')", timeout=10000)
    page.wait_for_timeout(500)


def run(width, height):
    print(f"\nAT {width} WIDE:")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": width, "height": height},
                                   color_scheme="dark").new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("[name=username]", "mb")
        page.fill("[name=password]", "password")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        page.goto(BASE + "/admin/workspace/tasks", wait_until="networkidle")
        page.wait_for_timeout(500)
        page.evaluate(STAMP)
        before = page.evaluate(READ)
        for key, path in (("projects", "/admin/workspace/projects"), ("messages", "/admin/workspace/messages"),
                          ("tasks", "/admin/workspace/tasks")):
            press_tab(page, key)
            now = page.evaluate(READ)
            same = all(now[k] == v for k, v in (("tabs", "TABS"), ("main", "MAIN"), ("title", "TITLE"),
                                                  ("subtitle", "SUBTITLE"), ("sidebar", "SIDEBAR"), ("ctx", "ALIVE")))
            check(f"{key}: tab row, page, banner and sidebar are the same elements", same, now)
            check(f"{key}: the URL moved", now["url"].startswith(path), now["url"])
            check(f"{key}: the mark slid and the tab is lit", now["markAt"] != before["markAt"] or key == "tasks",
                  (before["markAt"], now["markAt"]))
            before = now

        print("  a filter's switch keeps itself and its bar:")
        page.evaluate("""() => {
          const seg = document.querySelector('[aria-label="Whose tasks"]');
          seg.__witness = 'SEG'; seg.closest('form').__witness = 'BAR';
          [...seg.querySelectorAll('button')].find(b => /Everyone/.test(b.innerText)).click();
        }""")
        page.wait_for_timeout(1200)
        after = page.evaluate("""() => { const seg = document.querySelector('[aria-label="Whose tasks"]');
          return { seg: seg.__witness || null, bar: seg.closest('form').__witness || null, url: location.search,
                   rows: document.querySelectorAll('[data-task]').length }; }""")
        check("Mine / Everyone: the switch and its bar are the same elements",
              after["seg"] == "SEG" and after["bar"] == "BAR", after)
        check("and the rows followed", "who=all" in after["url"] and after["rows"] == 4, after)

        press_tab(page, "projects")
        page.evaluate("""() => {
          const seg = document.querySelector('[aria-label="Which projects"]');
          seg.__witness = 'SEG'; document.getElementById('project-q').__witness = 'SEARCH';
          [...seg.querySelectorAll('button')].find(b => /Personal/.test(b.innerText)).click();
        }""")
        page.wait_for_timeout(1200)
        after = page.evaluate("""() => ({ seg: document.querySelector('[aria-label="Which projects"]').__witness || null,
          search: document.getElementById('project-q').__witness || null, url: location.search })""")
        check("Work / Personal: the switch and the search box are the same elements",
              after["seg"] == "SEG" and after["search"] == "SEARCH" and "view=personal" in after["url"], after)

        print("  a project opens under the same tab row:")
        page.goto(BASE + "/admin/workspace/projects", wait_until="networkidle")
        page.wait_for_timeout(400)
        page.evaluate(STAMP)
        page.evaluate(f"""() => document.querySelector('a[href="/admin/workspace/projects/{PROJECT}"]').click()""")
        # Wait for the address, not a fixed pause: a busy machine is slower.
        page.wait_for_function(f"() => location.pathname === '/admin/workspace/projects/{PROJECT}'", timeout=10000)
        page.wait_for_timeout(400)
        now = page.evaluate(READ)
        check("the tab row, the page and the sidebar stay", now["tabs"] == "TABS" and now["main"] == "MAIN"
              and now["sidebar"] == "SIDEBAR" and now["ctx"] == "ALIVE", now)
        check("and the project is open", now["url"] == f"/admin/workspace/projects/{PROJECT}", now["url"])

        page.evaluate("""() => {
          const seg = document.querySelector('[aria-label="This project"]');
          seg.__witness = 'SEG'; window.__fetches = 0;
          const f = window.fetch; window.fetch = (...a) => { window.__fetches++; return f(...a); };
          [...seg.querySelectorAll('button')].find(b => /Playbooks/.test(b.innerText)).click();
        }""")
        page.wait_for_timeout(600)
        after = page.evaluate("""() => ({ seg: document.querySelector('[aria-label="This project"]').__witness || null,
          fetches: window.__fetches, hash: location.hash })""")
        check("Tasks / Playbooks / Messages fetches nothing and keeps itself",
              after["seg"] == "SEG" and after["fetches"] == 0 and after["hash"] == "#playbooks", after)

        if width >= 1024:
            print("  another chat keeps the list:")
            page.goto(BASE + f"/admin/workspace/messages/{CONVS[0]}", wait_until="networkidle")
            page.wait_for_timeout(400)
            page.evaluate(STAMP)
            page.evaluate("() => { document.querySelector('[data-keep=\"ws-conv-list\"]').__witness = 'LIST'; }")
            page.evaluate(f"""() => document.querySelector('[data-conv-rows] a[href$="/messages/{CONVS[1]}"]').click()""")
            page.wait_for_timeout(1200)
            after = page.evaluate("""() => ({ list: document.querySelector('[data-keep="ws-conv-list"]').__witness || null,
              tabs: document.querySelector('[data-keep="workspace-tabs"]').__witness || null,
              url: location.pathname, text: document.querySelector('[data-panel="ws-chat"]').innerText })""")
            check("the list and the tab row are the same elements", after["list"] == "LIST" and after["tabs"] == "TABS", after)
            check("and the other chat is open", after["url"].endswith(f"/messages/{CONVS[1]}")
                  and "Hello in Second chat" in after["text"], after["url"])

            print("  saving a chat's people does not reload the page:")
            page.evaluate(STAMP)
            page.evaluate("""() => {
              document.querySelector('[data-keep="ws-conv-list"]').__witness = 'LIST';
              document.querySelector('button[aria-label="People in this chat"]').click();
            }""")
            page.wait_for_timeout(300)
            page.evaluate("""() => {
              const form = document.querySelector('form[action*="/people"]');
              form.querySelector('input[name=title]').value = 'Renamed chat';
              form.requestSubmit();
            }""")
            page.wait_for_timeout(1500)
            after = page.evaluate(READ)
            listed = page.evaluate("() => document.querySelector('[data-conv-rows]').innerText")
            check("the page, the tab row and the list stayed", after["ctx"] == "ALIVE" and after["main"] == "MAIN"
                  and after["tabs"] == "TABS" and page.evaluate(
                      "() => document.querySelector('[data-keep=ws-conv-list]').__witness") == "LIST", after)
            check("and the new name is in the chat and the list", "Renamed chat" in listed
                  and "Renamed chat" in page.evaluate("() => document.querySelector('[data-panel=ws-chat]').innerText"),
                  listed)

            print("  deleting your own message takes two presses:")
            page.evaluate("""() => document.querySelector('form[x-ref=form] textarea').value = ''""")
            page.fill("form[x-ref=form] textarea", "Delete me please")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            row = page.locator("[data-mid]", has_text="Delete me please").last
            row.locator("button[aria-label='Delete this message']").click()
            page.wait_for_timeout(500)
            still = page.locator("[data-mid]", has_text="Delete me please").count()
            check("one press only arms it", still == 1)
            row.locator("button", has_text="Delete").first.click()
            page.wait_for_timeout(1200)
            check("the armed press deletes it", page.locator("[data-mid]", has_text="This message was deleted.").count() >= 1)

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        press_tab(page, "tasks")
        check("no script errors on the way", not errors, errors)
        browser.close()


run(1600, 900)
run(375, 812)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
