# -*- coding: utf-8 -*-
"""The business map: a network of everything that makes a business run.

Michael, 2026-11-02: "a network of everything that's making this product
run", with the surfaces people touch (marketing site, app, portals, phone
apps, status site, admin board), who uses them, the vendors behind each,
and the outcomes that cross the app's boundary ("how does this product let
our customers know there's an outage?"), each answered by its lines.

This boots the board on a throwaway SQLite database, runs the four map
migrations in order, and proves:

  1. The seed: needs and their connections; each business's services off
     its repo; the correction (Railway bucket, not AWS); then the network:
     surfaces, audiences, the outcomes that cross the boundary, and every
     old row carried into nodes and edges before the old tables went.
  2. The layout: the business in the middle, surfaces on the first ring,
     services behind the surfaces they power, audiences outside, outcomes
     between; nothing on a ring overlapping; a hole for an unfilled
     essential; every line with its why; a service's playbook line drawn
     unless the business wrote its own.
  3. The pages draw, the data rides in single-quoted x-data, and the
     presses: add a surface and an audience, connect them, save, remove a
     node and its lines, fetch a mark off a URL once, and never reach
     another business's node.

Run: python tools/test_business_map.py
"""
import importlib.util
import math
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-map-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Business, BusinessEdge, BusinessNeed, BusinessNode, Playbook, User  # noqa: E402
import business_map  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 0.0}

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
MIGRATIONS = ("c7f2a9e41d05_the_business_map", "e5a3c7b19d42_media_is_on_railway_not_aws",
              "f1d6b8c3a924_what_the_map_delivers", "a2c9e7d14b58_the_map_is_a_network")
LATER = ("b6d1f3a8c729_more_questions_a_partner_asks", "c0e4b7d2a915_tiles_adopt_their_playbook")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def run_migration(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"migrations/versions/{name}.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()
    return mig


def table_names():
    import sqlalchemy as sa
    return set(sa.inspect(db.engine).get_table_names())


with application.test_request_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    for slug, name, logo in (("stripe", "Stripe", "pm/logos/stripe.svg"), ("railway", "Railway", ""),
                             ("postgres", "PostgreSQL", ""), ("github", "GitHub", ""), ("resend", "Resend", ""),
                             ("cloudflare", "Cloudflare", ""), ("signadoc", "Signadoc", ""), ("twilio", "Twilio", ""),
                             ("apns", "APNs", ""), ("app-store", "App Store", ""), ("aws", "AWS", "")):
        db.session.add(Playbook(slug=slug, display_name=name, logo_path=logo, is_active=True))
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq", sales_source="manual",
                   admin_url="https://entertainhq.com/admin")
    other = Business(name="Other Co", slug="other-co", sales_source="manual")
    db.session.add_all([boss, ehq, other])
    db.session.commit()
    ids = dict(boss=boss.id, ehq=ehq.id, other=other.id)

    # The old tables are built by create_all no more (the models are gone), so
    # the first three migrations make them, fill them, and the fourth moves
    # everything across: exactly the path production took.
    print("THE SEED:")
    for name in MIGRATIONS[:3]:
        run_migration(name)
    import sqlalchemy as sa
    with db.engine.begin() as conn:
        before_services = conn.execute(sa.text("SELECT COUNT(*) FROM business_services WHERE business_id = :b"), {"b": ids["ehq"]}).scalar()
        before_caps = conn.execute(sa.text("SELECT COUNT(*) FROM business_capabilities WHERE business_id = :b"), {"b": ids["ehq"]}).scalar()
        before_links = conn.execute(sa.text("SELECT COUNT(*) FROM business_capability_links")).scalar()
        conn.execute(sa.text("INSERT INTO business_services (business_id, name, role, status, notes) VALUES (:b, 'Hand typed', 'Typed by hand', 'running', '')"),
                     {"b": ids["other"]})
    mig = run_migration(MIGRATIONS[3])
    tables = table_names()
    check("the old tables are gone", not ({"business_services", "business_capabilities", "business_links",
                                             "business_capability_links"} & tables), tables & {"business_services"})
    e = db.session.get(Business, ids["ehq"])
    kinds = {}
    for n in e.nodes:
        kinds.setdefault(n.kind, []).append(n)
    check("every service moved across", len(kinds.get("service", [])) == before_services, (len(kinds.get("service", [])), before_services))
    check("every outcome moved across, plus the two that cross the boundary",
          len(kinds.get("outcome", [])) == before_caps + 2, (len(kinds.get("outcome", [])), before_caps))
    check("a business the seed does not know keeps its hand-typed row",
          [n.name for n in db.session.get(Business, ids["other"]).nodes] == ["Hand typed"])
    names = {n.name for n in kinds.get("surface", [])}
    check("the surfaces are on it: the site, the app, the portals, the phones, the status site, the board",
          {"Marketing site", "The app", "Staff portal", "Talent portal", "Client portal", "iOS app", "Android app",
           "Status site", "Admin board", "Support inbox"} <= names, names)
    status = next(n for n in kinds["surface"] if n.name == "Status site")
    check("the status site has its address", status.url == "https://status.entertainhq.com" and status.surface_kind == "status")
    check("the people are on it", {"Tenants", "Talent", "Tenant staff", "Partners", "Michael", "Texas"} <= {n.name for n in kinds.get("audience", [])})
    outage = next(n for n in kinds["outcome"] if n.name == "Tenants are told about an outage")
    check("an outcome that crosses the boundary is honest about its state", outage.status == "in_progress")
    by_id = {n.id: n for n in e.nodes}
    touching = {by_id[x.from_node_id if x.to_node_id == outage.id else x.to_node_id].display_name
                for x in e.edges if outage.id in (x.from_node_id, x.to_node_id)}
    check("and is wired to the status site, Cloudflare and the tenants", {"Status site", "Cloudflare", "Tenants"} <= touching, touching)
    proposals = next(n for n in kinds["outcome"] if n.name == "Tenants send proposals to their clients")
    touching = {by_id[x.from_node_id if x.to_node_id == proposals.id else x.to_node_id].display_name
                for x in e.edges if proposals.id in (x.from_node_id, x.to_node_id)}
    check("proposals are answered by the client portal, Resend, Signadoc and Stripe",
          {"Client portal", "Resend", "Signadoc", "Stripe"} <= touching, touching)
    stripe = next(n for n in kinds["service"] if n.playbook and n.playbook.slug == "stripe")
    check("an old outcome's lines came across as edges",
          any({x.from_node_id, x.to_node_id} == {stripe.id, next(n for n in kinds["outcome"] if n.name == "Customers charge their clients").id}
              for x in e.edges))
    check("no edge joins a thing to itself", all(x.from_node_id != x.to_node_id for x in e.edges))
    run_migration(MIGRATIONS[3])
    check("running it again adds nothing", len(db.session.get(Business, ids["ehq"]).nodes) == len(e.nodes))

    # The playbook filed after the seed, and the tile that should wear it.
    db.session.add(Playbook(slug="mercury", display_name="Mercury", is_active=True))
    db.session.commit()
    for name in LATER:
        run_migration(name)
    e = db.session.get(Business, ids["ehq"])
    merc = next(n for n in e.nodes if n.display_name == "Mercury")
    check("Mercury's tile adopted the Mercury playbook", merc.playbook is not None and merc.playbook.slug == "mercury")
    check("Zapier, which EntertainHQ does not use, is off the map", not any(n.display_name == "Zapier" for n in e.nodes))
    check("the eight later outcomes are on it", any(n.name == "Talent gets paid" and n.status == "missing" for n in e.nodes))

    print("\nTHE LAYOUT:")
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    nodes = {n["key"]: n for n in m["nodes"]}
    cx, cy = m["center"]["x"], m["center"]["y"]
    check("the business is in the middle", nodes["center"]["x"] == cx and nodes["center"]["y"] == cy)

    def ring_of(n):
        return math.hypot(n["x"] - cx, n["y"] - cy)

    for kind, r in business_map.RING.items():
        ok = all(abs(ring_of(n) - r) < 1 for n in m["nodes"] if n["kind"] == kind)
        check(f"every {kind} sits on its ring", ok)
    check("a hole sits on the services ring", all(abs(ring_of(n) - business_map.RING["service"]) < 1 for n in m["nodes"] if n["kind"] == "hole"))
    for kind in ("surface", "service", "outcome", "audience"):
        ring = [n for n in m["nodes"] if n["kind"] in ((kind, "hole") if kind == "service" else (kind,))]
        too_close = []
        for i in range(len(ring)):
            for j in range(i + 1, len(ring)):
                d = math.hypot(ring[i]["x"] - ring[j]["x"], ring[i]["y"] - ring[j]["y"])
                if d < business_map.NODE_WIDTH[kind] * 0.9:
                    too_close.append((ring[i]["name"], ring[j]["name"], round(d)))
        check(f"no two {kind}s overlap", not too_close, too_close[:3])

    def angle(n):
        return math.atan2(n["y"] - cy, n["x"] - cx)

    def near(a, b, tol=1.2):
        d = abs((angle(a) - angle(b) + math.pi) % (2 * math.pi) - math.pi)
        return d < tol

    status_s = next(n for n in m["nodes"] if n["name"] == "Status site")
    tenants = next(n for n in m["nodes"] if n["name"] == "Tenants")
    cf = next(n for n in m["nodes"] if n["name"] == "Cloudflare")
    powered = [next(n for n in m["nodes"] if n["name"] == s) for s in ("Marketing site", "The app", "Status site")]
    check("a service sits behind a surface it powers", any(near(cf, s, 1.2) for s in powered))
    check("an audience sits outside what it uses", near(tenants, next(n for n in m["nodes"] if n["name"] == "The app"), 1.6)
          or near(tenants, status_s, 1.6))
    check("a hole is drawn for the unfilled essential", any(n["kind"] == "hole" and n["name"] == "Accounting" for n in m["nodes"]))
    check("every line says why", all(e["why"] for e in m["edges"] if not e["derived"]), [e for e in m["edges"] if not e["derived"] and not e["why"]][:2])
    merc = next(n for n in m["nodes"] if n["name"] == "Mercury")
    pb = next((e for e in m["edges"] if {e["a"], e["b"]} == {f"n{stripe.id}", merc["key"]}), None)
    check("the playbook's line between Stripe and Mercury is drawn, with its why", pb is not None and pb["derived"] and "Payouts" in pb["why"], pb)
    db.session.add(BusinessEdge(business_id=ids["ehq"], from_node_id=stripe.id, to_node_id=merc["id"], why="Every Tuesday."))
    db.session.commit()
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    pb = next(e for e in m["edges"] if {e["a"], e["b"]} == {f"n{stripe.id}", merc["key"]})
    check("the business's own line wins over the playbook's", not pb["derived"] and "Tuesday" in pb["why"])
    check("the counts add up", m["counts"]["surfaces"] == len(kinds["surface"]) and m["counts"]["holes"] >= 1
          and m["counts"]["gaps"] >= 1, m["counts"])

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("\nTHE PAGES:")
r = c.get(f"/admin/businesses/{ids['ehq']}/map")
page = r.get_data(as_text=True)
check("the map draws", r.status_code == 200, r.status_code)
check("its data rides in a single-quoted x-data", "x-data='bizMap({" in page)
check("it never scrolls the window", "contained-scroll" in page)
check("the status site and the outage question are on it", "Status site" in page and "told about an outage" in page)
check("no em dash on it", chr(0x2014) not in page)
page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
check("the business page carries the counts and opens the map", "What runs it" in page and f"/admin/businesses/{ids['ehq']}/map" in page)
r = c.get(f"/admin/businesses/{ids['ehq']}/map/edit?need=accounting")
page = r.get_data(as_text=True)
check("the edit page draws, grouped by kind", r.status_code == 200 and "What they use" in page and "What it delivers" in page, r.status_code)
check("a hole preselects its need", "Accounting (Money)" in page)

print("\nTHE PRESSES:")
with application.test_request_context():
    other_node = db.session.get(Business, ids["other"]).nodes[0].id
    acct = BusinessNeed.query.filter_by(slug="accounting").one().id
r = c.post(f"/admin/businesses/{ids['ehq']}/map/nodes", data={"kind": "surface", "name": "Partner portal", "surface_kind": "portal",
                                                              "status": "building", "role": "Where partners read the numbers.",
                                                              "url": ""}, follow_redirects=True)
with application.test_request_context():
    portal = BusinessNode.query.filter_by(business_id=ids["ehq"], name="Partner portal").first()
    check("a surface can be added", portal is not None and portal.kind == "surface" and portal.status == "building" and portal.surface_kind == "portal")
    portal_id = portal.id
c.post(f"/admin/businesses/{ids['ehq']}/map/nodes", data={"kind": "audience", "name": "Investors", "role": "Who might put money in."})
with application.test_request_context():
    inv = BusinessNode.query.filter_by(business_id=ids["ehq"], name="Investors").first()
    check("a person can be added", inv is not None and inv.kind == "audience" and inv.status == "")
    inv_id = inv.id
c.post(f"/admin/businesses/{ids['ehq']}/map/edges", data={"from_node_id": inv_id, "to_node_id": portal_id, "why": "They read the numbers here."})
with application.test_request_context():
    edge = BusinessEdge.query.filter_by(from_node_id=inv_id, to_node_id=portal_id).first()
    check("two things can be connected with a why", edge is not None and "numbers" in edge.why)
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    check("and the new person sits outside the new surface", near(next(n for n in m["nodes"] if n["name"] == "Investors"),
                                                                 next(n for n in m["nodes"] if n["name"] == "Partner portal"), 1.0))
r = c.post(f"/admin/businesses/{ids['ehq']}/map/nodes", data={"kind": "service", "role": "no name, no playbook"}, follow_redirects=True)
check("a service with neither a playbook nor a name is refused", b"needs a name" in r.data)
c.post(f"/admin/businesses/{ids['ehq']}/map/nodes", data={"kind": "service", "need_id": acct, "name": "QuickBooks", "status": "setting_up",
                                                          "role": "The books."})
with application.test_request_context():
    m = br._map_for(db.session.get(Business, ids["ehq"]))
    check("filling the hole closes it", not any(n["kind"] == "hole" and n["name"] == "Accounting" for n in m["nodes"]))
    qb_id = BusinessNode.query.filter_by(business_id=ids["ehq"], name="QuickBooks").one().id
c.post(f"/admin/businesses/{ids['ehq']}/map/nodes/{portal_id}", data={"kind": "surface", "name": "Partner portal", "surface_kind": "portal",
                                                                      "status": "live", "role": "Live now."})
with application.test_request_context():
    check("a node saves", db.session.get(BusinessNode, portal_id).status == "live")
r = c.post(f"/admin/businesses/{ids['ehq']}/map/nodes/{other_node}", data={"kind": "service", "name": "Hijacked"})
with application.test_request_context():
    check("another business's node cannot be reached", r.status_code == 404 and db.session.get(BusinessNode, other_node).name == "Hand typed")
c.post(f"/admin/businesses/{ids['ehq']}/map/nodes/{portal_id}/delete")
with application.test_request_context():
    check("removing a node removes it and its lines", db.session.get(BusinessNode, portal_id) is None
          and BusinessEdge.query.filter_by(to_node_id=portal_id).count() == 0)

fetched = []
br.app_icon_service.fetch = lambda url: (fetched.append(url) or (b"\x89PNG" + b"0" * 100, "png", url))
c.post(f"/admin/businesses/{ids['ehq']}/map/marks", follow_redirects=True)
with application.test_request_context():
    status_node = BusinessNode.query.filter_by(business_id=ids["ehq"], name="Status site").one()
    check("the press fetches a mark for the status site off its URL", status_node.icon_file is not None
          and any("status.entertainhq.com" in u for u in fetched), fetched[:3])
    mark_url = status_node.mark_url
    check("and the tile shows it", mark_url.endswith(f"/map/nodes/{status_node.id}/icon"))
r = c.get(mark_url)
check("served with nosniff", r.status_code == 200 and r.headers.get("X-Content-Type-Options") == "nosniff")
before = len(fetched)
c.post(f"/admin/businesses/{ids['ehq']}/map/marks", follow_redirects=True)
check("a thing already asked is not asked again", all("status.entertainhq" not in u for u in fetched[before:]))

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
