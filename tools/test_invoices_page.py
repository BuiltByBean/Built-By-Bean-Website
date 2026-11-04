# -*- coding: utf-8 -*-
"""The Invoices page, slimmed (docs/finances_plan.md item 3).

Michael, 2026-11-04: "the finances section as a whole could use some better
processes top to bottom ... some feature creep cleanup." For Invoices he
decided: the list, New invoice, and a thin Stripe balance strip; Setup
Products and Sync All Clients go; the two "Outstanding" figures get names
of their own; the hidden Unbilled figure comes back as Time not yet billed;
the stale comments go; every row opens the invoice. And item 10: CEO only.

Proves, with Stripe faked:

  1. Every route in the blueprint refuses a non-CEO login, GET and POST, and
     the webhook is still answered without one.
  2. The old addresses: /admin/stripe/ is a 301 to the list, the two retired
     presses land on the list (303) and make nothing; their buttons and
     endpoints are gone.
  3. The strip: available and pending from the balance, Open in Stripe for
     the whole account, and "Did not answer" rather than $0.00 when Stripe
     is down. No figure on the page is called Outstanding.
  4. Unpaid in this list follows every filter, status included.
  5. Every row opens the board's record: straight to it when the import has
     written one, through invoice_open (which writes it) when not, and an
     orphan says so and comes back to the list.
  6. Time not yet billed: per client, hours and value, leaving out time on a
     draft/open/paid invoice, MVP build time and free maintenance, keeping
     time a void invoice let go and an entry that names only its project;
     the tab's count is its rows; each row's press starts that client's
     invoice with the time ticked, and New invoice offers exactly the
     entries the tab counted.
  7. The stale "currently none" comments are gone.
  8. In a real browser at 320, 375 and 1600: nothing scrolls sideways, the
     window never scrolls, every control below 640px is at least 44px tall,
     and a tab press swaps the panel while the strip and the tab row stay
     the same elements.

Run: python tools/test_invoices_page.py
"""
import os
import pathlib
import re
import socket
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-invoices-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("RAILWAY_ENVIRONMENT", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "MAIL_SYNC_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import stripe  # noqa: E402

from app import create_app  # noqa: E402
from models import (db, Client, Invoice, InvoiceLineItem, Project, TimeEntry,  # noqa: E402
                    User)
import stripe_service  # noqa: E402
import pm.stripe_routes as stripe_routes  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def flat(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def money(text, label):
    m = re.search(re.escape(label) + r".{0,200}?(-?)\$([\d,]+\.\d\d)", text)
    return None if not m else float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


# ── Stripe, faked ───────────────────────────────────────────

NOW = datetime.now(timezone.utc)
TODAY = date.today()


def inv(id_, number, customer, status, total, due=None, paid=0.0, refunded=0.0, tax=0.0, days_ago=3):
    return {
        "id": id_, "number": number, "status": status, "customer_id": customer,
        "customer_name": None, "customer_email": None, "customer_client_ref": None,
        "total": total, "tax": tax, "amount_due": total if due is None else due,
        "amount_paid": paid, "refunded": refunded,
        "created_at": NOW - timedelta(days=days_ago), "due_date": None, "paid_at": None,
        "issued_at": NOW - timedelta(days=days_ago), "catchup": False, "description": None,
        "lines": [], "hosted_url": None, "pdf_url": None,
        "admin_url": f"https://dashboard.stripe.com/invoices/{id_}",
    }


INVOICES = [
    inv("in_paid", "A-0001", "cus_acme", "paid", 1000.0, due=0.0, paid=1000.0),
    inv("in_open", "A-0002", "cus_acme", "open", 400.0),
    inv("in_draft", None, "cus_acme", "draft", 250.0),
    inv("in_new", "A-0004", "cus_acme", "open", 75.0, days_ago=1),
    inv("in_orphan", "Z-0001", "cus_nobody", "open", 60.0),
    inv("in_void", "A-0003", "cus_acme", "void", 90.0, due=0.0, days_ago=40),
]

stripe.api_key = "sk_test_fake"


def stripe_answers(rows):
    # ts in the far future, so every ttl (0 included) reads the cache.
    stripe_service._invoice_cache.update({"ts": time.time() + 1e9, "data": rows, "refunds": {}})


stripe_answers(INVOICES)
BALANCE = {"answer": NS(available=[NS(currency="usd", amount=123456)], pending=[NS(currency="usd", amount=7890)])}
stripe_routes.get_stripe_balance = lambda: BALANCE["answer"]


def fresh_balance():
    stripe_routes._balance_cache.update({"ts": 0.0, "data": None})


# ── The board ───────────────────────────────────────────────

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", last_name="Bean", role="cmo")
    boss.set_password("password")
    hannah.set_password("password")
    acme = Client(name="Acme Plumbing", email="acme@example.test", stripe_customer_id="cus_acme")
    quiet = Client(name="Quiet Client", email="quiet@example.test")
    db.session.add_all([boss, hannah, acme, quiet])
    db.session.flush()
    site = Project(name="Acme Site", client_id=acme.id, phase="delivered")
    build = Project(name="Acme Build", client_id=acme.id, phase="mvp")
    db.session.add_all([site, build])
    db.session.flush()

    def entry(project, hours, rate_type="maintenance", client=True, days_ago=5):
        e = TimeEntry(project_id=project.id, client_id=project.client_id if client else None,
                      hours=hours, rate_type=rate_type, date=TODAY - timedelta(days=days_ago),
                      description="work")
        db.session.add(e)
        db.session.flush()
        return e

    waiting = entry(site, 2.0, days_ago=9)                   # $200, waiting
    feature = entry(site, 1.5, "new_feature", days_ago=2)    # $300, waiting
    loose = entry(site, 1.0, client=False, days_ago=4)       # $100, names only its project
    mvp = entry(build, 6.0, "mvp_build")                     # $0, build time is in the fee
    on_paid = entry(site, 3.0)                               # on a paid invoice
    on_draft = entry(site, 1.0)                              # on a draft
    let_go = entry(site, 0.5, days_ago=7)                    # on a void invoice: waiting again ($50)

    def held(status, e, sid):
        i = Invoice(client_id=acme.id, status=status, stripe_invoice_id=sid, total=0.0)
        db.session.add(i)
        db.session.flush()
        db.session.add(InvoiceLineItem(invoice_id=i.id, time_entry_id=e.id, description="x",
                                       quantity=e.hours, unit_amount=e.rate, total=e.cost, item_type="time"))
        return i

    paid_local = held("paid", on_paid, "in_paid")
    held("draft", on_draft, "in_draft")
    held("void", let_go, "in_void")
    db.session.commit()
    IDS = dict(boss=boss.id, hannah=hannah.id, acme=acme.id, quiet=quiet.id, paid_local=paid_local.id,
               waiting=waiting.id, feature=feature.id, loose=loose.id, mvp=mvp.id, on_paid=on_paid.id,
               on_draft=on_draft.id, let_go=let_go.id, site=site.id)


def login(user_id):
    c = application.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return c


ceo = login(IDS["boss"])
cmo = login(IDS["hannah"])

# ── 1. CEO only ─────────────────────────────────────────────
print("1. Every route is the CEO's, but the webhook")
rules = [r for r in application.url_map.iter_rules() if r.endpoint.startswith("stripe.")]
endpoints = {r.endpoint for r in rules}
for name in ("stripe.invoices_list", "stripe.unbilled", "stripe.invoice_create", "stripe.invoice_detail",
             "stripe.invoice_open", "stripe.stripe_webhook"):
    check(f"{name} exists", name in endpoints)
for rule in rules:
    if rule.endpoint == "stripe.stripe_webhook":
        continue
    path = re.sub(r"<int:\w+>", str(IDS["paid_local"]), rule.rule)
    path = re.sub(r"<(?:\w+:)?\w+>", "in_paid", path)
    for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
        res = cmo.open(path, method=method)
        check(f"a non-CEO is turned away from {method} {path}",
              res.status_code == 302 and "/admin/stripe" not in res.headers.get("Location", ""),
              (res.status_code, res.headers.get("Location")))
res = application.test_client().post("/admin/stripe/webhook", data="{}", headers={"Stripe-Signature": "x"})
check("the webhook is answered without a login (and refuses a bad signature itself)",
      res.status_code == 400, res.status_code)

# ── 2. Old addresses ────────────────────────────────────────
print("2. The old addresses")
res = ceo.get("/admin/stripe/")
check("/admin/stripe/ is a permanent redirect to the list",
      res.status_code == 301 and res.headers["Location"].endswith("/admin/stripe/invoices"),
      (res.status_code, res.headers.get("Location")))
for path in ("/admin/stripe/clients/sync-all", "/admin/stripe/setup-products"):
    res = ceo.post(path)
    check(f"POST {path} lands on the list", res.status_code == 303
          and res.headers["Location"].endswith("/admin/stripe/invoices"), (res.status_code, res.headers.get("Location")))
check("the sync_all_clients and setup_products endpoints are gone",
      not {"stripe.sync_all_clients", "stripe.setup_products"} & endpoints)
with application.app_context():
    check("no client was linked or made by them", db.session.get(Client, IDS["quiet"]).stripe_customer_id is None)

# ── 3. The strip ────────────────────────────────────────────
print("3. The Stripe strip")
fresh_balance()
res = ceo.get("/admin/stripe/invoices")
html = res.get_data(as_text=True)
page = flat(html)
check("the list renders", res.status_code == 200, res.status_code)
check("available is the balance", "$1,234.56 available" in page, page[:600])
check("pending is the balance", "$78.90 pending" in page)
check("Open in Stripe is the whole account's open invoices",
      "$535.00 open in Stripe, 3 invoices" in page, re.findall(r"\$[\d,.]+ open in Stripe[^$]{0,30}", page))
check("no figure is called Outstanding any more", "outstanding" not in page.lower())
check("the Setup Products and Sync All Clients presses are gone",
      "Setup Products" not in page and "Sync All Clients" not in page)
check("New invoice is a header action", 'href="/admin/stripe/invoices/new"' in html)
BALANCE["answer"] = None
fresh_balance()
page = flat(ceo.get("/admin/stripe/invoices").get_data(as_text=True))
check("Stripe down says so rather than $0.00", "Did not answer" in page and "$0.00 available" not in page)
BALANCE["answer"] = NS(available=[NS(currency="usd", amount=123456)], pending=[NS(currency="usd", amount=7890)])
fresh_balance()

# ── 4. Unpaid in this list ──────────────────────────────────
print("4. Unpaid in this list follows the filters")
page = flat(ceo.get("/admin/stripe/invoices").get_data(as_text=True))
check("unfiltered: drafts and open, orphan included", money(page, "Unpaid in this list") == 785.00,
      money(page, "Unpaid in this list"))
page = flat(ceo.get("/admin/stripe/invoices?status=paid").get_data(as_text=True))
check("filtered to paid: nothing unpaid in the list", money(page, "Unpaid in this list") == 0.00,
      money(page, "Unpaid in this list"))
check("and Total Paid is the paid one", money(page, "Total Paid") == 1000.00, money(page, "Total Paid"))
page = flat(ceo.get(f"/admin/stripe/invoices?client_id={IDS['acme']}&status=open").get_data(as_text=True))
check("Acme, open: the two open invoices", money(page, "Unpaid in this list") == 475.00
      and "2 draft or open" in page, money(page, "Unpaid in this list"))

# ── 5. Rows open the invoice ────────────────────────────────
print("5. Every row opens the invoice")
html = ceo.get("/admin/stripe/invoices").get_data(as_text=True)
check("a recorded invoice opens its record directly",
      f'href="/admin/stripe/invoices/{IDS["paid_local"]}"' in html)
check("one not recorded yet opens through invoice_open", 'href="/admin/stripe/invoices/stripe/in_new"' in html)
check("every row also opens in Stripe, by an icon with a name",
      html.count('aria-label="Open ') == len(INVOICES))
res = ceo.get("/admin/stripe/invoices/stripe/in_new")
with application.app_context():
    written = Invoice.query.filter_by(stripe_invoice_id="in_new").first()
check("invoice_open writes the record and opens it",
      written is not None and res.status_code == 302
      and res.headers["Location"].endswith(f"/admin/stripe/invoices/{written.id}"),
      (res.status_code, res.headers.get("Location")))
res = ceo.get("/admin/stripe/invoices/stripe/in_orphan")
with ceo.session_transaction() as s:
    said = " ".join(t for _, t in s.get("_flashes", []))
check("an orphan comes back to the list and says why",
      res.status_code == 302 and res.headers["Location"].endswith("/admin/stripe/invoices")
      and "on no client" in said, (res.headers.get("Location"), said))

# ── 6. Time not yet billed ──────────────────────────────────
print("6. Time not yet billed")
with application.app_context():
    got = stripe_routes.unbilled_time()
    rows = got["rows"]
    check("one client row, Acme's", [r["client"].name for r in rows] == ["Acme Plumbing"], rows)
    acme_row = rows[0] if rows else {}
    check("the value is the waiting maintenance, the feature, the loose entry and the time a void let go",
          acme_row.get("value") == 650.00 and got["total"] == 650.00, acme_row.get("value"))
    check("and the hours are the billable ones only", acme_row.get("hours") == 5.0, acme_row.get("hours"))
    check("four entries", acme_row.get("entries") == 4, acme_row.get("entries"))
    check("from the oldest day to the newest",
          acme_row.get("since") == TODAY - timedelta(days=9) and acme_row.get("latest") == TODAY - timedelta(days=2))

res = ceo.get("/admin/stripe/invoices/unbilled")
html = res.get_data(as_text=True)
page = flat(html)
check("the tab renders", res.status_code == 200, res.status_code)
check("the row shows the client, the value and the hours",
      "Acme Plumbing" in page and "$650.00" in page and "5.0h" in page)
check("its press starts Acme's invoice with the time ticked",
      f'href="/admin/stripe/invoices/new?client_id={IDS["acme"]}&amp;take=all"' in html)
tab_count = re.search(r'data-count="unbilled"[^>]*>([^<]*)<', html)
check("the tab's count is the number of rows", tab_count and tab_count.group(1).strip() == "1",
      tab_count.group(0) if tab_count else None)
list_html = ceo.get("/admin/stripe/invoices").get_data(as_text=True)
tab_count = re.search(r'data-count="unbilled"[^>]*>([^<]*)<', list_html)
check("and the same on the Invoices tab", tab_count and tab_count.group(1).strip() == "1")
check("both tabs share one panel and one kept tab row",
      'data-panel="invoices"' in html and 'data-keep="invoices-tabs"' in html
      and 'data-panel="invoices"' in list_html and 'data-keep="invoices-tabs"' in list_html)

offered = {e["id"] for e in ceo.get(f"/admin/stripe/api/uninvoiced-entries/{IDS['acme']}").get_json()}
counted = {IDS["waiting"], IDS["feature"], IDS["loose"], IDS["let_go"]}
check("New invoice offers every entry the tab counted, the loose one included",
      counted <= offered, (counted - offered))
check("and nothing on a draft, open or paid invoice", not ({IDS["on_paid"], IDS["on_draft"]} & offered), offered)

res = ceo.get(f"/admin/stripe/invoices/new?client_id={IDS['acme']}&take=all")
gen = res.get_data(as_text=True)
check("New invoice shows the time step whatever the time flag says",
      "Select Time Entries" in gen and not application.config.get("FEATURE_TIME_TRACKING"))
check("and loads the client's time ticked", "this.loadEntries(true ? 'time' : false)" in gen)

with application.app_context():
    for e in TimeEntry.query.all():
        db.session.delete(e)
    db.session.commit()
html = ceo.get("/admin/stripe/invoices/unbilled").get_data(as_text=True)
check("with nothing waiting the tab says so", 'class="empty' in html
      and "Every billable hour is on an invoice" in flat(html))
tab_count = re.search(r'data-count="unbilled"[^>]*class="([^"]*)"', html) or \
    re.search(r'class="([^"]*)"[^>]*data-count="unbilled"', html)
badge = re.search(r'<span data-count="unbilled"\s+class="([^"]*)"', html)
check("and the tab's count is hidden", badge and "hidden" in badge.group(1), badge.group(1) if badge else None)

# ── 7. Stale words ──────────────────────────────────────────
print("7. Stale comments")
stripe_dir = ROOT / "templates" / "pm" / "stripe"
text = " ".join(p.read_text(encoding="utf-8") for p in stripe_dir.rglob("*.html"))
text += (ROOT / "pm" / "stripe_routes.py").read_text(encoding="utf-8")
for stale in ("currently none", "production has none", "no local record behind these",
              "sync_all_clients", "setup_products"):
    check(f"'{stale}' is gone", stale not in text)
check("the account partial is gone", not (stripe_dir / "_account.html").exists())

# ── 8. In a browser ─────────────────────────────────────────
print("8. In a browser")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    check("playwright is installed, so the page was actually measured", False)

if sync_playwright:
    # Rows enough to scroll, with long names, so the measures mean something.
    long_rows = [inv(f"in_{n}", f"LONG-{n:04d}", "cus_acme", ("paid", "open", "draft")[n % 3], 1234.5 + n,
                     paid=1234.5 + n if n % 3 == 0 else 0.0) for n in range(45)]
    stripe_answers(INVOICES + long_rows)
    with application.app_context():
        acme = db.session.get(Client, IDS["acme"])
        acme.name = "Acme Plumbing and Drain Services of Northeast Texas Limited"
        LONG = []
        for n in range(8):
            c = Client(name=f"Client With A Long Name Number {n} Incorporated")
            db.session.add(c)
            db.session.flush()
            p = Project(name=f"A Project With A Long Name {n}", client_id=c.id, phase="delivered")
            db.session.add(p)
            db.session.flush()
            db.session.add(TimeEntry(project_id=p.id, client_id=c.id, hours=1.25 + n, rate_type="new_feature",
                                     date=TODAY - timedelta(days=n), description="x"))
            LONG.append(c.id)
        db.session.commit()

    def free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    PORT = free_port()
    BASE = f"http://127.0.0.1:{PORT}"
    threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                     daemon=True).start()
    time.sleep(1.0)

    MEASURE = """() => {
      const s = document.getElementById('pm-scroll');
      const small = [];
      if (innerWidth < 640) {
        document.querySelectorAll('#pm-main a, #pm-main button, #pm-main input:not([type=hidden]), #pm-main [role=button]').forEach(el => {
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) return;
          if (el.closest('td') && el.tagName === 'A' && !el.className.includes('w-11')) return;
          if (r.height < 43.5) small.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40) + ' ' + Math.round(r.height));
        });
      }
      const past = [];
      document.querySelectorAll('#pm-main *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (!r.width || r.right <= innerWidth + 0.5) return;
        for (let a = el.parentElement; a; a = a.parentElement) {
          const st = getComputedStyle(a);
          if ((st.overflowX === 'auto' || st.overflowX === 'scroll') && a.scrollWidth > a.clientWidth) return;
        }
        past.push(el.tagName + '.' + (el.className || '').toString().slice(0, 40));
      });
      // A figure cut off at its own card's edge: the page never scrolls for
      // it, so only the card can say.
      document.querySelectorAll('#pm-main .glass-card').forEach(card => {
        const c = card.getBoundingClientRect();
        card.querySelectorAll('p, span').forEach(el => {
          const r = el.getBoundingClientRect();
          if (!r.width || r.right <= c.right + 0.5) return;
          for (let a = el.parentElement; a && a !== card; a = a.parentElement) {
            const st = getComputedStyle(a);
            if ((st.overflowX === 'auto' || st.overflowX === 'scroll') && a.scrollWidth > a.clientWidth) return;
          }
          past.push('cut: ' + el.textContent.trim().slice(0, 30));
        });
      });
      return { sideways: s.scrollWidth - s.clientWidth, window: document.documentElement.scrollHeight - innerHeight,
               small: small.slice(0, 8), past: past.slice(0, 8) };
    }"""

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((320, 640), (375, 812), (1600, 900)):
            page_ = browser.new_context(viewport={"width": width, "height": height}, color_scheme="dark").new_page()
            errors = []
            page_.on("pageerror", lambda e: errors.append(str(e)))
            page_.goto(BASE + "/login", wait_until="domcontentloaded")
            page_.fill("[name=username]", "mb")
            page_.fill("[name=password]", "password")
            page_.click("button[type=submit]")
            page_.wait_for_load_state("networkidle")
            for path in ("/admin/stripe/invoices", "/admin/stripe/invoices/unbilled"):
                page_.goto(BASE + path, wait_until="networkidle")
                page_.wait_for_timeout(400)
                if os.environ.get("INVOICES_SHOTS"):
                    page_.screenshot(path=os.path.join(os.environ["INVOICES_SHOTS"],
                                                       f"{width}{path.replace('/', '_')}.png"))
                m = page_.evaluate(MEASURE)
                check(f"{width}px {path}: nothing scrolls sideways", m["sideways"] <= 0 and not m["past"], m)
                check(f"{width}px {path}: the window never scrolls", m["window"] <= 0, m["window"])
                if width < 640:
                    check(f"{width}px {path}: every control is 44px", not m["small"], m["small"])

            page_.goto(BASE + "/admin/stripe/invoices", wait_until="networkidle")
            page_.wait_for_timeout(300)
            page_.evaluate("""() => { document.querySelector('[data-invoices-strip]').__w = 'STRIP';
                document.querySelector('[data-keep="invoices-tabs"]').__w = 'TABS';
                document.getElementById('pm-main').__w = 'MAIN'; }""")
            page_.evaluate("""() => document.querySelector('[data-keep="invoices-tabs"] [data-tab="unbilled"]').click()""")
            page_.wait_for_function("() => location.pathname === '/admin/stripe/invoices/unbilled'", timeout=10000)
            page_.wait_for_timeout(500)
            kept = page_.evaluate("""() => ({ strip: document.querySelector('[data-invoices-strip]').__w || null,
                tabs: document.querySelector('[data-keep="invoices-tabs"]').__w || null,
                main: document.getElementById('pm-main').__w || null,
                rows: document.querySelectorAll('[data-unbilled-client]').length,
                lit: document.querySelector('[data-keep="invoices-tabs"] [aria-current="page"]')?.dataset.tab })""")
            check(f"{width}px: a tab press keeps the strip, the tab row and the page",
                  kept["strip"] == "STRIP" and kept["tabs"] == "TABS" and kept["main"] == "MAIN", kept)
            check(f"{width}px: and the panel is the other tab's", kept["rows"] == 8 and kept["lit"] == "unbilled", kept)

            # A filter pick swaps the rows, not the bar.
            page_.goto(BASE + "/admin/stripe/invoices", wait_until="networkidle")
            page_.wait_for_timeout(300)
            # Who scrolls: the rows on a wide screen, the page on a phone with
            # the bar pinned flush under the banner and on top of the rows.
            sc = page_.evaluate("""async () => {
                const s = document.getElementById('pm-scroll');
                const rows = document.querySelector('#pm-main table').parentElement;
                const bar = document.querySelector('#pm-main form[method=GET]');
                const out = { inner: rows.scrollHeight > rows.clientHeight + 1, outer: s.scrollHeight > s.clientHeight + 1 };
                s.scrollTop = 600; rows.scrollTop = 600;
                await new Promise(r => setTimeout(r, 150));
                const b = bar.getBoundingClientRect(), t = s.getBoundingClientRect();
                const hit = document.elementFromPoint(b.left + 12, b.top + b.height / 2);
                out.barTop = Math.round(b.top - t.top); out.barHit = !!hit && bar.contains(hit);
                out.scrolled = s.scrollTop;
                return out; }""")
            if width >= 640:
                check(f"{width}px: the rows scroll inside, the page does not", sc["inner"] and not sc["outer"], sc)
            else:
                check(f"{width}px: on a phone the page scrolls and the bar stays pinned on top",
                      sc["outer"] and sc["scrolled"] > 0 and abs(sc["barTop"]) <= 1 and sc["barHit"], sc)
            page_.goto(BASE + "/admin/stripe/invoices", wait_until="networkidle")
            page_.wait_for_timeout(300)
            page_.evaluate("""() => { const f = document.querySelector('#pm-main form[method=GET]'); f.__w = 'BAR';
                [...f.querySelectorAll('button')].find(b => /Last month/.test(b.textContent)).click(); }""")
            page_.wait_for_timeout(1200)
            after = page_.evaluate("""() => ({ bar: document.querySelector('#pm-main form[method=GET]').__w || null,
                url: location.search,
                pressed: [...document.querySelectorAll('#pm-main form[method=GET] button[aria-pressed=true]')].map(b => b.textContent.trim()) })""")
            check(f"{width}px: Last month applies itself and keeps the bar",
                  after["bar"] == "BAR" and "month=" in after["url"] and after["pressed"] == ["Last month"], after)
            if width == 1600:
                # The row's press, followed: New invoice with that client's time ticked.
                page_.goto(BASE + "/admin/stripe/invoices/unbilled", wait_until="networkidle")
                page_.evaluate(f"""() => document.querySelector('[data-unbilled-client="{LONG[0]}"] a').click()""")
                page_.wait_for_function("() => location.pathname === '/admin/stripe/invoices/new'", timeout=10000)
                page_.wait_for_timeout(1200)
                ticked = page_.evaluate("""() => [...document.querySelectorAll('input[name=time_entries]')]
                    .map(i => i.checked)""")
                check("the row's press opens New invoice with the client's time ticked",
                      ticked == [True], ticked)
            check(f"{width}px: no script errors", not errors, errors)
            page_.context.close()
        browser.close()

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
