# -*- coding: utf-8 -*-
"""A company's papers in a real browser, at 320, 375 and 1600 wide (issue #31).

A server render cannot show any of this, so it drives headless Chromium:

  1. The business pages (a company with papers held, missing and set aside, a
     DBA) and Needs attention at every width: the window never scrolls,
     nothing runs past the right edge, every control on a phone is 44px, and
     no control on the Documents card is bare text (each has a border or a
     fill: "Text alone is never a button").
  2. Picking a file on a missing paper's Upload is the upload: the row turns
     held, the card swaps in place, the scroller does not move, the banner is
     the same element, and the sidebar's Needs attention count drops.
  3. Not needed sets one aside in place the same way, and Ask for it brings
     it back.

Seeded with long names on purpose; short seed data hides overflow.
Run: python tools/test_business_documents_browser.py [--shots <dir>]
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-docs-browser-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"
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
from models import (db, Business, BusinessDocument, BusinessLocation, BusinessOwner,  # noqa: E402
                    DeadlineDone, User)
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 0.0}

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["WTF_CSRF_ENABLED"] = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
LONGFILE = "EntertainHQ LLC Internal Revenue Service Letter 147C Employer Identification Number Confirmation Scan.pdf"
PDF = b"%PDF-1.4\n" + b"1" * 300
os.makedirs(os.path.join(TMP, "business_documents"), exist_ok=True)

with application.app_context():
    db.create_all()
    boss = User(username="Mbean", email="mbean@entertainhq.com", first_name="Michael", role="ceo")
    boss.set_password("password")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb",
                   formed_on=date(2024, 1, 17), sales_source="manual")
    ehq = Business(name="EntertainHQ Limited Liability Company of Paris Texas", short_name="EntertainHQ",
                   slug="ehq", texas_taxpayer_number="32108463343", sales_tax_webfile="RT123456",
                   sales_source="manual")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id, sales_source="manual")
    db.session.add(dd)
    db.session.add(BusinessLocation(business_id=bbb.id, label="Paris", webfile_number="00001"))
    for name in ("Michael Bean", "Kenali Kendrick", "Ty Lane"):
        db.session.add(BusinessOwner(business_id=ehq.id, name=name))
    with open(os.path.join(TMP, "business_documents", "ein.pdf"), "wb") as fh:
        fh.write(PDF)
    db.session.add(BusinessDocument(business_id=ehq.id, kind="ein", stored_name="ein.pdf",
                                    original_name=LONGFILE, size=len(PDF)))
    db.session.add(DeadlineDone(key=f"paper:{ehq.id}:formation"))
    db.session.commit()
    EHQ, BBB, DD = ehq.id, bbb.id, dd.id

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True), daemon=True).start()

PAGES = [f"/admin/businesses/{EHQ}", f"/admin/businesses/{BBB}", f"/admin/businesses/{DD}", "/admin/attention/"]

MEASURE = """() => {
  const vw = innerWidth, out = [], small = [], bare = [];
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
    if (vw < 640 && el.matches('a, button, input:not([type=hidden]):not(.sr-only):not([type=file]), textarea, label:not([for])') && r.height < 43.5 && !el.closest('.sr-only'))
      small.push((el.innerText || el.name || el.tagName).trim().slice(0, 30) + ' ' + Math.round(r.height));
  });
  // Every press on the Documents card has a border or a fill.
  const card = document.getElementById('documents');
  if (card) card.querySelectorAll('a, button, label:has(input[type=file])').forEach(el => {
    // A picker's options are rows of a list, drawn only while it is open.
    if (el.closest('[role=listbox], [role=option]') || !el.getClientRects().length) return;
    const st = getComputedStyle(el);
    const border = parseFloat(st.borderTopWidth) > 0 && st.borderTopColor !== 'rgba(0, 0, 0, 0)';
    const fill = st.backgroundColor !== 'rgba(0, 0, 0, 0)' || st.backgroundImage !== 'none';
    if (!border && !fill) bare.push((el.getAttribute('aria-label') || el.innerText || el.tagName).trim().slice(0, 40));
  });
  // Every press stays inside its own row: a button hanging past the row's
  // edge is inside the screen and still wrong.
  const spill = [];
  document.querySelectorAll('[data-paper], [data-paper-missing], [data-paper-waived], [data-papers-row]').forEach(row => {
    const rr = row.getBoundingClientRect();
    row.querySelectorAll('a, button, label:has(input[type=file])').forEach(el => {
      if (!el.getClientRects().length) return;
      const r = el.getBoundingClientRect();
      if (r.right > rr.right + 0.5 || r.left < rr.left - 0.5 || r.bottom > rr.bottom + 0.5)
        spill.push((el.getAttribute('aria-label') || el.innerText).trim().slice(0, 30) + ' ' + Math.round(r.right) + '>' + Math.round(rr.right));
    });
  });
  return {
    spill: spill,
    doc: document.documentElement.scrollHeight <= innerHeight,
    scrollW: scroller.scrollWidth <= scroller.clientWidth,
    out: out.slice(0, 8), small: [...new Set(small)].slice(0, 8), bare: bare
  };
}"""

BADGE = """() => { const n = document.querySelector('[data-live="nav-attention"]');
                   return n ? n.innerText.trim() : ''; }"""

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
            if path != "/admin/attention/":
                page.evaluate("() => document.getElementById('documents').scrollIntoView()")
                page.wait_for_timeout(100)
            m = page.evaluate(MEASURE)
            check(f"{width} {path}: the window never scrolls", m["doc"])
            check(f"{width} {path}: nothing sideways", m["scrollW"] and not m["out"], m["out"])
            if width < 640:
                check(f"{width} {path}: every control 44px", not m["small"], m["small"])
            check(f"{width} {path}: no bare-text press on the card", not m["bare"], m["bare"])
            check(f"{width} {path}: every press inside its own row", not m["spill"], m["spill"])
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                name = path.strip("/").replace("/", "_")
                page.screenshot(path=os.path.join(SHOTS, f"{width}_{name}.png"), full_page=False)
        ctx.close()

    print("2. Upload and Not needed, in place, at 375")
    ctx = browser.new_context(viewport={"width": 375, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.fill("[name=username]", "Mbean")
    page.fill("[name=password]", "password")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    page.goto(BASE + f"/admin/businesses/{EHQ}", wait_until="networkidle")
    page.evaluate("() => document.getElementById('documents').scrollIntoView()")
    page.wait_for_timeout(150)
    page.evaluate("() => { document.getElementById('pm-topbar').dataset.stamp = 'T'; }")
    before = page.evaluate("() => document.getElementById('pm-scroll').scrollTop")
    badge0 = page.evaluate(BADGE)
    page.set_input_files('[data-paper-missing="sales_permit"] input[type=file]',
                         files=[{"name": "EntertainHQ LLC Texas Sales and Use Tax Permit.pdf",
                                 "mimeType": "application/pdf", "buffer": PDF}])
    page.wait_for_selector('[data-paper-missing="sales_permit"]', state="detached", timeout=5000)
    page.wait_for_timeout(200)
    after = page.evaluate("""() => [document.getElementById('pm-scroll').scrollTop,
                                    document.getElementById('pm-topbar').dataset.stamp,
                                    document.querySelectorAll('[data-paper]').length]""")
    check("picking the file uploads it and the row turns held", after[2] == 2, after)
    check("the page did not move and the banner stayed", abs(after[0] - before) < 2 and after[1] == "T",
          (before, after))
    check("the sidebar badge stays (Operating Agreement still missing)", page.evaluate(BADGE) == badge0,
          (badge0, page.evaluate(BADGE)))
    page.click('[data-paper-missing="operating"] button:has-text("Not needed")')
    page.wait_for_selector('[data-paper-waived="operating"]', timeout=5000)
    page.wait_for_timeout(200)
    check("Not needed sets it aside in place", page.evaluate(
        "() => document.getElementById('pm-topbar').dataset.stamp") == "T")
    check("and the badge drops", page.evaluate(BADGE) != badge0, (badge0, page.evaluate(BADGE)))
    check("the card reads All on file", "All on file" in page.inner_text("#documents"))
    page.click('[data-paper-waived="operating"] button:has-text("Ask for it")')
    page.wait_for_selector('[data-paper-missing="operating"]', timeout=5000)
    check("Ask for it brings it back", True)
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "375_after_presses.png"), full_page=False)
    browser.close()

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
