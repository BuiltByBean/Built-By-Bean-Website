# -*- coding: utf-8 -*-
"""The catalog and its private showcase (issue #23).

  1. The board's Catalog page draws, adds an app, saves its words, orders it,
     takes tour pictures (and refuses a file that is not one), and takes it
     out again keeping its words.
  2. A link is the only way in: a live token shows the approved apps; an
     unknown, expired or switched-off one is the same page, naming nothing;
     a link narrowed to some apps shows only those, and a picture of an app
     outside it is a 404.
  3. Every showcase answer is private, no-store, noindex and sends no
     referrer. Opening it is counted; Michael's preview is not, and needs a
     login.
  4. At a glance: platforms from the store ids, services from the code
     (through the door's /apps/services), capabilities in plain words.

Run: python tools/test_catalog.py
"""
import io
import json
import os
import pathlib
import sys
import tempfile
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-catalog-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "door-key"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import catalog_service as cs  # noqa: E402
from app import create_app  # noqa: E402
from models import db, AppLink, CatalogLink, CatalogView, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    ehq = AppLink(name="EntertainHQ", url="https://entertainhq.com", app_store_bundle_id="com.ehq",
                  play_package="com.ehq", github_url="https://github.com/BuiltByBean/EntertainHQ",
                  railway_url="https://railway.app/project/1")
    rob = AppLink(name="Robinson & Co.", url="https://admin.robinsonandcodesign.com")
    secret = AppLink(name="Not For Prospects", url="https://private.example.com")
    db.session.add_all([boss, ehq, rob, secret])
    db.session.commit()
    boss_id, ehq_id, rob_id, secret_id = boss.id, ehq.id, rob.id, secret.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True
anon = application.test_client()

print("THE BOARD'S PAGE:")
r = c.get("/admin/catalog/")
check("it draws", r.status_code == 200, r.status_code)
check("the sidebar links it", b'href="/admin/catalog/"' in r.data)
check("it is not out on the web", anon.get("/admin/catalog/").status_code in (302, 401))
c.post(f"/admin/catalog/apps/{ehq_id}/toggle")
c.post(f"/admin/catalog/apps/{rob_id}/toggle")
with application.app_context():
    check("two apps are in, in the order added", [a.id for a in cs.approved()] == [ehq_id, rob_id])
c.post(f"/admin/catalog/apps/{rob_id}/save", data={
    "catalog_name": "Vignette", "catalog_pitch": "A studio manager for interior designers.",
    "catalog_points": "Mood boards\n- Client portal", "demo_url": ""})
c.post(f"/admin/catalog/apps/{rob_id}/move", data={"dir": "up"})
with application.app_context():
    r_ = db.session.get(AppLink, rob_id)
    check("its catalog name and pitch are saved", r_.showcase_name == "Vignette" and r_.catalog_pitch)
    check("what it does reads one per line", cs.points(r_) == ["Mood boards", "Client portal"])
    check("moving it up puts it first", [a.id for a in cs.approved()] == [rob_id, ehq_id])
r = c.post(f"/admin/catalog/apps/{rob_id}/save", data={"demo_url": "javascript:alert(1)"})
with application.app_context():
    check("a demo address that is not a web address is refused",
          not db.session.get(AppLink, rob_id).demo_url)
c.post(f"/admin/catalog/apps/{rob_id}/shots", data={"shots": [(io.BytesIO(PNG), "a.png"),
                                                              (io.BytesIO(b"<svg/>"), "b.png")]},
       content_type="multipart/form-data")
with application.app_context():
    shots = db.session.get(AppLink, rob_id).catalog_shots
    check("a picture is added to the tour, a file that is not one is not", len(shots) == 1, len(shots))
    shot_id = shots[0].id
    check("and it is on the volume", os.path.exists(os.path.join(TMP, "catalog", shots[0].file)))

print("\nA LINK IS THE ONLY WAY IN:")
c.post("/admin/catalog/links", data={"label": "Louis Lucas", "days": "30", "action": "link"})
c.post("/admin/catalog/links", data={"label": "Only Vignette", "app_ids": [str(rob_id)], "days": "7",
                                     "action": "link"})
r = c.get("/admin/catalog/")
check("the page draws with apps, a tour and links on it", r.status_code == 200
      and b"Vignette" in r.data and b"Only Vignette" in r.data, r.status_code)
with application.app_context():
    every = CatalogLink.query.filter_by(label="Louis Lucas").first()
    narrow = CatalogLink.query.filter_by(label="Only Vignette").first()
    check("an all-apps link names no apps", every.app_ids is None)
    check("a narrowed one names them", narrow.app_ids == [rob_id])
    t_all, t_one, every_id = every.token, narrow.token, every.id
r = anon.get(f"/work/{t_all}")
page = r.get_data(as_text=True)
check("a live link opens the showcase with no login", r.status_code == 200, r.status_code)
check("it says who it was made for", "Prepared for Louis Lucas" in page)
check("it shows the approved apps by their catalog names", "Vignette" in page and "EntertainHQ" in page)
check("never an app that is not approved", "Not For Prospects" not in page)
check("never the tile's own name where the catalog renamed it", "Robinson" not in page)
check("it is private, no-store", r.headers.get("Cache-Control") == "private, no-store")
check("it is never indexed", "noindex" in r.headers.get("X-Robots-Tag", ""))
check("and sends no referrer with the token", r.headers.get("Referrer-Policy") == "no-referrer")
check("no em dash", chr(0x2014) not in page)
r = anon.get(f"/work/{t_all}/{rob_id}")
app_page = r.get_data(as_text=True)
check("an app's page opens", r.status_code == 200 and "Mood boards" in app_page)
check("with its tour", f"/work/{t_all}/shot/{shot_id}" in app_page)
check("the tour picture comes through the link", anon.get(f"/work/{t_all}/shot/{shot_id}").status_code == 200)
r = anon.get(f"/work/{t_one}")
check("a narrowed link shows only its apps",
      "Vignette" in r.get_data(as_text=True) and "EntertainHQ" not in r.get_data(as_text=True))
check("and an app outside it is the closed page", anon.get(f"/work/{t_one}/{ehq_id}").status_code == 404)
check("an app that is not approved is the closed page", anon.get(f"/work/{t_all}/{secret_id}").status_code == 404)
with application.app_context():
    check("opening it is counted", db.session.get(CatalogLink, every_id).open_count == 2
          and CatalogView.query.filter_by(link_id=every_id, app_link_id=rob_id).count() == 1)
gone = anon.get("/work/not-a-real-token")
gone_page = gone.get_data(as_text=True)
check("an unknown token is a 404", gone.status_code == 404)
check("that names nothing", "Vignette" not in gone_page and "Louis" not in gone_page)
c.post(f"/admin/catalog/links/{every_id}/off")
check("a switched-off link is the same page", anon.get(f"/work/{t_all}").get_data(as_text=True) == gone_page)
c.post(f"/admin/catalog/links/{every_id}/extend")
check("and extending it turns it back on", anon.get(f"/work/{t_all}").status_code == 200)
with application.app_context():
    link = db.session.get(CatalogLink, every_id)
    link.expires_at = cs.now() - timedelta(minutes=1)
    db.session.commit()
check("an expired link is the closed page", anon.get(f"/work/{t_all}").status_code == 404)
check("as is a picture through it", anon.get(f"/work/{t_all}/shot/{shot_id}").status_code == 404)

print("\nA RENAMED APP'S ICON:")
with application.app_context():
    r_ = db.session.get(AppLink, rob_id)
    r_.icon_file = "robinson-logo.png"
    db.session.commit()
    check("a renamed app does not wear the tile's icon", not r_.showcase_has_icon and r_.showcase_initials == "VI")
c.post(f"/admin/catalog/links/{every_id}/extend")
check("and the link will not serve it", anon.get(f"/work/{t_all}/icon/{rob_id}").status_code == 404)
c.post(f"/admin/catalog/apps/{rob_id}/icon", data={"icon": (io.BytesIO(PNG), "v.png")},
       content_type="multipart/form-data")
check("its own catalog icon is served instead", anon.get(f"/work/{t_all}/icon/{rob_id}").status_code == 200)

print("\nLOGOS:")
for key_, path in cs.LOGOS.items():
    check(f"the shipped logo for {key_} is on disk", (ROOT / "static" / path).exists(), path)
with application.app_context():
    check("YouTube, Spotify and AI models find a shipped logo",
          all(cs.static_logo(n) for n in ("YouTube", "Spotify", "AI models", "Signadoc")))
    check("a service with no logo anywhere is named on the board",
          cs.missing_logos(["Nobody Heard Of It", "YouTube"]) == ["Nobody Heard Of It"])

print("\nMICHAEL'S PREVIEW:")
r = c.get("/admin/catalog/preview")
check("it shows the showcase", r.status_code == 200 and b"Vignette" in r.data and b"Preview" in r.data)
before = 0
with application.app_context():
    before = CatalogView.query.count()
c.get(f"/admin/catalog/preview/{rob_id}")
with application.app_context():
    check("and is never counted", CatalogView.query.count() == before)
check("it needs a login", anon.get("/admin/catalog/preview").status_code in (302, 401))

print("\nAT A GLANCE:")
door = application.test_client()
H = {"Authorization": "Bearer door-key"}
r = door.post("/api/guidance/apps/services", headers=H,
              json={"github": "BuiltByBean/EntertainHQ", "services": ["Twilio", "Stripe", "GitHub", "Resend"]})
check("the door records an app's services", r.status_code == 200 and "Twilio" in r.get_json()["services"],
      r.get_json())
check("and refuses without the key", door.post("/api/guidance/apps/services",
                                                json={"name": "EntertainHQ", "services": []}).status_code == 401)
with application.app_context():
    e = db.session.get(AppLink, ehq_id)
    check("platforms come from the store ids", cs.platforms(e) == ["web", "ios", "android"])
    check("the stores, Railway and GitHub are services too, the names anybody knows first",
          cs.services(e) == ["App Store", "Google Play", "Stripe", "Twilio", "Resend", "Railway", "GitHub"],
          cs.services(e))
    check("each with what it is for", cs.info("Twilio")[2] == "Sends and receives text messages")
    check("found by its plain name too", cs.info("AI models")[2] != "" and cs.info("YouTube")[2] != "")
    check("capabilities are in plain words",
          cs.capabilities(e) == ["Online payments", "Automated texting", "Automated email"], cs.capabilities(e))
    check("the card's feature list leads with the phones",
          cs.highlights(e)[:2] == ["iPhone and Android apps", "Online payments"], cs.highlights(e))
    e.catalog_services_extra = "YouTube"
    e.catalog_services_hidden = "Twilio"
    db.session.commit()
    check("a service can be added and one hidden by hand",
          "YouTube" in cs.services(e) and "Twilio" not in cs.services(e), cs.services(e))
    cs.record_repo_services("BuiltByBean/EntertainHQ", ["Twilio", "Stripe"])
    check("and the night does not undo either", "Twilio" not in cs.services(e) and "YouTube" in cs.services(e))
    e.catalog_highlights = "Texting, Invoicing, Online payments"
    db.session.commit()
    check("a feature list written by hand wins", cs.highlights(e) == ["Texting", "Invoicing", "Online payments"])
    e.catalog_services_extra = e.catalog_services_hidden = e.catalog_highlights = None
    db.session.commit()
    glance = cs.overview(cs.approved())
    check("the glance gathers every app", glance["count"] == 2 and glance["platforms"] == ["web", "ios", "android"])
    n = cs.record_repo_services("BuiltByBean/EntertainHQ", ["Twilio"])
    check("the nightly audit writes onto the tile its repo is", n == 1 and db.session.get(AppLink, ehq_id).services == ["Twilio"])

print("\nSENDING IT:")
import pm.mail_service as mail_service  # noqa: E402
SENT = []
mail_service.send_new = lambda to, name, subject, text, html_body=None, client=None, app=None: SENT.append(
    (to, name, subject, text, client.id if client else None))
with application.app_context():
    from models import Client
    cl = Client(name="Louis Lucas", email="louie@example.test")
    db.session.add(cl)
    db.session.commit()
    cl_id = cl.id
r = c.post("/admin/catalog/links", data={"client_id": str(cl_id), "label": "Louis Lucas",
                                         "email": "louie@example.test", "days": "30"})
check("the armed Send emails the link", len(SENT) == 1 and SENT[0][0] == "louie@example.test", SENT)
check("with the link in it, addressed by first name",
      SENT and "/work/" in SENT[0][3] and SENT[0][3].startswith("Hi Louis,"), SENT and SENT[0][3][:60])
check("filed against the client", SENT and SENT[0][4] == cl_id)
with application.app_context():
    sent = CatalogLink.query.filter(CatalogLink.sent_at.isnot(None)).first()
    check("and the link says when it went and to whom", sent is not None and sent.email == "louie@example.test"
          and sent.client_id == cl_id)
c.post("/admin/catalog/links", data={"label": "Typed In", "email": "", "days": "30"})
check("no email, nothing is sent", len(SENT) == 1)
c.post("/admin/catalog/links", data={"label": "Just A Link", "email": "x@example.test", "days": "30", "action": "link"})
check("Just make the link sends nothing", len(SENT) == 1)
r = c.get("/admin/catalog/")
check("every app is on the page with a switch", b'role="switch"' in r.data and b"Not For Prospects" in r.data)

c.post(f"/admin/catalog/apps/{rob_id}/toggle")
with application.app_context():
    r_ = db.session.get(AppLink, rob_id)
    check("taking an app out keeps its words and tour", not r_.catalog and r_.catalog_name == "Vignette"
          and len(r_.catalog_shots) == 1)

print("\n" + ("all passed" if not FAIL else f"{len(FAIL)} FAILED: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
