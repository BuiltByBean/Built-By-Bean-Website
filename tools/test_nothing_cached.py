# -*- coding: utf-8 -*-
"""Nothing behind the login may be stored by Cloudflare.

Cloudflare caches by what a URL ends in and knows nothing about logins. On
2026-11-03 the books export for both companies came back 200 to a request with no
cookies, because a signed-in press had put it in the edge cache. Proves every
route that ends in a file extension Cloudflare caches sits under a prefix that
says private, and that the answers really do say so, while static files stay
cacheable.

Run: python tools/test_nothing_cached.py
"""
import os
import pathlib
import re
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-cache-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

from app import create_app  # noqa: E402
from models import db, Business, User  # noqa: E402

application = create_app()
FAIL = []
EDGE_CACHED = re.compile(r"\.(bmp|class|css|csv|doc|docx|eot|eps|gif|ico|jar|jpeg|jpg|js|mid|midi|otf|pdf|pict|pls|png|"
                         r"ppt|pptx|ps|svg|svgz|swf|tar|tif|tiff|ttf|webp|woff|woff2|xls|xlsx|zip)$")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:200]) if detail != "" and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.commit()
    ids = (boss.id, bbb.id)

routes = [r.rule for r in application.url_map.iter_rules() if EDGE_CACHED.search(r.rule)]
check("every route ending in a cached extension is under a private prefix",
      routes and all(r.startswith(("/admin", "/api/")) for r in routes), routes)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids[0])
    s["_fresh"] = True
year = date.today().year
res = c.get(f"/admin/books/{ids[1]}/year/{year}.csv")
check("the books export is served", res.status_code == 200, res.status_code)
check("and says it is private", res.headers.get("Cache-Control") == "private, no-store", res.headers.get("Cache-Control"))
res = c.get("/admin/books/")
check("so does an ordinary admin page", "no-store" in (res.headers.get("Cache-Control") or ""), res.headers.get("Cache-Control"))
anon = application.test_client().get(f"/admin/books/{ids[1]}/year/{year}.csv")
check("a redirect to the login says so too", anon.status_code == 302 and "no-store" in (anon.headers.get("Cache-Control") or ""),
      anon.status_code)
files = sorted(p for p in (ROOT / "static").rglob("*") if p.is_file())
if files:
    res = c.get("/static/" + files[0].relative_to(ROOT / "static").as_posix())
    check("a static file stays cacheable", "no-store" not in (res.headers.get("Cache-Control") or ""),
          res.headers.get("Cache-Control"))

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
