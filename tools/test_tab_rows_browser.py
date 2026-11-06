# -*- coding: utf-8 -*-
"""Every tab row switches the EntertainHQ way (issue #16).

Michael, 2026-11-05, of the MVP Builder's Packages / Price list: switches
need to be smoother, "look at entertain hq's code it has perfected this".
EntertainHQ's glide: the row is never redrawn, its mark moves the moment a
tab is pressed, only what is under the row changes and fades in, and the
chosen tab is lit by the server so the first paint never flashes.

Driven in a real browser at 1600 and 375, on the two rows that used to
rebuild the whole page (the Handbook's and the MVP Builder's):

  1. A press keeps the row and #pm-main as the same elements (so the page's
     entry animation does not play again), and the URL and content change.
  2. The mark slid, and the pressed tab is the lit one.
  3. While the next page is on its way the row is never dimmed.
  4. On first paint the chosen tab is lit before any script has measured.
  5. Nothing scrolls the page sideways at 375.

Run: python tools/test_tab_rows_browser.py
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-tabrows-")
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
    print("  FAIL playwright is installed, so the rows were actually driven")
    sys.exit(1)

from app import create_app  # noqa: E402
from models import db, User  # noqa: E402


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
    boss.set_password("password")
    db.session.add(boss)
    db.session.commit()

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                 daemon=True).start()

ROWS = [
    ("mvp-tabs", "/admin/mvp/", [("prices", "/admin/mvp/price-list"), ("packages", "/admin/mvp/")]),
    ("practices-tabs", "/admin/practices/", [("rule", "/admin/features/rules"), ("playbook", "/admin/playbooks"),
                                             ("icon", "/admin/practices/icons"), ("all", "/admin/practices")]),
]

STAMP = """(key) => {
  document.querySelector('[data-keep="' + key + '"]').__witness = 'ROW';
  document.getElementById('pm-main').__witness = 'MAIN';
  return true;
}"""

READ = """(key) => {
  const nav = document.querySelector('[data-keep="' + key + '"]');
  const mark = nav && nav.querySelector('span[aria-hidden="true"]');
  return {
    url: location.pathname,
    row: nav ? nav.__witness || null : null,
    main: document.getElementById('pm-main').__witness || null,
    markAt: mark ? mark.style.transform : null,
    lit: nav ? [...nav.querySelectorAll('[aria-current="page"]')].map(a => a.dataset.tab) : [],
    rowOpacity: nav ? getComputedStyle(nav).opacity : null,
    sideways: document.getElementById('pm-scroll').scrollWidth - document.getElementById('pm-scroll').clientWidth,
  };
}"""


def run(width, height):
    print(f"\nAT {width} WIDE:")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("[name=username]", "mb")
        page.fill("[name=password]", "password")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        for key, start, presses in ROWS:
            # First paint: the chosen tab is lit by the server, before any script.
            html = page.request.get(BASE + start).text()
            row_html = html[html.find(f'data-keep="{key}"'):][:6000]
            lit_tag = row_html[:row_html.find("</a>", row_html.find('aria-current="page"'))]
            check(f"{key}: the chosen tab is lit in the page as sent", "data-lit" in lit_tag and "btn-brand" in lit_tag)

            page.goto(BASE + start, wait_until="networkidle")
            page.wait_for_timeout(400)
            page.evaluate(STAMP, key)
            before = page.evaluate(READ, key)
            check(f"{key}: after the hand-off only the mark is lit",
                  page.evaluate(f"""() => document.querySelectorAll('[data-keep="{key}"] [data-lit]').length""") == 0)
            for tab, path in presses:
                # Slow the answer a little, so the row's look while waiting is seen.
                page.route("**" + path + "*", lambda route: (page.wait_for_timeout(450), route.continue_()))
                page.evaluate(f"""() => document.querySelector('[data-keep="{key}"] [data-tab="{tab}"]').click()""")
                page.wait_for_timeout(330)
                waiting = page.evaluate(READ, key)
                check(f"{key} -> {tab}: the row is never dimmed while it waits", waiting["rowOpacity"] == "1",
                      waiting["rowOpacity"])
                page.wait_for_function(f"() => location.pathname.startsWith('{path}')", timeout=10000)
                page.wait_for_timeout(500)
                page.unroute("**" + path + "*")
                now = page.evaluate(READ, key)
                check(f"{key} -> {tab}: the row and the page are the same elements",
                      now["row"] == "ROW" and now["main"] == "MAIN", now)
                check(f"{key} -> {tab}: the mark slid and {tab} is lit",
                      now["markAt"] != before["markAt"] and now["lit"] == [tab], (before["markAt"], now))
                check(f"{key} -> {tab}: nothing scrolls sideways", now["sideways"] <= 0, now["sideways"])
                before = now
        browser.close()


run(1600, 900)
run(375, 812)
print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
