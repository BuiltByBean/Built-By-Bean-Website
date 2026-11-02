# -*- coding: utf-8 -*-
"""Best Practices: the catalogue folded into one place.

Michael, 2026-11-02: features, rules, playbooks, products and Cerebro were
"a good idea on paper, but it's not functional", so they became one sidebar
link with one tab strip across the pages that already existed. This proves
the parts that would quietly come apart:

  1. Everything lists every active rule, how-to, playbook and product, and
     nothing switched off.
  2. The search text covers the traps, not only the name, so a lesson is
     found by its symptom.
  3. Every Best Practices page draws the tab strip with its own tab lit,
     under one title, and the sidebar has one link for all of them.
  4. Waiting counts the pending proposals, the inbox nothing linked to.
  5. Cerebro's page redirects here, and its link is gone.
  6. "Sell it" hands the product's id to the products page, which carries
     the Sell button that the id presses.
  7. The guidance door still answers from the same rows.

Run: python tools/test_best_practices.py
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-practices-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, CatalogueProposal, Feature, Playbook, Product, User  # noqa: E402
from pm.practices_routes import entries  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add_all([
        boss,
        Feature(slug="no-em-dash", name="No em dashes", kind="rule", category="ui",
                summary="Punctuation", pitfalls_md="Shipped in a commit message once."),
        Feature(slug="texting", name="Text messaging", kind="feature", category="comms",
                summary="SMS to customers", typical_value=1500),
        Feature(slug="retired", name="Retired thing", kind="feature", is_active=False),
        Playbook(slug="twilio", display_name="Twilio", one_liner="A2P registration",
                 traps_md="Brand record cannot be edited after approval."),
        Product(slug="custom", name="Custom software build", price=5000),
        CatalogueProposal(kind="rule", target_slug="no-em-dash", field="pitfalls_md",
                          mode="replace", proposed="x", status="pending"),
        CatalogueProposal(kind="rule", target_slug="no-em-dash", field="pitfalls_md",
                          mode="append", proposed="y", status="applied"),
    ])
    db.session.commit()
    boss_id = boss.id
    product_id = Product.query.filter_by(slug="custom").one().id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

print("1. Everything lists what is active")
with application.test_request_context():
    items = entries()
names = [e["name"] for e in items]
check("a rule, a how-to, a playbook and a product", sorted(e["type"] for e in items) ==
      ["howto", "playbook", "product", "rule"], names)
check("a switched-off feature is not listed", "Retired thing" not in names)

print("2. The search reaches the traps")
rule = next(e for e in items if e["name"] == "No em dashes")
pb = next(e for e in items if e["type"] == "playbook")
check("a rule is found by its pitfall", "commit message" in rule["search"])
check("a playbook is found by its traps section", "brand record" in pb["search"])

print("3. One title, one strip, one sidebar link")
PAGES = {"/admin/practices/": "Everything", "/admin/features/rules": "Rules",
         "/admin/features/": "How to build", "/admin/playbooks/": "Playbooks",
         "/admin/products/": "Products", "/admin/features/inbox/": "Waiting"}
for url, tab in PAGES.items():
    r = c.get(url)
    body = r.get_data(as_text=True)
    lit = re.findall(r'aria-current="page"[^>]*>\s*([^<\n]+)', body)
    check(f"{url} renders", r.status_code == 200, r.status_code)
    check(f"{url} lights {tab}", lit and lit[0].strip() == tab, lit)
    check(f"{url} is titled Best Practices",
          re.search(r'id="pm-page-title"[^>]*>\s*Best Practices', body) is not None)
    check(f"{url} lights the Best Practices sidebar link",
          re.search(r'sidebar-link active">\s*<svg[^>]*>\s*<path[^>]*/>\s*</svg>\s*Best Practices', body) is not None)
    check(f"{url} has no Rules, Features, Playbooks or Cerebro sidebar link",
          not re.search(r'</svg>\s*(Rules|Features|Playbooks|Cerebro|Products)\s*</a>', body))

print("4. Waiting counts what waits")
body = c.get("/admin/practices/").get_data(as_text=True)
waiting = re.search(r'Waiting\s*<span[^>]*>(\d+)</span>', body)
check("the Waiting tab says 1", waiting and waiting.group(1) == "1", waiting and waiting.group(0))
check("the strip above the list says one lesson waits", "1</span>\n            lesson Claude filed" in body)

print("5. Cerebro is gone")
r = c.get("/admin/cerebro/")
check("its page redirects here", r.status_code == 302 and r.headers["Location"].endswith("/admin/practices/"),
      (r.status_code, r.headers.get("Location")))

print("6. Sell it reaches the dialog")
check("the Everything row links to the products page with the id",
      f'/admin/products/?sell={product_id}' in body)
products = c.get(f"/admin/products/?sell={product_id}").get_data(as_text=True)
check("the products page carries that Sell button", f'data-sell="{product_id}"' in products)
check("and reads the id it was given", f'const want = "{product_id}";' in products)

print("7. The door is untouched")
r = c.get("/api/guidance/brief", headers={"Authorization": "Bearer test-key"})
check("the rules brief still answers", r.status_code == 200 and "No em dashes" in r.get_data(as_text=True),
      r.status_code)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
