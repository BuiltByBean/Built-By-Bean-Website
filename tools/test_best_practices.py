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
  4. History is a tab with no count and no banner: nothing waits on a yes.
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
                summary="SMS to customers"),
        Feature(slug="retired", name="Retired thing", kind="feature", is_active=False),
        Playbook(slug="twilio", display_name="Twilio", one_liner="A2P registration",
                 traps_md="Brand record cannot be edited after approval."),
        Product(slug="custom", name="Custom software build", price=5000),
        CatalogueProposal(kind="rule", target_slug="no-em-dash", field="pitfalls_md",
                          mode="replace", proposed="x", status="candidate"),
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
check("a rule, a feature and a playbook, and no product", sorted(e["type"] for e in items) ==
      ["howto", "playbook", "rule"], names)
check("a switched-off feature is not listed", "Retired thing" not in names)

print("2. The search reaches the traps")
rule = next(e for e in items if e["name"] == "No em dashes")
pb = next(e for e in items if e["type"] == "playbook")
check("a rule is found by its pitfall", "commit message" in rule["search"])
check("a playbook is found by its traps section", "brand record" in pb["search"])

print("3. One title, one strip, one sidebar link")
PAGES = {"/admin/practices/": "Everything", "/admin/features/rules": "Rules",
         "/admin/features/": "Features", "/admin/playbooks/": "Playbooks",
         "/admin/features/inbox/": "History"}
for url, tab in PAGES.items():
    r = c.get(url)
    body = r.get_data(as_text=True)
    lit = re.findall(r'aria-current="page"[^>]*>\s*([^<\n]+)', body)
    check(f"{url} renders", r.status_code == 200, r.status_code)
    check(f"{url} lights {tab}", lit and lit[0].strip() == tab, lit)
    # Called the Handbook on screen since 2026-11-04.
    check(f"{url} is titled Handbook",
          re.search(r'id="pm-page-title"[^>]*>\s*Handbook', body) is not None)
    check(f"{url} lights the Handbook sidebar link",
          re.search(r'sidebar-link active">\s*<svg[^>]*>\s*<path[^>]*/>\s*</svg>\s*Handbook', body) is not None)
    check(f"{url} has no Rules, Features, Playbooks or Cerebro sidebar link",
          not re.search(r'</svg>\s*(Rules|Features|Playbooks|Cerebro)\s*</a>', body))
    check(f"{url} shows no money", "$" not in re.sub(r"<script.*?</script>|<style.*?</style>|\$(el|dispatch|refs|watch|nextTick|store|root|data|id|event)\b", "", body, flags=re.S)
          .split('id="pm-main"', 1)[-1], url)

print("4. Nothing waits on a yes")
body = c.get("/admin/practices/").get_data(as_text=True)
check("the History tab carries no count", re.search(r'History\s*<span', body) is None)
check("there is no Waiting tab", re.search(r'>\s*Waiting\s*<', body) is None)
check("and no banner over the list", "waiting on your yes" not in body)

print("5. Cerebro is gone")
r = c.get("/admin/cerebro/")
check("its page redirects here", r.status_code == 302 and r.headers["Location"].endswith("/admin/practices/"),
      (r.status_code, r.headers.get("Location")))

print("6. Products have left Best Practices, and the sell flow still works")
check("no Products tab in the strip", "/admin/products/" not in body.split('aria-label="Handbook"', 1)[-1].split("</nav>", 1)[0])
check("a Products link of its own in the sidebar",
      re.search(r'</svg>\s*Products\s*</a>', body) is not None)
products = c.get(f"/admin/products/?sell={product_id}").get_data(as_text=True)
check("the Products page keeps its prices", "5,000" in products)
check("and is titled Products", re.search(r'id="pm-page-title"[^>]*>\s*Products', products) is not None)
check("the products page carries that Sell button", f'data-sell="{product_id}"' in products)
check("and reads the id it was given", f'const want = "{product_id}";' in products)

print("7. The door is untouched")
r = c.get("/api/guidance/brief", headers={"Authorization": "Bearer test-key"})
check("the rules brief still answers", r.status_code == 200 and "No em dashes" in r.get_data(as_text=True),
      r.status_code)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
