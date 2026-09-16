# -*- coding: utf-8 -*-
"""Moving between pages does not rebuild the parts that did not move.

Pressing Expenses and then My Apps threw away and rebuilt the whole shell: the
sidebar and its scroll position, the drawer on a phone, the banner, the running
timer, every entry animation. None of that changes between two pages of this
board. What changes is the title, the two lines in the banner, the back link
and page actions, the content, and which sidebar link is lit.

This drives a real browser, because there is no other honest way to test it.
The DOM assertions that a normal suite makes would pass against a full reload:
after the dust settles the page is correct either way. What is being tested is
whether the SAME ELEMENTS are still there, which is a question about the step
between two pages and not about either of them.

What is proved:

  1. THE POINT: after a navigation the sidebar, the banner and the scroller are
     the same elements they were, proved by a witness attribute set from
     JavaScript that no server render could reproduce.
  2. The sidebar's own scroll position survives, and one class moves from one
     link to another, which is all "you are here" ever was.
  3. The content, the title, the heading and the URL all do change.
  4. Back and forward work, and land on the right page with the right link lit.
  5. A filter, which is a GET form, swaps the same way.
  6. Alpine runs on what arrives, and an inline <script> in swapped content
     executes - the one thing innerHTML silently does not do.
  7. The guards hold: a PDF and a link off the board are left to the browser.

Run: python tools/test_shell_stays_put.py
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-shell-")
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
    # Loud, not skipped. A check that cannot run is not a check that passed.
    print("  FAIL playwright is installed, so the shell was actually driven")
    print("       -> pip install playwright && playwright install chromium")
    print("\n1 FAILED: this suite tests a browser and could not start one")
    sys.exit(1)

from app import create_app  # noqa: E402
from models import db, Client, Expense, Project, User  # noqa: E402


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
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("password")
    client = Client(name="Shell Test Ltd", email="shell@example.test")
    db.session.add_all([boss, client])
    db.session.flush()
    db.session.add(Project(name="Shell Test", client_id=client.id,
                           created_at=datetime.now(timezone.utc)))
    for n in range(6):
        db.session.add(Expense(category="software", amount=10.0 + n,
                               date=date(2026, 9, 1) + timedelta(days=n),
                               description=f"Shell probe {n}"))
    db.session.commit()

threading.Thread(
    target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
    daemon=True).start()

WITNESS = """() => {
  document.querySelector('aside').dataset.witness = 'SIDEBAR';
  document.getElementById('pm-topbar').dataset.witness = 'TOPBAR';
  document.getElementById('pm-scroll').dataset.witness = 'SCROLLER';
  document.querySelector('aside nav').scrollTop = 40;
  window.__ctx = 'ALIVE';
  return true;
}"""

STATE = """() => ({
  url: location.pathname + location.search,
  title: document.title,
  heading: document.getElementById('pm-page-title').innerText.trim(),
  active: [...document.querySelectorAll('aside a.sidebar-link.active')].map(a => a.innerText.trim()),
  sidebar: document.querySelector('aside').dataset.witness || null,
  topbar: document.getElementById('pm-topbar').dataset.witness || null,
  scroller: document.getElementById('pm-scroll').dataset.witness || null,
  navScroll: document.querySelector('aside nav').scrollTop,
  ctx: window.__ctx || null
})"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": 1280, "height": 900},
                               color_scheme="dark").new_page()
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.fill("[name=username]", "mb")
    page.fill("[name=password]", "password")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")

    page.goto(BASE + "/admin/expenses", wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    page.evaluate(WITNESS)
    before = page.evaluate(STATE)

    print("PRESSING ANOTHER PAGE:")
    page.evaluate("""() => [...document.querySelectorAll('aside a.sidebar-link')]
        .find(a => /My Apps/i.test(a.innerText)).click()""")
    page.wait_for_timeout(900)
    after = page.evaluate(STATE)

    check("THE POINT: the sidebar is the same element", after["sidebar"] == "SIDEBAR",
          after["sidebar"])
    check("and so is the banner", after["topbar"] == "TOPBAR", after["topbar"])
    check("and so is the scroller", after["scroller"] == "SCROLLER", after["scroller"])
    check("no page was loaded at all", after["ctx"] == "ALIVE", after["ctx"])
    check("the sidebar kept its own scroll position", after["navScroll"] == 40,
          after["navScroll"])
    check("the lit link moved", before["active"] == ["Expenses"]
          and after["active"] == ["My Apps"], (before["active"], after["active"]))
    check("the URL changed", after["url"].startswith("/admin/apps"), after["url"])
    check("the title changed", after["title"] != before["title"], after["title"])
    check("and so did the heading", after["heading"] == "My Apps", after["heading"])

    print("\nBACK AND FORWARD:")
    page.go_back()
    page.wait_for_timeout(900)
    back = page.evaluate(STATE)
    check("back lands on the page it came from", back["url"].startswith("/admin/expenses"),
          back["url"])
    check("with the right link lit", back["active"] == ["Expenses"], back["active"])
    check("and still without a reload", back["ctx"] == "ALIVE", back["ctx"])
    page.go_forward()
    page.wait_for_timeout(900)
    fwd = page.evaluate(STATE)
    check("forward goes forward again", fwd["url"].startswith("/admin/apps"), fwd["url"])

    print("\nA FILTER IS A NAVIGATION TOO:")
    page.goto(BASE + "/admin/expenses", wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    page.evaluate(WITNESS)
    page.evaluate("""() => {
      const input = document.querySelector('input[type=hidden][name="category"]');
      const cfg = JSON.parse(input.closest('[x-data^="bbbSelect("]').getAttribute('x-data').slice(10, -1));
      const opt = cfg.options.find(o => /Software/i.test(o.l)) || cfg.options[1];
      input.value = opt.v;
      input.dispatchEvent(new CustomEvent('dropdown-change',
        { bubbles: true, detail: { name: 'category', value: opt.v } }));
    }""")
    page.wait_for_timeout(1100)
    filtered = page.evaluate(STATE)
    check("the query string moved", "category=" in filtered["url"], filtered["url"])
    check("and the shell did not", filtered["ctx"] == "ALIVE" and filtered["sidebar"] == "SIDEBAR",
          (filtered["ctx"], filtered["sidebar"]))

    print("\nWHAT ARRIVES IS ALIVE:")
    page.goto(BASE + "/admin/contracts/", wait_until="domcontentloaded")
    page.wait_for_timeout(600)
    page.evaluate(WITNESS)
    page.evaluate("""() => [...document.querySelectorAll('a')]
        .find(a => /new\\/partnership/.test(a.getAttribute('href') || '')).click()""")
    page.wait_for_timeout(1200)
    live = page.evaluate("""() => {
      const input = document.querySelector('input[type=hidden][name="basis"]');
      const wrap = input && input.closest('[x-data^="bbbSelect("]');
      const trigger = wrap && wrap.querySelector('button[role=combobox]');
      if (trigger) trigger.click();
      return { ctx: window.__ctx || null,
               inlineScriptRan: typeof window.revisionPrefill === 'function',
               label: trigger ? trigger.innerText.trim() : null };
    }""")
    # Alpine writes :aria-expanded on its next tick, so the answer to whether
    # the panel opened is not available in the same breath as the press.
    page.wait_for_timeout(300)
    live["opened"] = page.evaluate("""() => {
      const input = document.querySelector('input[type=hidden][name=\"basis\"]');
      const wrap = input && input.closest('[x-data^=\"bbbSelect(\"]');
      const t = wrap && wrap.querySelector('button[role=combobox]');
      return t ? t.getAttribute('aria-expanded') : null;
    }""")
    check("it swapped rather than loaded", live["ctx"] == "ALIVE", live["ctx"])
    check("THE POINT: an inline script in the new content ran",
          live["inlineScriptRan"], "innerHTML does not execute scripts")
    check("Alpine initialised what arrived", live["label"] == "% of Net Profit",
          live["label"])
    check("and its picker opens", live["opened"] == "true", live["opened"])

    print("\nTHE GUARDS:")
    for what, href in (("a PDF", "/admin/contracts/1/signed.pdf"),
                       ("a page off the board", "/Bible-Study")):
        page.goto(BASE + "/admin/expenses", wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        page.evaluate(WITNESS)
        page.evaluate("""(href) => {
          const a = document.createElement('a');
          a.href = href;
          a.style.cssText = 'position:fixed;left:-9999px';
          document.body.appendChild(a);
          a.click();
        }""", href)
        page.wait_for_timeout(1200)
        # A swap keeps the JS context; a real navigation destroys it.
        ctx = page.evaluate("() => window.__ctx || null")
        check(f"{what} is left to the browser", ctx is None,
              "it was swapped, and it should not have been")

    browser.close()

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
