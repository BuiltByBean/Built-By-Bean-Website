# -*- coding: utf-8 -*-
"""The icon vocabulary: one drawing per concept, in the Handbook, through the
door, in every build prompt, and the only way the board draws an icon.

Michael, 2026-11-04: "give me an icon overhaul ... icons that I like to use
for concepts" (icon_vocabulary.py, icon_defaults.py). Proves:

  1. The defaults are a vocabulary: every concept has a drawing that survives
     clean_svg unchanged, and no two concepts share a drawing.
  2. clean_svg keeps geometry and nothing else: a script, a handler, another
     viewBox and a foreign element are refused.
  3. The board draws no icon of its own: no <svg> in templates/pm outside
     the brand marks and the business map's lines, every icon() names a
     concept, and the sidebar's links each wear a different one.
  4. A session reads the vocabulary through the door, whole or by concept.
  5. A session changes a drawing through the door; the board draws the new
     one at once; a drawing another concept has is refused; Revert puts the
     old one back; a new concept can be created and retired.
  6. The Icons tab draws every concept, and History lists the change without
     writing a row for a concept nobody touched.
  7. A build prompt carries THE ICONS, one line per concept.

Run: python tools/test_icons.py
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-icons-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None

import icon_vocabulary  # noqa: E402
from icon_defaults import DEFAULTS  # noqa: E402
from app import create_app  # noqa: E402
from models import db, CatalogueProposal, Client, IconConcept, MvpPackage, User  # noqa: E402

application = create_app()
application.config["GUIDANCE_API_KEY"] = "test-key"
application.config["WTF_CSRF_ENABLED"] = False
AUTH = {"Authorization": "Bearer test-key"}
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("1. The defaults are a vocabulary")
slugs = [d["slug"] for d in DEFAULTS]
check("every concept once", len(slugs) == len(set(slugs)))
unclean = [d["slug"] for d in DEFAULTS if icon_vocabulary.clean_svg(d["svg"]) != (d["svg"], None)]
check("every drawing is already clean", not unclean, unclean)
keys = {}
for d in DEFAULTS:
    keys.setdefault(icon_vocabulary.drawing_key(d["svg"]), []).append(d["slug"])
twice = [v for v in keys.values() if len(v) > 1]
check("no drawing stands for two concepts", not twice, twice)
check("every concept says what it is", all(d["name"] and d["group"] in dict(icon_vocabulary.GROUPS)
                                             for d in DEFAULTS))
check("the concepts the rule names are all there",
      {"sign-out", "close", "search", "back", "edit", "delete", "add", "copy", "download",
       "external"} <= set(slugs))

print("2. A drawing is geometry and nothing else")
for bad, why in [
    ('<svg viewBox="0 0 24 24"><script>alert(1)</script></svg>', "a script"),
    ('<svg viewBox="0 0 24 24"><foreignObject/></svg>', "a foreign element"),
    ('<svg viewBox="0 0 20 20"><path d="M1 1h4"/></svg>', "another viewBox"),
    ('<path d="M1 1h4" onclick="x()"/><image href="x"/>', "an image"),
    ('<path d="url(javascript:x)"/>', "a url in the geometry"),
    ("", "nothing"),
]:
    check(f"refuses {why}", icon_vocabulary.clean_svg(bad)[0] is None)
inner, err = icon_vocabulary.clean_svg('<path d="M1 1h4" onclick="x()" stroke-width="9"/>')
check("drops a handler and a stroke style, keeps the shape", inner == '<path d="M1 1h4"/>', inner)

print("3. The board draws no icon of its own")
ALLOWED_SVG = {"components/brand_icons.html": None,
               # The map's lines layer, and its surface tiles, whose shapes
               # come from the vocabulary through icon_shapes and x-html.
               "businesses/map.html": 2}
pm = ROOT / "templates" / "pm"
stray = []
used = set()
for f in pm.rglob("*.html"):
    rel = f.relative_to(pm).as_posix()
    text = f.read_text(encoding="utf-8")
    n = len(re.findall(r"<svg\b", text))
    if rel in ALLOWED_SVG:
        if ALLOWED_SVG[rel] is not None and n != ALLOWED_SVG[rel]:
            stray.append(f"{rel}: {n}")
    elif n:
        stray.append(f"{rel}: {n}")
    used |= set(re.findall(r"""\bicon\(\s*'([a-z0-9-]+)'""", text))
    for group in re.findall(r"icon_shapes\(\[([^\]]*)\]", text):
        used |= set(re.findall(r"'([a-z0-9-]+)'", group))
    for table in re.findall(r"\{% set (?:PRODUCT_ICON|section_icons|LINK_ICONS|GLYPHS) = \{(.*?)\} %\}", text, re.S):
        used |= set(re.findall(r""":\s*["']([a-z0-9-]+)["']""", table))
check("no inline <svg> on the board's pages", not stray, stray)
check("every icon() names a concept", used <= set(slugs), sorted(used - set(slugs)))
import business_map  # noqa: E402
check("every map surface is a concept", set(business_map.SURFACE_GLYPH.values()) <= set(slugs))

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    client = Client(name="Acme Events", email="a@example.test")
    db.session.add_all([boss, client])
    db.session.commit()
    package = MvpPackage(client_id=client.id, name="Acme MVP")
    db.session.add(package)
    db.session.commit()
    ids = {"boss": boss.id, "package": package.id}

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

page = c.get("/admin/practices/icons")
html = page.get_data(as_text=True)
check("the Icons tab answers", page.status_code == 200, page.status_code)
nav = html[html.find("<aside"):html.find("</aside>")]
nav_icons = re.findall(r'class="sidebar-link[^"]*"[^>]*>\s*(?:\{#.*?#\}\s*)?<svg[^>]*data-icon="([a-z0-9-]+)"', nav, re.S)
links = len(re.findall(r'class="sidebar-link', nav))
check("every sidebar link wears an icon", links and len(nav_icons) == links, (links, nav_icons))
check("and no two the same", len(nav_icons) == len(set(nav_icons)), nav_icons)
check("every svg on the page is from the vocabulary",
      len(re.findall(r"<svg\b", html)) == len(re.findall(r"<svg\b[^>]*data-icon=", html)))

print("4. A session reads it through the door")
r = c.get("/api/guidance/icons", headers=AUTH)
data = r.get_json()
check("the whole vocabulary", r.status_code == 200 and len(data["icons"]) == len(DEFAULTS))
check("with the one viewBox and stroke", data["viewBox"] == "0 0 24 24" and data["stroke_width"] == "1.5")
r = c.get("/api/guidance/icons?concept=delete", headers=AUTH).get_json()
check("by concept", [i["slug"] for i in r["icons"]] == ["delete"], [i["slug"] for i in r["icons"]])
r = c.get("/api/guidance/icons?concept=log%20out", headers=AUTH).get_json()
check("by another name for it", [i["slug"] for i in r["icons"]] == ["sign-out"], [i["slug"] for i in r["icons"]])
check("the text carries the svg", "<svg viewBox=\"0 0 24 24\"" in r["text"])
check("the door is shut without the key", c.get("/api/guidance/icons").status_code == 401)

print("5. A session changes one, and the board follows")
NEW = '<path d="M4 4h16v16H4z"/>'
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "icon", "mode": "replace", "slug": "clients", "field": "svg", "project": "Built By Bean",
    "text": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-width="2">{NEW}</svg>',
    "reason": "test"})
check("a new drawing applies", r.status_code == 200 and r.get_json().get("action") == "applied", r.get_json())
pid = r.get_json().get("id")
html = c.get("/admin/practices/icons").get_data(as_text=True)
check("the sidebar draws it at once", 'data-icon="clients" aria-hidden="true" >' + NEW in html)
with application.app_context():
    row = IconConcept.query.filter_by(slug="clients").one()
    check("stored clean", row.svg == NEW, row.svg)
    check("the old drawing is kept for Revert",
          CatalogueProposal.query.get(pid).previous == next(d["svg"] for d in DEFAULTS if d["slug"] == "clients"))
taken = next(d["svg"] for d in DEFAULTS if d["slug"] == "delete")
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "icon", "mode": "replace", "slug": "users", "field": "svg", "project": "Built By Bean",
    "text": taken, "reason": "test"})
check("a drawing another concept has is refused", r.status_code == 400 and "Delete" in r.get_json()["error"],
      r.get_json())
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "icon", "mode": "replace", "slug": "users", "field": "svg", "project": "Built By Bean",
    "text": '<script>alert(1)</script>', "reason": "test"})
check("and so is a script", r.status_code == 400)
r = c.post(f"/admin/features/inbox/{pid}/revert", follow_redirects=False)
with application.app_context():
    check("Revert puts it back", IconConcept.query.filter_by(slug="clients").one().svg
          == next(d["svg"] for d in DEFAULTS if d["slug"] == "clients"), r.status_code)
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "icon", "mode": "create", "project": "Built By Bean", "reason": "test",
    "payload": {"name": "Rocket", "group": "thing", "svg": '<path d="M2 2l20 20"/>',
                "icon_name": "rocket", "aliases": "launch, go live"}})
check("a new concept is created", r.status_code == 200 and r.get_json().get("slug") == "rocket", r.get_json())
_rb = c.get("/api/guidance/icons?concept=go%20live", headers=AUTH).get_json()
check("and read back by another name", [x["slug"] for x in _rb["icons"]] == ["rocket"],
      [x["slug"] for x in _rb["icons"]])
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "icon", "mode": "retire", "slug": "rocket", "project": "Built By Bean", "reason": "test"})
check("and retired", r.status_code == 200 and "rocket" not in
      [i["slug"] for i in c.get("/api/guidance/icons", headers=AUTH).get_json()["icons"]])

print("6. The tab and History")
html = c.get("/admin/practices/icons").get_data(as_text=True)
check("every concept is drawn on the tab",
      all(f'data-concept="{s}"' in html for s in slugs))
check("the tab is in the strip", 'href="/admin/practices/icons"' in html)
with application.app_context():
    before = IconConcept.query.count()
hist = c.get("/admin/features/inbox/")
with application.app_context():
    check("History answers without writing a row", hist.status_code == 200 and IconConcept.query.count() == before,
          (hist.status_code, before))
check("History names the concept", "Clients" in hist.get_data(as_text=True))

print("7. The build prompt carries the icons")
with application.test_request_context():
    from pm.mvp_routes import build_package_prompt
    with application.app_context():
        prompt = build_package_prompt(db.session.get(MvpPackage, ids["package"]))
block = prompt[prompt.find("THE ICONS"):]
block = block[:block.find("\n\n", block.find("\n\n") + 2)]
check("a section of its own", "THE ICONS" in prompt)
check("one line per concept", block.count("\n  - ") == len(DEFAULTS), block.count("\n  - "))
check("naming get_icons", "get_icons" in block)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
