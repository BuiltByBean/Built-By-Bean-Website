# -*- coding: utf-8 -*-
"""Org in a real browser, at 320, 375 and 1600 wide.

A server render cannot show any of this, so it drives headless Chromium:

  1. Every Org page at every width: the window never scrolls, nothing runs
     past the screen's right edge (outside a real sideways scroller), and on a
     phone every control is at least 44px.
  2. Switching business or view replaces only the panel: the business row,
     the view row and the banner are the same elements afterwards (a stamp set
     from JavaScript survives), and the URL follows.
  3. An open dropdown is on top: every option of the new responsibility's
     department picker hit-tests as that option (LM-1, LM-3).
  4. A save in place keeps the scroll position and the rows, and saving the
     person page twice in a row is not refused as stale: the swap brings the
     new version in.

Seeded with long names on purpose; short seed data hides overflow.
Run: python tools/test_org_browser.py [--shots <dir>]
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-org-browser-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("RAILWAY_ENVIRONMENT", None)
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed -> pip install playwright && playwright install chromium")
    sys.exit(1)

from app import create_app  # noqa: E402
import org_service  # noqa: E402
from models import db, Business, BusinessOwner, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
LONG = "Extraordinarily Long Departmental Name For Measuring Overflow"

with application.app_context():
    db.create_all()
    boss = User(username="Mbean", email="mbean@entertainhq.com", first_name="Michael", last_name="Bean", role="ceo")
    boss.set_password("password")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb")
    db.session.add_all([boss, bbb])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    pt = Business(name="Personal Training", slug="pt", parent_id=bbb.id)
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", hub_slug="entertainhq",
                   hub_secret="s")
    db.session.add_all([dd, pt, ehq])
    db.session.flush()
    for name, share in (("Michael Bean", 55), ("Kenali Kendrick", 35), ("Ty Lane", 10)):
        db.session.add(BusinessOwner(business_id=ehq.id, name=name, share_percent=share))
    db.session.commit()
    depts = [{"id": i, "name": n, "tone": t, "sort": i} for i, (n, t) in enumerate(
        [("Strategy & Leadership", "gold"), ("Product Development", "teal"), ("Engineering", "blue"),
         ("Marketing", "amber"), ("Sales", "green"), ("Customer Support", "sky"), ("Legal", "gray"),
         ("Accounting", "gold"), (LONG, "red")], start=1)]
    people = [{"id": 1, "name": "Michael Bean", "title": "Chief Executive Officer", "email": "mbean@entertainhq.com",
               "depts": [1, 2, 7, 8, 9]},
              {"id": 2, "name": "Kenali Kendrick", "title": "Chief Operating Officer", "supervisor": 1,
               "email": "kkendrick@entertainhq.com", "depts": [1, 4, 5, 6]},
              {"id": 3, "name": "Ty Lane", "title": "Chief Technology Officer", "supervisor": 1,
               "email": "tlane@entertainhq.com", "depts": [2, 3, 9]},
              {"id": 4, "name": "Bartholomew Montgomery-Fairweather", "title": "Senior Director of Partner Operations and Long Titles",
               "supervisor": 2, "depts": [9]}]
    resps = [{"id": i, "title": f"Responsibility number {i} with a fairly long description of the duty",
              "owner": (None if i % 5 == 0 else (i % 4) + 1), "dept": (i % 9) + 1, "sort": i} for i in range(1, 41)]
    org_service.import_org(ehq, {"people": people, "departments": depts, "responsibilities": resps,
                                 "logins": [{"email": p["email"]} for p in people[:3]]}, "entertainhq")
    EHQ, BBB = ehq.id, bbb.id
    TY = org_service.payload(ehq)["people"]
    TY = next(p["id"] for p in TY if p["name"] == "Ty Lane")

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True), daemon=True).start()

PAGES = [f"/admin/org/{EHQ}/", f"/admin/org/{EHQ}/chart", f"/admin/org/{EHQ}/responsibilities",
         f"/admin/org/{EHQ}/departments", f"/admin/org/{EHQ}/people/{TY}", f"/admin/org/{BBB}/",
         f"/admin/org/{BBB}/chart", "/admin/org/logins/"]

MEASURE = """() => {
  const vw = innerWidth, out = [], small = [];
  const scroller = document.getElementById('pm-scroll');
  function sideways(el) {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (/(auto|scroll)/.test(s.overflowX) && n.scrollWidth > n.clientWidth) return true;
    }
    return false;
  }
  document.querySelectorAll('#pm-main *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[aria-hidden="true"]')) return;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return;
    if (r.right > vw + 0.5 && !sideways(el)) out.push((el.className || el.tagName).toString().slice(0, 60) + ' ' + Math.round(r.right));
    if (vw < 640 && el.matches('a, button, input:not([type=hidden]):not(.sr-only), textarea, label:not([for])') && r.height < 43.5 && !el.closest('.sr-only'))
      small.push((el.innerText || el.name || el.tagName).trim().slice(0, 30) + ' ' + Math.round(r.height));
  });
  return {
    doc: document.documentElement.scrollHeight <= innerHeight,
    scrollW: scroller.scrollWidth <= scroller.clientWidth,
    out: out.slice(0, 8), small: [...new Set(small)].slice(0, 8)
  };
}"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (320, 375, 1600):
        ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("[name=username]", "Mbean")
        page.fill("[name=password]", "password")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        print(f"1. Every page at {width}")
        for path in PAGES:
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(150)
            # Open every responsibility card so the expanded state is measured too.
            if path.endswith("/responsibilities"):
                page.evaluate("() => document.querySelectorAll('[data-live-key] > button').forEach(b => b.click())")
                page.wait_for_timeout(200)
            m = page.evaluate(MEASURE)
            check(f"{width} {path}: the window never scrolls", m["doc"])
            check(f"{width} {path}: nothing sideways", m["scrollW"] and not m["out"], m["out"])
            if width < 640:
                check(f"{width} {path}: every control 44px", not m["small"], m["small"])
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                name = path.strip("/").replace("/", "_") or "root"
                page.screenshot(path=os.path.join(SHOTS, f"{width}_{name}.png"), full_page=False)

        if width in (375, 1600):
            print(f"2. Switching swaps only the panel at {width}")
            page.goto(BASE + f"/admin/org/{EHQ}/", wait_until="networkidle")
            page.evaluate("""() => {
              document.querySelector('[data-keep="org-tabs"]').dataset.stamp = 'B';
              document.querySelector('[data-keep="org-view-tabs"]').dataset.stamp = 'V';
              document.getElementById('pm-topbar').dataset.stamp = 'T';
            }""")
            page.click('[data-keep="org-view-tabs"] [data-tab="chart"]')
            page.wait_for_url("**/chart")
            page.wait_for_timeout(300)
            kept = page.evaluate("""() => [document.querySelector('[data-keep="org-tabs"]').dataset.stamp,
                                          document.querySelector('[data-keep="org-view-tabs"]').dataset.stamp,
                                          document.getElementById('pm-topbar').dataset.stamp,
                                          !!document.querySelector('.org-tree')]""")
            check("a view switch keeps both rows and the banner", kept[:3] == ["B", "V", "T"] and kept[3], kept)
            page.click(f'[data-keep="org-tabs"] [data-tab="{BBB}"]')
            page.wait_for_url(f"**/admin/org/{BBB}/**")
            page.wait_for_timeout(300)
            kept = page.evaluate("""() => [document.querySelector('[data-keep="org-tabs"]').dataset.stamp,
                                          document.querySelector('[data-keep="org-view-tabs"]').dataset.stamp,
                                          document.querySelector('[data-keep="org-view-tabs"] [data-tab="people"]').getAttribute('href')]""")
            check("a business switch keeps both rows", kept[:2] == ["B", "V"], kept)
            check("and the view row follows the business", kept[2].startswith(f"/admin/org/{BBB}/"), kept)

            print(f"3. An open dropdown is on top at {width}")
            page.goto(BASE + f"/admin/org/{EHQ}/responsibilities", wait_until="networkidle")
            page.wait_for_timeout(200)
            trigger = page.locator(
                                   "form:has(input[name=op][value=create]) button[aria-haspopup]").first
            trigger.click()
            page.wait_for_timeout(250)
            hits = page.evaluate("""() => {
              const form = document.querySelector('form input[name=op][value=create]').closest('form');
              const rows = [...form.querySelectorAll('[role=option]')].filter(r => r.getBoundingClientRect().height);
              const bad = [];
              let n = 0;
              rows.forEach(r => {
                // An option below the fold of its own list is scrolled to first,
                // by its list's scrollTop, never scrollIntoView.
                const list = r.closest('[role=listbox]') || r.parentElement;
                const lb = list.getBoundingClientRect(), rb = r.getBoundingClientRect();
                if (rb.bottom > lb.bottom) list.scrollTop += rb.bottom - lb.bottom;
                if (rb.top < lb.top) list.scrollTop -= lb.top - rb.top;
                const b = r.getBoundingClientRect();
                if (b.bottom > innerHeight || b.top < 0) return;
                n++;
                const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
                if (!hit || !(r === hit || r.contains(hit))) bad.push((r.innerText || '').trim().slice(0, 30));
              });
              return {n, bad};
            }""")
            check("every visible option hit-tests as itself", hits["n"] > 0 and not hits["bad"], hits)
            page.keyboard.press("Escape")

            print(f"4. A save in place at {width}")
            page.goto(BASE + f"/admin/org/{EHQ}/responsibilities", wait_until="networkidle")
            page.evaluate("() => { document.getElementById('pm-scroll').scrollTop = 600; window.__alive = 1; }")
            card = page.locator("[data-live-key]").nth(6)
            card.locator("> button").click()
            card.locator("input[name=title]").fill("Renamed in place")
            save_btn = card.locator("button[type=submit]:has-text('Save')")
            save_btn.scroll_into_view_if_needed()
            before = page.evaluate("() => document.getElementById('pm-scroll').scrollTop")
            save_btn.click()
            page.wait_for_timeout(700)
            after = page.evaluate("() => [document.getElementById('pm-scroll').scrollTop, window.__alive, "
                                  "document.body.innerText.includes('Renamed in place')]")
            check("the save landed without a reload", after[1] == 1 and after[2], after)
            check("and the page did not move", abs(after[0] - before) < 4 or before == 0, (before, after[0]))

            page.goto(BASE + f"/admin/org/{EHQ}/people/{TY}", wait_until="networkidle")
            page.fill("#p-title", "CTO, first save")
            page.click("#pm-actions button[form=org-person-form]")
            page.wait_for_timeout(600)
            page.fill("#p-title", "CTO, second save")
            page.click("#pm-actions button[form=org-person-form]")
            page.wait_for_timeout(600)
            txt = page.evaluate("() => document.body.innerText")
            check("two saves in a row both land", "CTO, second save" in txt and "changed that since" not in txt)
        ctx.close()
    browser.close()

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All org browser checks passed.")
sys.exit(1 if FAIL else 0)
