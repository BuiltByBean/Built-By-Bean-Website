# -*- coding: utf-8 -*-
"""The Taxes pages: five tabs, income tax per company, and CEO only.

docs/finances_plan.md item 4 (Michael, 2026-11-04). Proves:

  1. income_tax.estimate for Built by Bean (Schedule C): its net is the
     Books page's net for the year to the cent, its tax is tax_engine's on
     that profit, set aside is the same rate on the profit dated through
     today, and the four quarters carry deadlines.estimate_due.
  2. EntertainHQ (three members) is a partnership: the company's net, each
     member's share of it, and Michael's share's tax as what it adds to his
     own return on top of Built by Bean's profit (no tax at the company).
     A partnership he is not a member of costs him nothing, and a DBA asks
     for its parent.
  3. The Income tax page: the company switch, the year, the Books figure,
     the members on EntertainHQ's, no Stripe payout wording, and saving the
     situation keeps the company and year.
  4. Every tax page (Income tax, Sales tax, Returns and a return under it,
     Deadlines, Guide) draws the same five tabs in that order from the kit,
     with its own tab lit, over one data-panel="taxes"; "How to file" is gone.
  5. CEO only: a CMO login is refused on every GET and POST of these pages,
     and the old URLs still answer the CEO.
  6. In a real browser at 320, 375 and 1600 (when Playwright is installed):
     a tab press keeps the tab row and the page and swaps the panel; the
     company switch swaps only the answer; nothing scrolls sideways, the
     window never scrolls, and every control is 44px tall below 640px.

Run: python tools/test_taxes_tabs.py
"""
import os
import pathlib
import re
import socket
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-taxtabs-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
os.environ.pop("RAILWAY_ENVIRONMENT", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, BusinessOwner, Client, Expense, Invoice,  # noqa: E402
                    StripeActivity, TaxSetting, User)
import books_service  # noqa: E402
import deadlines  # noqa: E402
import income_tax  # noqa: E402
from tax_engine import compute  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
TODAY = date.today()
YEAR = TODAY.year


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def flat(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def money(text, label):
    m = re.search(re.escape(label) + r".{0,200}?(-?)\$([\d,]+\.\d\d)", flat(text))
    return None if not m else float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", last_name="Bean", role="cmo")
    boss.set_password("password")
    hannah.set_password("password")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board",
                   formed_on=date(YEAR - 1, 3, 1))
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub",
                   stripe_key="rk_test_x")
    other = Business(name="Somebody Else LLC", short_name="Somebody Else", slug="else", sales_source="manual")
    db.session.add_all([boss, hannah, bbb, ehq, other])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    client = Client(name="Kenali Kendrick")
    db.session.add_all([dd, client])
    db.session.flush()
    db.session.add_all([
        BusinessOwner(business_id=bbb.id, name="Michael Bean", share_percent=100),
        BusinessOwner(business_id=ehq.id, name="Michael Bean", share_percent=40),
        BusinessOwner(business_id=ehq.id, name="Kenali Kendrick", share_percent=35),
        BusinessOwner(business_id=ehq.id, name="Third Member", share_percent=25),
        BusinessOwner(business_id=other.id, name="Hannah Bean", share_percent=50),
        BusinessOwner(business_id=other.id, name="A Stranger", share_percent=50),
        # $30,000 of work with sales tax on top, $4,000 spent, one DBA expense.
        Invoice(client_id=client.id, status="paid", total=21_320, tax=1_320, amount_paid=21_320,
                paid_at=datetime(YEAR, 1, 20)),
        Invoice(client_id=client.id, status="paid", total=10_000, tax=0, amount_paid=10_000,
                paid_at=datetime(YEAR, 4, 10)),
        Expense(amount=3_000.0, description="Railway", category="hosting", date=date(YEAR, 2, 5),
                business_id=bbb.id),
        Expense(amount=1_000.0, description="Data Dungeon domain", category="domain", date=date(YEAR, 4, 15),
                business_id=dd.id),
        StripeActivity(business_id=ehq.id, external_id="txn_1", kind="charge", category="charge",
                       amount=25_000.0, fee=725.0, net=24_275.0, created_on=date(YEAR, 2, 9),
                       description="Booking"),
        Expense(amount=5_000.0, description="Google Workspace", category="software", date=date(YEAR, 5, 6),
                business_id=ehq.id),
        Expense(amount=700.0, description="A later charge", category="software",
                date=TODAY + timedelta(days=3), business_id=bbb.id),
    ])
    s = TaxSetting.get()
    s.filing_status, s.your_wages, s.federal_withheld = "single", 40_000.0, 3_000.0
    db.session.commit()
    IDS = {"boss": boss.id, "hannah": hannah.id, "bbb": bbb.id, "ehq": ehq.id, "dd": dd.id,
           "other": other.id}

    print("1. Built by Bean is a Schedule C on the Books figure")
    books = books_service.summarize(bbb, date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
    est = income_tax.estimate(bbb, YEAR, TODAY)
    kw = dict(filing_status="single", your_wages=40_000.0, spouse_wages=0.0, other_income=0.0,
              federal_withheld=3_000.0, state_rate=0.0, year=YEAR)
    check("kind is schedule_c", est["kind"] == "schedule_c", est["kind"])
    check("net is the Books page's net to the cent", est["net"] == books["net"] == 30_000 - 4_700,
          (est["net"], books["net"]))
    want = round(compute(books["net"], **kw)["business_tax"], 2)
    check("tax is tax_engine's on that profit, on top of the wages", est["tax"] == want, (est["tax"], want))
    check("set aside is the same rate on profit dated through today (not the later charge)",
          abs(est["set_aside"] - round((books["net"] + 700) * est["effective"], 2)) < 0.02,
          (est["set_aside"], books["net"] + 700))
    check("four quarters, each due on deadlines.estimate_due",
          [q["due"] for q in est["quarters"]] == [deadlines.estimate_due(YEAR, q) for q in (1, 2, 3, 4)])
    check("Q1's profit is January's work less February's spend",
          est["quarters"][0]["profit"] == 20_000 - 3_000, est["quarters"][0])
    check("no members on a Schedule C", est["members"] == [])

    print("2. EntertainHQ is a partnership, and only Michael's share is his tax")
    ehq_books = books_service.summarize(ehq, date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
    pe = income_tax.estimate(ehq, YEAR, TODAY)
    check("kind is partnership", pe["kind"] == "partnership", pe["kind"])
    check("net is EntertainHQ's own books", pe["net"] == ehq_books["net"] == 20_000.0, pe["net"])
    shares = {m["name"]: m["amount"] for m in pe["members"]}
    check("each member's share of the net",
          shares == {"Michael Bean": 8_000.0, "Kenali Kendrick": 7_000.0, "Third Member": 5_000.0}, shares)
    check("Michael's row is marked as his", [m["is_michael"] for m in pe["members"]] == [True, False, False])
    check("his part is 40%", pe["profit"] == 8_000.0 and pe["michael_share"] == 0.4, pe["profit"])
    stacked = round(compute(books["net"] + 8_000, **kw)["business_tax"]
                    - compute(books["net"], **kw)["business_tax"], 2)
    check("its tax is what his share adds on top of Built by Bean's profit", pe["tax"] == stacked,
          (pe["tax"], stacked))
    check("the companies add up to the whole return",
          abs(est["tax"] + pe["tax"] - pe["personal"]["tax"]) < 0.02, (est["tax"], pe["tax"], pe["personal"]))
    check("Built by Bean's estimate sees the same whole return", est["personal"] == pe["personal"])
    oe = income_tax.estimate(db.session.get(Business, IDS["other"]), YEAR, TODAY)
    check("a partnership he is not in (Hannah Bean shares only a surname) costs him nothing",
          oe["kind"] == "partnership" and oe["tax"] == 0 and oe["profit"] == 0
          and not any(m["is_michael"] for m in oe["members"]), oe["members"])
    de = income_tax.estimate(db.session.get(Business, IDS["dd"]), YEAR, TODAY)
    check("a DBA asks for its parent", de["business"].id == IDS["bbb"] and de["net"] == est["net"])
    check("the keys the Overview reads are there",
          {"kind", "net", "tax", "set_aside", "members", "quarters"} <= set(est))


def login(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True


c = application.test_client()
login(c, IDS["boss"])

print("3. The Income tax page")
page = c.get("/admin/taxes/").get_data(as_text=True)
check("opens on Built by Bean with the Books profit", money(page, "Business profit") == est["net"],
      money(page, "Business profit"))
check("and the tax", money(page, "Tax on that profit") == est["tax"], money(page, "Tax on that profit"))
check("no Stripe payout wording", not re.search(r"Stripe pay|payout|Set aside per payment", page, re.I))
check("the company switch offers both companies",
      'aria-label="Company"' in page and "EntertainHQ" in page and "Built by Bean" in page)
check("the year switch offers this year", f'data-seg="{YEAR}"' in page)
page = c.get(f"/admin/taxes/?company={IDS['ehq']}&year={YEAR}").get_data(as_text=True)
check("EntertainHQ shows its net, the members and his share",
      money(page, "Company net") == 20_000.0 and "Kenali Kendrick" in page and money(page, "Your share") == 8_000.0,
      (money(page, "Company net"), money(page, "Your share")))
check("and what his share adds, labelled as his", money(page, "What your share adds") == pe["tax"]
      and "You" in flat(page))
page = c.get(f"/admin/taxes/?company={IDS['dd']}").get_data(as_text=True)
check("a DBA's id opens its parent", money(page, "Business profit") == est["net"])
r = c.post(f"/admin/taxes/?company={IDS['ehq']}&year={YEAR}",
           data={"filing_status": "mfj", "your_wages": "50,000", "federal_withheld": "4000",
                 "state_tax_rate": "0"})
check("saving the situation comes back to the same company and year",
      r.status_code == 302 and f"company={IDS['ehq']}" in r.headers["Location"]
      and f"year={YEAR}" in r.headers["Location"], r.headers.get("Location"))
with application.app_context():
    s = TaxSetting.get()
    check("and saved it", s.filing_status == "mfj" and s.your_wages == 50_000.0, (s.filing_status, s.your_wages))

print("4. Five tabs on every tax page")
with application.app_context():
    from flask import url_for
    with application.test_request_context():
        PAGES = {
            "income": url_for("taxes.taxes_index"),
            "sales": url_for("taxes.sales_tax_index"),
            "returns": url_for("businesses.returns_index"),
            "deadlines": url_for("taxes_deadlines.index"),
            "guide": url_for("businesses.guide"),
        }
        RETURN = url_for("businesses.return_page", slug="bbb", year=YEAR, quarter=1)
ORDER = ["income", "sales", "returns", "deadlines", "guide"]
for key, url in list(PAGES.items()) + [("returns", RETURN)]:
    html = c.get(url).get_data(as_text=True)
    tabs = re.findall(r'data-tab="(\w+)"', html)
    lit = re.findall(r'data-tab="(\w+)"[^>]*\s+aria-current="page"', html)
    check(f"{url}: the five tabs in order", tabs == ORDER, tabs)
    check(f"{url}: {key} is lit", lit == [key], lit)
    check(f"{url}: one taxes panel under the kit's row",
          html.count('data-panel="taxes"') == 1 and 'data-keep="taxes-tabs"' in html)
    check(f"{url}: no 'How to file'", "How to file" not in html)
labels = re.findall(r'data-tab="\w+"[^>]*>\s*([^<\n]+?)\s*<', c.get(PAGES["guide"]).get_data(as_text=True))
check("the labels read Income tax, Sales tax, Returns, Deadlines, Guide",
      labels == ["Income tax", "Sales tax", "Returns", "Deadlines", "Guide"], labels)
check("the old tab partial is gone", not (ROOT / "templates/pm/taxes/_sales_tabs.html").exists())

print("5. CEO only, and the old URLs answer")
for url in list(PAGES.values()) + [RETURN, "/admin/taxes/?year=2025"]:
    check(f"the CEO opens {url}", c.get(url).status_code == 200)
h = application.test_client()
login(h, IDS["hannah"])
GETS = list(PAGES.values()) + [RETURN, "/admin/taxes/sales/filings/1/record.pdf", "/admin/taxes/sales/files/1"]
POSTS = ["/admin/taxes/", "/admin/taxes/sales/clients/1/exempt",
         "/admin/taxes/sales/invoices/1/project", "/admin/taxes/sales/invoices/1/taxable",
         "/admin/taxes/sales/invoices/1/back-tax", "/admin/taxes/sales/clients/1/catchup",
         "/admin/taxes/sales/clients/1/drafts", "/admin/taxes/sales/clients/1/subscriptions",
         "/admin/taxes/deadlines/done", "/admin/taxes/deadlines/undo", "/admin/taxes/flags/1/seen",
         f"/admin/taxes/sales/returns/bbb/{YEAR}/q1/record", "/admin/taxes/sales/filings/1/files",
         "/admin/taxes/sales/files/1/delete", "/admin/taxes/sales/filings/1/delete"]
for url in GETS:
    r = h.get(url)
    check(f"CMO refused GET {url}", r.status_code == 302 and "/admin/taxes" not in r.headers.get("Location", ""),
          (r.status_code, r.headers.get("Location")))
for url in POSTS:
    r = h.post(url, data={"key": "personal:2026", "filing_status": "single"})
    check(f"CMO refused POST {url}", r.status_code == 302 and "/admin/taxes" not in r.headers.get("Location", ""),
          (r.status_code, r.headers.get("Location")))
with application.app_context():
    from models import DeadlineDone
    check("and nothing she posted landed", DeadlineDone.query.count() == 0 and TaxSetting.get().filing_status == "mfj")


print("6. In a browser")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    print("  (Playwright is not installed: the browser checks were not run)")

if sync_playwright is not None:
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    PORT = free_port()
    BASE = f"http://127.0.0.1:{PORT}"
    threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                     daemon=True).start()

    STAMP = """() => {
      document.querySelector('[data-keep="taxes-tabs"]').__w = 'TABS';
      document.getElementById('pm-main').__w = 'MAIN';
      document.querySelector('aside').__w = 'SIDE';
      const f = document.querySelector('form[method="GET"]'); if (f) f.__w = 'BAR';
      window.__alive = 1; return true; }"""
    READ = """() => ({
      url: location.pathname + location.search,
      tabs: (document.querySelector('[data-keep="taxes-tabs"]') || {}).__w || null,
      main: document.getElementById('pm-main').__w || null,
      side: document.querySelector('aside').__w || null,
      bar: (document.querySelector('form[method="GET"]') || {}).__w || null,
      alive: window.__alive || null,
      lit: [...document.querySelectorAll('[data-keep="taxes-tabs"] [aria-current="page"]')].map(a => a.dataset.tab),
    })"""
    MEASURE = """() => {
      const sc = document.getElementById('pm-scroll');
      const small = [];
      if (innerWidth < 640) {
        document.querySelectorAll('#pm-main a[href], #pm-main button, #pm-main input:not([type=hidden]), #pm-main [role=combobox]').forEach(el => {
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) return;
          const st = getComputedStyle(el);
          if (st.visibility === 'hidden' || el.closest('[aria-hidden="true"]')) return;
          if (el.tagName === 'A' && el.closest('p, li, td, dd')) return;  // a link in running text
          if (r.height < 43.5) small.push((el.innerText || el.name || el.tagName).trim().slice(0, 30) + ' ' + Math.round(r.height));
        });
      }
      return { sideways: sc.scrollWidth - sc.clientWidth,
               window: document.documentElement.scrollHeight - innerHeight, small: small.slice(0, 8) };
    }"""

    for width, height in ((320, 700), (375, 812), (1600, 1000)):
        print(f"  at {width} wide:")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_context(viewport={"width": width, "height": height}, color_scheme="dark").new_page()
            pg.goto(BASE + "/login", wait_until="domcontentloaded")
            pg.fill("[name=username]", "mb")
            pg.fill("[name=password]", "password")
            pg.click("button[type=submit]")
            pg.wait_for_load_state("networkidle")
            for key in ORDER:
                pg.goto(BASE + PAGES[key], wait_until="networkidle")
                pg.wait_for_timeout(300)
                m = pg.evaluate(MEASURE)
                check(f"{width} {key}: nothing scrolls sideways", m["sideways"] <= 0, m)
                check(f"{width} {key}: the window never scrolls", m["window"] <= 0, m)
                if width < 640:
                    check(f"{width} {key}: every control is 44px tall", not m["small"], m["small"])
            pg.goto(BASE + PAGES["income"], wait_until="networkidle")
            pg.wait_for_timeout(300)
            pg.evaluate(STAMP)
            for key in ("sales", "returns", "deadlines", "guide", "income"):
                pg.evaluate(f"""() => document.querySelector('[data-keep="taxes-tabs"] [data-tab="{key}"]').click()""")
                pg.wait_for_function(f"() => location.pathname === '{PAGES[key]}'", timeout=15000)
                pg.wait_for_timeout(500)
                now = pg.evaluate(READ)
                check(f"{width} {key}: the tab row, the page and the sidebar are the same elements",
                      now["tabs"] == "TABS" and now["main"] == "MAIN" and now["side"] == "SIDE"
                      and now["alive"] == 1, now)
                check(f"{width} {key}: its tab is lit", now["lit"] == [key], now["lit"])
            pg.evaluate(STAMP)
            pg.evaluate("""() => { document.querySelector('[data-live="answer"]').__w = 'OLD';
              [...document.querySelectorAll('[aria-label="Company"] button')].find(b => /EntertainHQ/.test(b.innerText)).click(); }""")
            pg.wait_for_function("() => /company=/.test(location.search)", timeout=15000)
            pg.wait_for_timeout(600)
            after = pg.evaluate("""() => ({ bar: document.querySelector('form[method="GET"]').__w || null,
              answer: document.querySelector('[data-live="answer"]').__w || null,
              text: document.querySelector('[data-live="answer"]').innerText,
              tabs: document.querySelector('[data-keep="taxes-tabs"]').__w || null })""")
            check(f"{width}: the company switch keeps its bar and the tab row, and swaps the answer",
                  after["bar"] == "BAR" and after["tabs"] == "TABS" and after["answer"] is None
                  and "Kenali Kendrick" in after["text"], {k: v for k, v in after.items() if k != "text"})
            m = pg.evaluate(MEASURE)
            check(f"{width} EntertainHQ: nothing scrolls sideways", m["sideways"] <= 0, m)
            pg.evaluate("""() => [...document.querySelectorAll('button')].find(b => /Edit/.test(b.innerText)).click()""")
            pg.wait_for_timeout(300)
            m = pg.evaluate(MEASURE)
            check(f"{width} the situation form open: nothing sideways, controls 44px",
                  m["sideways"] <= 0 and (width >= 640 or not m["small"]), m)
            browser.close()

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
