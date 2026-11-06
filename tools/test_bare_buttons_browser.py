# -*- coding: utf-8 -*-
"""The pages the bare-button sweep changed, in a real browser at 320, 375 and 1600.

tools/test_bare_buttons.py holds the markup to "a press is a border or a fill";
this holds the result to the house rules once it is drawn (issue #30):

  1. The window never scrolls and nothing runs past the right edge outside a
     real sideways scroller, at every width.
  2. On a phone every link and button the sweep boxed is at least 44px.
  3. Every press the sweep touched is boxed as drawn, not only as written: a
     border wider than zero or a background that is not transparent.
  4. A form's Cancel sits before its submit, and the pair ends at the
     trailing edge of its row.

Seeded with long names on purpose; short seed data hides overflow.
Run: python tools/test_bare_buttons_browser.py [--shots <dir>]
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-bare-browser-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ["FEATURE_TIME_TRACKING"] = "1"
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("RAILWAY_ENVIRONMENT", None)
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:500]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright is not installed -> pip install playwright && playwright install chromium")
    sys.exit(1)

from app import create_app  # noqa: E402
from models import (db, User, Client, Project, Ticket, Expense, SignatureRequest,  # noqa: E402
                    MvpPackage, WorkTask)

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
LONG = "Extraordinarily Long Company Name For Measuring Overflow Holdings"

with application.app_context():
    db.create_all()
    boss = User(username="Mbean", email="mbean@entertainhq.com", first_name="Michael", last_name="Bean", role="ceo")
    boss.set_password("password")
    db.session.add(boss)
    client = Client(name="Bartholomew Montgomery-Fairweather", company=LONG,
                    email="bartholomew.montgomery-fairweather@extraordinarily-long-domain.example",
                    phone="9035551234")
    db.session.add(client)
    db.session.flush()
    project = Project(name=LONG + " Website Rebuild", client_id=client.id, status="active", phase="mvp")
    db.session.add(project)
    db.session.flush()
    ticket = Ticket(client_id=client.id, project_id=project.id, title="A ticket with a long title " * 3,
                    description="Something broke.", source_path="/a/very/long/path/that/goes/on")
    db.session.add(ticket)
    db.session.flush()
    db.session.add(Expense(description="Receipt row", amount=12.5, date=date.today(), category="software",
                           ticket_id=ticket.id, project_id=project.id, client_id=client.id))
    sig = SignatureRequest(envelope_id="env-bare-1", title="Statement of Work: " + LONG, kind="sow", client_id=client.id,
                           project_id=project.id, signer_name="Bartholomew", signer_email="b@example.test",
                           status="completed", created_at=datetime.now(timezone.utc))
    db.session.add(sig)
    package = MvpPackage(client_id=client.id, name=LONG + " package")
    db.session.add(package)
    db.session.add(WorkTask(title="A task with a long title " * 3, created_by_id=None))
    db.session.commit()
    IDS = {"client": client.id, "project": project.id, "ticket": ticket.id, "contract": sig.id,
           "package": package.id}

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True), daemon=True).start()

C, P, T, S, K = (IDS[k] for k in ("client", "project", "ticket", "contract", "package"))
PAGES = [
    "/admin/clients", f"/admin/clients/{C}", f"/admin/clients/{C}/edit", "/admin/clients/new",
    f"/admin/workspace/projects/{P}", f"/admin/workspace/projects/{P}/edit", "/admin/workspace/projects/new",
    f"/admin/tickets/{T}", f"/admin/tickets/{T}/edit", "/admin/tickets/new",
    "/admin/time", "/admin/time/new",
    "/admin/contracts/", f"/admin/contracts/{S}", "/admin/contracts/new/statement-of-work", "/admin/contracts/new/engagement-letter",
    "/admin/contracts/new/hosting", "/admin/contracts/new/add-on", "/admin/contracts/new/addendum",
    "/admin/contracts/new/partnership", "/admin/contracts/new/founding", "/admin/contracts/new/profit-share",
    "/admin/mvp/", f"/admin/mvp/{K}", "/admin/mvp/price-list",
    "/admin/stripe/invoices/new", "/admin/workspace/tasks", "/admin/leads/", "/admin/catalog/",
    "/admin/taxes/sales/guide", "/admin/hosting/", "/admin/apps/",
]

# The presses this sweep boxed, by what they say or are named; each must be
# drawn with a border or a fill.
BOXED_PRESSES = """() => {
  const out = [];
  const want = /^(Cancel|No|Add a milestone|Add a feature|Open in Best Practices|Select All|Deselect All)$/;
  const named = /^(Edit |Download the unsigned|Take this|Read the |Log time on|Add an expense|View the receipt|Close|Menu|Delete this|Pause|Discard)/;
  document.querySelectorAll('a, button').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const text = (el.innerText || '').trim(), name = el.getAttribute('aria-label') || '';
    if (!want.test(text) && !named.test(name)) return;
    const s = getComputedStyle(el);
    const border = parseFloat(s.borderTopWidth) > 0 && s.borderTopStyle !== 'none';
    const fill = s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.backgroundImage !== 'none';
    if (!border && !fill) out.push(text || name);
  });
  return out;
}"""

FOOTERS = """() => {
  const out = [];
  document.querySelectorAll('a, button').forEach(el => {
    if ((el.innerText || '').trim() !== 'Cancel' || !el.getBoundingClientRect().width) return;
    const row = el.parentElement;
    const kids = [...row.children].filter(k => k.getBoundingClientRect().width);
    const submit = kids.find(k => k.matches('button[type=submit]'));
    if (!submit) return;
    const rr = row.getBoundingClientRect(), last = Math.max(...kids.map(k => k.getBoundingClientRect().right));
    const before = el.getBoundingClientRect().left <= submit.getBoundingClientRect().left
                   || el.getBoundingClientRect().top < submit.getBoundingClientRect().top;
    if (!before) out.push('Cancel after its submit');
    if (rr.right - last > 2) out.push('pair stops ' + Math.round(rr.right - last) + 'px short of the edge');
  });
  return out;
}"""

MEASURE = """(vw) => {
  const out = [], small = [];
  const scroller = document.getElementById('pm-scroll');
  function sideways(el) {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (/(auto|scroll)/.test(s.overflowX) && n.scrollWidth > n.clientWidth) return true;
    }
    return false;
  }
  document.querySelectorAll('#pm-main *, #pm-topbar *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[aria-hidden="true"]')) return;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return;
    if (r.right > vw + 0.5 && !sideways(el)) out.push((el.className || el.tagName).toString().slice(0, 60) + ' ' + Math.round(r.right));
    if (vw < 640 && el.matches('a:not([data-press=prose]):not([data-press=value]), button') && r.height < 43.5
        && !el.closest('.sr-only') && !el.closest('[role=listbox]'))
      small.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 30) + ' ' + Math.round(r.height));
  });
  return {
    doc: document.documentElement.scrollHeight <= innerHeight && innerWidth <= vw,
    scrollW: !scroller || scroller.scrollWidth <= scroller.clientWidth,
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
        print(f"\nAT {width}:")
        for path in PAGES:
            resp = page.goto(BASE + path, wait_until="networkidle")
            if not resp or resp.status >= 400:
                check(f"{width} {path}: opens", False, resp and resp.status)
                continue
            page.wait_for_timeout(120)
            m = page.evaluate(MEASURE, width)
            check(f"{width} {path}: the window never scrolls, nothing sideways",
                  m["doc"] and m["scrollW"] and not m["out"], m["out"])
            if width < 640:
                check(f"{width} {path}: every press 44px", not m["small"], m["small"])
            bare = page.evaluate(BOXED_PRESSES)
            check(f"{width} {path}: the presses the sweep boxed are drawn boxed", not bare, bare)
            feet = page.evaluate(FOOTERS)
            check(f"{width} {path}: Cancel before its submit, on the trailing edge", not feet, feet)
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                name = f"{width}_{path.strip('/').replace('/', '_')}"
                page.screenshot(path=os.path.join(SHOTS, name + ".png"))
                # And the foot of the one scroller, where a form's Cancel and
                # submit sit.
                page.evaluate("() => { const s = document.getElementById('pm-scroll'); if (s) s.scrollTop = s.scrollHeight; }")
                page.wait_for_timeout(80)
                page.screenshot(path=os.path.join(SHOTS, name + "_end.png"))
        ctx.close()
    browser.close()

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("All passed.")
