# -*- coding: utf-8 -*-
"""The Overview and Books, measured in a real browser at 320, 375 and 1600.

Seeded with long names and enough rows to scroll, because short seed data
hides every overflow fault this board has had. On every page, at every width:

  1. Nothing scrolls sideways: #pm-scroll's scrollWidth fits, and no element
     outside a real sideways scroller runs past the viewport's right edge.
  2. The window never scrolls (documentElement.scrollHeight <= innerHeight).
  3. Below 640px every visible button and button-like link is 44px tall.
  4. A Books tab press keeps the company row, the tab row and the page
     (#pm-main); a company press keeps both rows and every tab's address
     follows the company. Only the panel changes.
  5. The current Books tab sits inside its row on a phone (the row scrolls
     to it), never off the end.

Run: python tools/test_finances_browser.py
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-finbrowser-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("RAILWAY_ENVIRONMENT", None)
os.environ.pop("STRIPE_SECRET_KEY", None)
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
    print("  FAIL playwright is installed, so the pages were actually measured")
    sys.exit(1)

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, BusinessOwner, Client,  # noqa: E402
                    Expense, ExpenseTag, Project, ReceiptMailbox, User)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
LONG = "Supercalifragilistic Wholesale Plumbing and Heating Supply Company of North East Texas"
today = date.today()

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    boss.set_password("password")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ Limited Liability Company of Texas", short_name="EntertainHQ",
                   slug="ehq", sales_source="hub")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    db.session.add_all([BusinessOwner(business_id=ehq.id, name=n, share_percent=p)
                        for n, p in (("Michael Bean", 40), ("Kenali Kendrick", 40), ("A Third Member With A Long Name", 20))])
    client = Client(name=LONG)
    db.session.add(client)
    db.session.flush()
    project = Project(name=LONG + " website", client_id=client.id, status="active")
    db.session.add(project)
    merc = BankConnection(business_id=bbb.id, token="t", label="Mercury checking with a long label for the account")
    card = BankConnection(business_id=bbb.id, provider="statement", kind="personal", owner_name="Michael Bean",
                          label="Chase Sapphire Preferred personal card ending 4242")
    db.session.add_all([merc, card])
    db.session.add(ReceiptMailbox(address="a-very-long-receipts-mailbox-address@builtbybeans-example.test",
                                  password="x", business_id=bbb.id))
    db.session.flush()
    start = date(today.year, 4, 1) if today.month > 4 else date(today.year, 1, 1)
    for n in range(45):
        when = start + timedelta(days=(n * 4) % max(1, (today - start).days or 1))
        db.session.add(Expense(amount=10 + n * 3.17, date=when, business_id=bbb.id, category="software",
                               description=f"{LONG} invoice {n}", client_id=client.id if n % 2 else None,
                               project_id=project.id if n % 3 == 0 else None))
        db.session.add(BankTransaction(connection_id=merc.id, business_id=bbb.id, external_id=f"x{n}",
                                       status="sent", amount=-(5 + n), occurred_on=when,
                                       counterparty=f"{LONG} {n}", disposition="review"))
    db.session.add(ExpenseTag(amount=15.0, occurred_on=today - timedelta(days=12), vendor=LONG, business_id=bbb.id))
    db.session.commit()
    IDS = {"bbb": bbb.id, "ehq": ehq.id}

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                 daemon=True).start()

MEASURE = """(narrow) => {
  const vw = innerWidth, out = {page: [], small: [], edge: []};
  const s = document.getElementById('pm-scroll');
  if (s.scrollWidth > s.clientWidth + 1) out.page.push('pm-scroll ' + s.scrollWidth + ' > ' + s.clientWidth);
  if (document.documentElement.scrollHeight > innerHeight + 1) out.page.push('window scrolls ' + document.documentElement.scrollHeight);
  const sideways = (el) => { for (let n = el.parentElement; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && n.scrollWidth > n.clientWidth) return true; }
    return false; };
  for (const el of document.querySelectorAll('#pm-main *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[aria-hidden="true"]')) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (r.right > vw + 1 && !sideways(el)) out.edge.push((el.tagName + '.' + (el.className.baseVal ?? el.className)).slice(0, 80) + ' ' + Math.round(r.right));
    if (narrow && (el.tagName === 'BUTTON' || (el.tagName === 'A' && /rounded-(xl|lg)|btn-brand/.test(el.className))) && r.height < 43.5)
      out.small.push((el.textContent.trim() || el.getAttribute('aria-label') || el.tagName).slice(0, 40) + ' ' + Math.round(r.height));
  }
  out.edge = [...new Set(out.edge)].slice(0, 6); out.small = [...new Set(out.small)].slice(0, 6);
  return out;
}"""

STAMP = """() => {
  for (const [sel, v] of [['[data-keep="books-company-tabs"]', 'CO'], ['[data-keep="books-tabs"]', 'TABS']])
    { const el = document.querySelector(sel); if (el) el.__w = v; }
  document.getElementById('pm-main').__w = 'MAIN'; window.__ctx = 'ALIVE'; return true; }"""
READ = """() => ({
  co: (document.querySelector('[data-keep="books-company-tabs"]') || {}).__w || null,
  tabs: (document.querySelector('[data-keep="books-tabs"]') || {}).__w || null,
  main: document.getElementById('pm-main').__w || null, ctx: window.__ctx || null,
  url: location.pathname + location.search,
  hrefs: [...document.querySelectorAll('[data-keep="books-tabs"] [data-tab]')].map(a => a.getAttribute('href')),
  lit: [...document.querySelectorAll('[data-keep="books-tabs"] [aria-current="page"]')].map(a => a.dataset.tab),
})"""
INSIDE = """() => { const row = document.querySelector('[data-keep="books-tabs"] [x-ref="row"]');
  const a = row.querySelector('[aria-current="page"]'); if (!a) return 'none';
  const r = row.getBoundingClientRect(), t = a.getBoundingClientRect();
  return t.left >= r.left - 1 && t.right <= r.right + 1 ? 'inside' : `${Math.round(t.left)}..${Math.round(t.right)} vs ${Math.round(r.left)}..${Math.round(r.right)}`; }"""

PAGES = ["/admin/finances", f"/admin/finances?business={IDS['ehq']}", f"/admin/books/{IDS['bbb']}/",
         f"/admin/books/{IDS['bbb']}/bank", f"/admin/books/{IDS['bbb']}/bank?view=tags",
         f"/admin/books/{IDS['bbb']}/expenses", f"/admin/books/{IDS['bbb']}/receipts",
         f"/admin/books/{IDS['bbb']}/year/{today.year}", f"/admin/books/{IDS['bbb']}/connections",
         f"/admin/books/{IDS['ehq']}/connections", f"/admin/books/{IDS['bbb']}/month/{start:%Y-%m}",
         f"/admin/expenses/new?business_id={IDS['bbb']}", "/admin/clients", "/admin/tickets"]


def run(width, height):
    print(f"\nAT {width} WIDE:")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": width, "height": height}, color_scheme="dark").new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("[name=username]", "mb")
        page.fill("[name=password]", "password")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        for path in PAGES:
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(300)
            got = page.evaluate(MEASURE, width < 640)
            check(f"{path}: fits ({width})", not got["page"] and not got["edge"], got["page"] + got["edge"])
            if width < 640:
                check(f"{path}: every control is 44px ({width})", not got["small"], got["small"])

        # The sweep has to be able to fail: plant a wide box and a small press.
        page.goto(BASE + f"/admin/books/{IDS['bbb']}/connections", wait_until="networkidle")
        page.evaluate("""() => { const m = document.getElementById('pm-main');
            const d = document.createElement('div'); d.style.width = '3000px'; d.textContent = 'planted';
            const b = document.createElement('button'); b.textContent = 'tiny'; b.style.cssText = 'height:20px;min-height:0';
            m.prepend(d); m.prepend(b); }""")
        planted = page.evaluate(MEASURE, True)
        check(f"the sweep reports a planted overflow and a planted small press ({width})",
              planted["edge"] and (planted["small"] or width >= 640), planted)

        page.goto(BASE + f"/admin/books/{IDS['bbb']}/", wait_until="networkidle")
        page.wait_for_timeout(400)
        page.evaluate(STAMP)
        for tab in ("expenses", "connections", "bank", "receipts", "months"):
            page.evaluate(f"""() => document.querySelector('[data-keep="books-tabs"] [data-tab="{tab}"]').click()""")
            page.wait_for_function(f"""() => document.querySelector('[data-keep="books-tabs"] [aria-current="page"]')
                                          && location.pathname.indexOf('/admin/books/') === 0""", timeout=10000)
            page.wait_for_timeout(700)
            now = page.evaluate(READ)
            check(f"{tab}: the company row, the tab row and the page are the same elements ({width})",
                  (now["co"], now["tabs"], now["main"], now["ctx"]) == ("CO", "TABS", "MAIN", "ALIVE"), now)
            check(f"{tab}: the tab pressed is lit ({width})", now["lit"] == [tab], now["lit"])
            if width < 640:
                check(f"{tab}: the lit tab sits inside its row ({width})", page.evaluate(INSIDE) == "inside",
                      page.evaluate(INSIDE))
        page.evaluate(f"""() => document.querySelector('[data-keep="books-company-tabs"] [data-tab="{IDS['ehq']}"]').click()""")
        page.wait_for_function(f"() => location.pathname.indexOf('/admin/books/{IDS['ehq']}/') === 0", timeout=10000)
        page.wait_for_timeout(700)
        now = page.evaluate(READ)
        check(f"a company press keeps both rows and the page ({width})",
              (now["co"], now["tabs"], now["main"]) == ("CO", "TABS", "MAIN"), now)
        check(f"and every tab's address follows the company ({width})",
              all(f"/admin/books/{IDS['ehq']}/" in h for h in now["hrefs"]), now["hrefs"])
        browser.close()


for w, h in ((1600, 1000), (375, 812), (320, 640)):
    run(w, h)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
