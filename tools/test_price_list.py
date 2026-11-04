# -*- coding: utf-8 -*-
"""Products folded into the MVP Builder as its Price list tab (2026-11-04).

  1. The builder carries two tabs, Packages and Price list, and the price list
     draws every product with its price and its Sell button.
  2. The sidebar has no Products link any more, and the MVP Builder link is
     lit on the price list.
  3. /admin/products/ forwards to the price list with its query string, so
     the Handbook's "Sell it" (?sell=<id>) still opens the dialog.
  4. Saving a price, selling and erasing a sale all come back to the price
     list, and the sale shows there.
  5. Nothing that reads Product broke: a package's build prompt and its
     picker, and a note's link to a product.

Run: python tools/test_price_list.py
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-price-list-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["SIGNATURE_REFRESH_SECONDS"] = "0"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import url_for  # noqa: E402

from app import create_app  # noqa: E402
from models import (db, Client, MvpPackage, MvpPackageItem, Product,  # noqa: E402
                    ProductSale, User)

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
    client = Client(name="Acme Hauling", email="acme@example.test")
    texting = Product(slug="texting", name="Texting", price=1500, category="comms",
                      summary="Messages to and from customers")
    db.session.add_all([boss, client, texting])
    db.session.flush()
    package = MvpPackage(client_id=client.id, name="Acme Dispatch")
    db.session.add(package)
    db.session.flush()
    db.session.add(MvpPackageItem(package_id=package.id, kind="product",
                                  product_id=texting.id, name="Texting"))
    db.session.commit()
    ids = dict(boss=boss.id, client=client.id, texting=texting.id, package=package.id)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True


def page(path):
    r = c.get(path)
    return r.status_code, r.get_data(as_text=True)


print("1. TWO TABS")
code, packages = page("/admin/mvp/")
check("the builder draws", code == 200, code)
check("with a Price list tab", 'href="/admin/mvp/price-list"' in packages and "Price list" in packages)
code, prices = page("/admin/mvp/price-list")
check("the price list draws", code == 200, code)
check("it is the current tab", re.search(r'aria-current="page"[^>]*>\s*Price list', prices) is not None)
check("titled MVP Builder", re.search(r'id="pm-page-title"[^>]*>\s*MVP Builder', prices) is not None)
check("with the price, in commas", "1,500" in prices)
check("and the Sell button", f'data-sell="{ids["texting"]}"' in prices)

print("2. THE SIDEBAR")
check("no Products link", re.search(r'</svg>\s*Products\s*</a>', prices) is None)
builder = re.search(r'<a href="/admin/mvp/"\s+class="sidebar-link([^"]*)"', prices)
check("the MVP Builder link is lit on the price list", builder and "active" in builder.group(1),
      builder and builder.group(1))

print("3. THE OLD ADDRESS")
r = c.get("/admin/products/")
check("forwards to the price list", r.status_code == 302 and r.headers["Location"].endswith("/admin/mvp/price-list"),
      r.headers.get("Location"))
r = c.get(f"/admin/products/?sell={ids['texting']}")
check("carrying ?sell=", r.headers["Location"].endswith(f"/admin/mvp/price-list?sell={ids['texting']}"),
      r.headers.get("Location"))
code, opened = page(f"/admin/mvp/price-list?sell={ids['texting']}")
check("which the page reads", f'const want = "{ids["texting"]}";' in opened)

print("4. THE PRESSES COME BACK HERE")
r = c.post(f"/admin/products/{ids['texting']}/price", data={"price": "1,750", "has_monthly": "1"})
check("saving a price returns to the price list", r.headers.get("Location", "").endswith("/admin/mvp/price-list"),
      r.headers.get("Location"))
with application.app_context():
    p = db.session.get(Product, ids["texting"])
    check("and saves it", p.price == 1750 and p.monthly_price == 50, (p.price, p.monthly_price))
r = c.post("/admin/products/sell", data={"product_id": ids["texting"], "client_id": ids["client"],
                                         "price": "1,750", "new_project_name": "Acme Texting"})
check("selling opens the add-on contract", "/admin/contracts/new/add-on" in r.headers.get("Location", ""),
      r.headers.get("Location"))
code, prices = page("/admin/mvp/price-list")
check("the sale is listed", "Acme Texting" in prices)
with application.app_context():
    sale_id = ProductSale.query.one().id
r = c.post(f"/admin/products/sales/{sale_id}/delete")
check("erasing returns to the price list", r.headers.get("Location", "").endswith("/admin/mvp/price-list"))
r = c.post("/admin/products/sell", data={"product_id": 0, "client_id": 0})
check("a sell with nothing picked comes back too",
      r.headers.get("Location", "").endswith("/admin/mvp/price-list"))

print("5. WHAT READS PRODUCT")
code, detail = page(f"/admin/mvp/{ids['package']}")
check("the package picker still offers products", code == 200 and "Texting" in detail, code)
code, prompt = page(f"/admin/mvp/{ids['package']}/prompt.txt")
check("the build prompt still carries the product", "WHAT RUNS UNDERNEATH" in prompt and "Texting" in prompt)
with application.test_request_context():
    from models import Note
    note = Note(product_id=ids["texting"])
    with application.app_context():
        note.product = db.session.get(Product, ids["texting"])
        links = note.links
        hit = [link for link in links if link[0] == "product"]
        check("a note's product link resolves",
              hit and url_for(hit[0][2], **hit[0][3]) == "/admin/mvp/price-list", hit)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all passed")
