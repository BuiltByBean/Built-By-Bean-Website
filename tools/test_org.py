# -*- coding: utf-8 -*-
"""Org: every business's people, one store, two doors (Michael, 2026-11-04).

Boots the board on a throwaway SQLite database and proves:

  1. The migration goes down and up again over the tables create_all made.
  2. Org is the CEO's: a member is sent home from every page, every save and
     every old /admin/users address; the CEO gets each page, each view, with
     an empty state on an empty org; the sidebar says Org, not Team.
  3. The board's saves: a person, a department, a responsibility; a share is
     a BusinessOwner; a chart never loops; a stale version is refused and
     changes nothing; a department holding responsibilities is not deleted.
  4. The hub: unsigned is refused; a signed read answers the org and records
     the app's logins; a save from the app changes the same rows, never a
     share, and a stale one is a 409 carrying the org as it is.
  5. The import: into an empty org, twice changes nothing, rows the app no
     longer has go, and once the board's copy is edited it is refused.
  6. The god door imports the same way, behind its bearer key.
  7. /admin/users and its write addresses land on the Logins tab, and no
     login row was touched (Mbean survives).
  8. Only companies have an org (Michael, 2026-11-04: "orgs should only be on
     primary businesses not dba"): no DBA tab, a DBA's addresses land on its
     company's org, its app's hub calls read its company's, and a business
     made a DBA carries its org onto its company's, saying what moved.

Run: python tools/test_org.py
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-org-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "door-key"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
import hub  # noqa: E402
import org_service  # noqa: E402
from models import (db, Business, BusinessOwner, OrgDepartment, OrgPerson,  # noqa: E402
                    OrgResponsibility, OrgState, User)

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
application.config["GUIDANCE_API_KEY"] = "door-key"
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


class As:
    def __init__(self, user):
        self.c = application.test_client()
        with self.c.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True

    def __getattr__(self, name):
        method = getattr(self.c, name)

        def call(*a, **kw):
            from flask import g
            g.pop("_login_user", None)
            return method(*a, **kw)
        return call


def signed(client, path, payload, slug="entertainhq", secret="ehq-secret"):
    body = hub.canonical(payload)
    ts, sig = hub.sign(secret, body)
    return client.post(path, data=body, content_type="application/json", headers={
        hub.ORIGIN_HEADER: slug, hub.TIMESTAMP_HEADER: ts, hub.SIGNATURE_HEADER: sig})


def run_migration(direction):
    spec = importlib.util.spec_from_file_location("mig", ROOT / "migrations/versions/a7d3e1c95b20_org.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        getattr(mig, direction)()
    db.session.expire_all()


EHQ_ORG = {
    "people": [{"id": 1, "email": "mbean@entertainhq.com", "name": "Michael Bean", "title": "Chief Executive Officer",
                "supervisor": None, "depts": [1, 9]},
               {"id": 2, "email": "kkendrick@entertainhq.com", "name": "Kenali Kendrick",
                "title": "Chief Operating Officer", "supervisor": 1, "depts": [1]},
               {"id": 3, "email": "tlane@entertainhq.com", "name": "Ty Lane", "title": "Chief Technology Officer",
                "supervisor": 1, "depts": [3]}],
    "departments": [{"id": 1, "name": "Strategy & Leadership", "tone": "gold", "sort": 1},
                    {"id": 3, "name": "Engineering", "tone": "blue", "sort": 3},
                    {"id": 9, "name": "Accounting", "tone": "gold", "sort": 9}],
    "responsibilities": [{"id": 1, "title": "Company vision and yearly goals", "owner": 1, "dept": 1, "sort": 1},
                         {"id": 2, "title": "Product roadmap", "owner": 2, "dept": 1, "sort": 2},
                         {"id": 3, "title": "Release pipeline", "owner": None, "dept": 3, "sort": 3}],
    "logins": [{"email": "mbean@entertainhq.com", "name": "Michael"},
               {"email": "kkendrick@entertainhq.com", "name": "Kenali"},
               {"email": "tlane@entertainhq.com", "name": "Ty"}],
}


with application.app_context():
    db.create_all()
    boss = User(username="Mbean", email="mbean@entertainhq.com", first_name="Michael", last_name="Bean", role="ceo")
    boss.set_password("x")
    hannah = User(username="hannah", email="hb@example.test", first_name="Hannah", role="cmo")
    hannah.set_password("y")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean")
    db.session.add_all([boss, hannah, bbb])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="data-dungeon", parent_id=bbb.id)
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq", hub_slug="entertainhq",
                   hub_secret="ehq-secret", hub_base_url="https://ehq.example.test")
    db.session.add_all([dd, ehq])
    db.session.flush()
    db.session.add_all([BusinessOwner(business_id=ehq.id, name="Michael Bean", share_percent=55),
                        BusinessOwner(business_id=ehq.id, name="Kenali Kendrick", share_percent=35),
                        BusinessOwner(business_id=ehq.id, name="Ty Lane", share_percent=10)])
    db.session.commit()
    hash_before = boss.password_hash
    BBB_ID, BOSS_ID, HANNAH_ID = bbb.id, boss.id, hannah.id
    users_before = User.query.count()

    print("1. The migration")
    run_migration("downgrade")
    names = set(db.inspect(db.engine).get_table_names())
    check("downgrade drops the org tables", not ({"org_people", "org_state"} & names), names)
    run_migration("upgrade")
    names = set(db.inspect(db.engine).get_table_names())
    check("upgrade puts them back", {"org_people", "org_departments", "org_person_depts",
                                     "org_responsibilities", "org_state"} <= names)
    cols = {c["name"] for c in db.inspect(db.engine).get_columns("business_owners")}
    check("business_owners learns person_id", "person_id" in cols)
    run_migration("upgrade")
    check("upgrade twice is harmless", True)

    ceo, member = As(boss), As(hannah)
    anon = application.test_client()

    print("2. Who may open it")
    pages = ["/admin/org/", f"/admin/org/{ehq.id}/", f"/admin/org/{ehq.id}/chart",
             f"/admin/org/{ehq.id}/responsibilities", f"/admin/org/{ehq.id}/departments", "/admin/org/logins/"]
    for path in pages:
        r = member.get(path)
        check(f"member sent home from {path}", r.status_code == 302 and "/admin/org" not in r.headers["Location"],
              (r.status_code, r.headers.get("Location")))
    r = member.post(f"/admin/org/{ehq.id}/save", data={"what": "person", "op": "create", "name": "Sneaky"})
    check("member cannot save", r.status_code == 302 and OrgPerson.query.filter_by(name="Sneaky").count() == 0)
    r = member.get("/admin/users/")
    check("member sent home from the old address", r.status_code == 302
          and "/admin/org" not in r.headers["Location"], r.headers.get("Location"))
    home = member.get("/admin/")
    check("and that home answers", home.status_code in (200, 302))
    r = ceo.get("/admin/org/")
    check("Org opens on the first business", r.status_code == 302 and f"/admin/org/{bbb.id}/" in r.headers["Location"],
          r.headers.get("Location"))
    for path in pages[1:]:
        r = ceo.get(path)
        check(f"CEO gets {path}", r.status_code == 200, r.status_code)
    html = ceo.get(f"/admin/org/{ehq.id}/").get_data(as_text=True)
    check("an empty org says so", 'class="empty' in html and "Nobody on EntertainHQ" in html)
    check("a tab per company, then Logins",
          all(x in html for x in ("Built by Bean", "EntertainHQ", "Logins")))
    check("and no DBA tab", "Data Dungeon" not in html)
    check("the sidebar says Org", ">\n                Org\n" in html or "Org\n            </a>" in html)
    check("and Team is gone", "Team</p>" not in html)
    check("no em dash on the page", chr(0x2014) not in html)
    for v in ("chart", "responsibilities", "departments"):
        h = ceo.get(f"/admin/org/{ehq.id}/{v}").get_data(as_text=True)
        check(f"empty {v} says so", 'class="empty' in h)
    check("an unknown business is a 404", ceo.get("/admin/org/9999/").status_code == 404)
    check("an unknown view is a 404", ceo.get(f"/admin/org/{ehq.id}/payroll").status_code == 404)

    print("5. The import")
    r = signed(anon, "/api/hub/org/import", EHQ_ORG)
    body = r.get_json()
    check("an app's org comes over into an empty org", r.status_code == 200 and body["ok"], r.get_data(as_text=True))
    check("its counts", body["imported"] == {"people": 3, "departments": 3, "responsibilities": 3}, body.get("imported"))
    db.session.expire_all()
    ty = OrgPerson.query.filter_by(business_id=ehq.id, app_ref="entertainhq:3").one()
    mike = OrgPerson.query.filter_by(business_id=ehq.id, app_ref="entertainhq:1").one()
    check("the chart came with it", ty.supervisor_id == mike.id)
    check("and the departments", [d.name for d in mike.departments] == ["Strategy & Leadership", "Accounting"])
    check("owners are linked to people by name",
          BusinessOwner.query.filter_by(business_id=ehq.id, name="Ty Lane").one().person_id == ty.id)
    r = signed(anon, "/api/hub/org/import", EHQ_ORG)
    db.session.expire_all()
    check("a second import changes nothing", r.status_code == 200 and OrgPerson.query.filter_by(business_id=ehq.id).count() == 3
          and OrgResponsibility.query.filter_by(business_id=ehq.id).count() == 3)
    fewer = dict(EHQ_ORG, responsibilities=EHQ_ORG["responsibilities"][:2])
    signed(anon, "/api/hub/org/import", fewer)
    db.session.expire_all()
    check("a row the app no longer has goes", OrgResponsibility.query.filter_by(business_id=ehq.id).count() == 2)
    signed(anon, "/api/hub/org/import", EHQ_ORG)
    db.session.expire_all()

    print("4. The hub")
    r = anon.post("/api/hub/org", data=b"{}", content_type="application/json",
                  headers={hub.ORIGIN_HEADER: "entertainhq"})
    check("unsigned is refused", r.status_code == 401, r.status_code)
    r = signed(anon, "/api/hub/org", {}, secret="wrong")
    check("a wrong secret is refused the same way", r.status_code == 401)
    r = signed(anon, "/api/hub/org", {"logins": EHQ_ORG["logins"]})
    d = r.get_json()
    check("a signed read answers the org", r.status_code == 200 and len(d["people"]) == 3)
    check("with the shares from the board",
          {p["name"]: p["share_percent"] for p in d["people"]} == {"Michael Bean": 55, "Kenali Kendrick": 35, "Ty Lane": 10})
    check("and who holds which login", all(p["app_login"] for p in d["people"])
          and next(p for p in d["people"] if p["name"] == "Michael Bean")["board_login"]["username"] == "Mbean")
    ty = OrgPerson.query.filter_by(business_id=ehq.id, app_ref="entertainhq:3").one()
    v = ty.version
    r = signed(anon, "/api/hub/org/save", {"what": "person", "op": "update", "id": ty.id, "version": v,
                                           "title": "CTO", "share_percent": 99, "by": "kkendrick@entertainhq.com"})
    db.session.expire_all()
    ty = db.session.get(OrgPerson, ty.id)
    check("a save from the app changes the board's row", r.status_code == 200 and ty.title == "CTO", r.get_data(as_text=True))
    check("but never a share", BusinessOwner.query.filter_by(business_id=ehq.id, name="Ty Lane").one().share_percent == 10)
    r = signed(anon, "/api/hub/org/save", {"what": "person", "op": "update", "id": ty.id, "version": v, "title": "Old"})
    db.session.expire_all()
    check("a stale save from the app is a 409", r.status_code == 409 and db.session.get(OrgPerson, ty.id).title == "CTO",
          r.status_code)
    check("carrying the org as it is", r.get_json() and len(r.get_json()["people"]) == 3)
    r = signed(anon, "/api/hub/org/import", EHQ_ORG)
    check("once edited, an import is refused", r.status_code == 409, r.status_code)
    db.session.expire_all()
    check("and wrote nothing", db.session.get(OrgPerson, ty.id).title == "CTO")
    other = Business(name="Other LLC", slug="other", hub_slug="other", hub_secret="other-secret")
    db.session.add(other)
    db.session.commit()
    r = signed(anon, "/api/hub/org/save", {"what": "person", "op": "update", "id": ty.id, "version": ty.version,
                                           "title": "Stolen"}, slug="other", secret="other-secret")
    db.session.expire_all()
    check("one business cannot touch another's rows", r.status_code == 404 and db.session.get(OrgPerson, ty.id).title == "CTO",
          r.status_code)

    print("3. The board's saves")
    save = f"/admin/org/{ehq.id}/save"
    ceo.post(save, data={"what": "department", "op": "create", "name": "Marketing", "tone": "amber"})
    mkt = OrgDepartment.query.filter_by(business_id=ehq.id, name="Marketing").one()
    check("a department", mkt.tone == "amber")
    ceo.post(save, data={"what": "person", "op": "create", "name": "Hannah Bean", "title": "CMO",
                         "email": "hb@example.test", "phone": "903-555-0100"})
    hb = OrgPerson.query.filter_by(business_id=ehq.id, name="Hannah Bean").one()
    check("a person", hb.title == "CMO" and hb.phone == "903-555-0100")
    mike = OrgPerson.query.filter_by(business_id=ehq.id, name="Michael Bean").one()
    r = ceo.post(save, data={"what": "person", "op": "update", "id": hb.id, "version": hb.version,
                             "supervisor": str(mike.id), "has_depts": "1", "depts": [str(mkt.id)],
                             "share_percent": "", "next": f"/admin/org/{ehq.id}/people/{hb.id}"})
    db.session.expire_all()
    hb = db.session.get(OrgPerson, hb.id)
    check("her place and department", hb.supervisor_id == mike.id and [d.name for d in hb.departments] == ["Marketing"])
    check("a save goes back where it came from", r.headers["Location"].endswith(f"/admin/org/{ehq.id}/people/{hb.id}"))
    r = ceo.post(save, data={"what": "person", "op": "update", "id": hb.id, "version": hb.version, "next": "https://evil.example/"})
    check("but never off the org", r.headers["Location"].endswith(f"/admin/org/{ehq.id}/"), r.headers["Location"])
    hb = db.session.get(OrgPerson, hb.id)
    r = ceo.post(save, data={"what": "person", "op": "update", "id": mike.id, "version": mike.version,
                             "supervisor": str(hb.id)}, follow_redirects=True)
    db.session.expire_all()
    check("the chart never loops", db.session.get(OrgPerson, mike.id).supervisor_id is None
          and "cannot report" in r.get_data(as_text=True))
    hb = db.session.get(OrgPerson, hb.id)
    old = hb.version
    ceo.post(save, data={"what": "person", "op": "update", "id": hb.id, "version": old, "title": "Chief Marketing Officer"})
    r = ceo.post(save, data={"what": "person", "op": "update", "id": hb.id, "version": old, "title": "Overwritten"},
                 follow_redirects=True)
    db.session.expire_all()
    check("a stale save on the board changes nothing", db.session.get(OrgPerson, hb.id).title == "Chief Marketing Officer")
    check("and says why", "changed that since you opened it" in r.get_data(as_text=True))
    hb = db.session.get(OrgPerson, hb.id)
    ceo.post(save, data={"what": "person", "op": "update", "id": hb.id, "version": hb.version, "share_percent": "0"})
    db.session.expire_all()
    check("a share typed on the board is a BusinessOwner",
          BusinessOwner.query.filter_by(business_id=ehq.id, person_id=hb.id).one().share_percent == 0)
    ceo.post(save, data={"what": "responsibility", "op": "create", "title": "Launch campaign",
                         "dept": str(mkt.id), "owner": str(hb.id)})
    resp = OrgResponsibility.query.filter_by(business_id=ehq.id, title="Launch campaign").one()
    check("a responsibility", resp.owner_id == hb.id and resp.dept_id == mkt.id)
    r = ceo.post(save, data={"what": "responsibility", "op": "create", "title": "No home"}, follow_redirects=True)
    check("never without a department", OrgResponsibility.query.filter_by(title="No home").count() == 0)
    ceo.post(save, data={"what": "department", "op": "delete", "id": mkt.id, "version": mkt.version})
    check("a department holding responsibilities stays", db.session.get(OrgDepartment, mkt.id) is not None)
    ceo.post(save, data={"what": "responsibility", "op": "update", "id": resp.id, "version": resp.version, "owner": ""})
    db.session.expire_all()
    check("unassigning", db.session.get(OrgResponsibility, resp.id).owner_id is None)
    dd_id = dd.id
    hp = ceo.get(f"/admin/org/{ehq.id}/people/{hb.id}")
    check("the person page", hp.status_code == 200 and "Chief Marketing Officer" in hp.get_data(as_text=True))
    other_person = ceo.get(f"/admin/org/{bbb.id}/people/{hb.id}")
    check("a person is only on their own business's page", other_person.status_code == 404)
    for v in ("", "chart", "responsibilities", "departments"):
        h = ceo.get(f"/admin/org/{ehq.id}/{v}")
        check(f"filled {v or 'people'} renders", h.status_code == 200
              and ("Marketing" if v == "departments" else "Hannah Bean") in h.get_data(as_text=True))
    r = signed(anon, "/api/hub/org/save", {"what": "person", "op": "delete", "id": ty.id, "version": db.session.get(OrgPerson, ty.id).version})
    check("a person holding the app's login is not taken off", r.status_code == 400)
    ceo.post(save, data={"what": "person", "op": "delete", "id": hb.id, "version": db.session.get(OrgPerson, hb.id).version})
    db.session.expire_all()
    check("taking somebody off unassigns what was theirs", db.session.get(OrgPerson, hb.id) is None
          and db.session.get(OrgResponsibility, resp.id) is not None)
    check("and unlinks their share", BusinessOwner.query.filter_by(person_id=hb.id).count() == 0)

    print("6. The god door")
    door = application.test_client()
    r = door.post("/api/guidance/org/import", json={"business": "Built by Bean", **EHQ_ORG, "origin": "entertainhq"})
    check("the door wants its key", r.status_code == 401, r.status_code)
    r = door.post("/api/guidance/org/import", json={"business": "Built by Bean", "origin": "seed", **EHQ_ORG},
                  headers={"Authorization": "Bearer door-key"})
    check("the door imports into an empty org", r.status_code == 200 and r.get_json()["imported"]["people"] == 3,
          r.get_data(as_text=True))
    r = door.get("/api/guidance/org?business=EntertainHQ", headers={"Authorization": "Bearer door-key"})
    check("and reads one back", r.status_code == 200 and len(r.get_json()["people"]) == 3)
    r = door.post("/api/guidance/org/import", json={"business": "EntertainHQ", **EHQ_ORG},
                  headers={"Authorization": "Bearer door-key"})
    check("and refuses over edits", r.status_code == 409)

    print("7. The old address, and the account he signs in with")
    r = ceo.get("/admin/users/")
    check("/admin/users lands on Logins", r.status_code == 301 and r.headers["Location"].endswith("/admin/org/logins/"),
          r.headers.get("Location"))
    r = ceo.get(f"/admin/users/{boss.id}/edit")
    check("an old edit link lands on the new one", r.status_code == 301
          and r.headers["Location"].endswith(f"/admin/org/logins/{boss.id}/edit"))
    r = ceo.post(f"/admin/users/{hannah.id}/reset")
    check("an old write address keeps its method", r.status_code == 307
          and r.headers["Location"].endswith(f"/admin/org/logins/{hannah.id}/reset"))
    check("a shape it never took is a 404", ceo.post(f"/admin/users/{hannah.id}/delete").status_code in (404, 405))
    h = ceo.get("/admin/org/logins/").get_data(as_text=True)
    check("the Logins tab is the old page with Org's tabs", "Mbean" in h and "EntertainHQ" in h and "Add a login" in h)
    db.session.expire_all()
    me = User.query.filter_by(username="Mbean").one()
    check("Mbean survives, password and all", me.password_hash == hash_before and me.check_password("x")
          and User.query.count() == users_before)

with application.app_context():
    print("8. Only companies have an org")
    bbb = db.session.get(Business, BBB_ID)
    dd = db.session.get(Business, dd_id)
    ceo, member = As(db.session.get(User, BOSS_ID)), As(db.session.get(User, HANNAH_ID))
    for view in ("", "chart", "responsibilities", "departments"):
        r = ceo.get(f"/admin/org/{dd.id}/{view}")
        want = f"/admin/org/{bbb.id}/" + view
        check(f"a DBA's {view or 'people'} lands on its company's", r.status_code == 301
              and r.headers["Location"].endswith(want), (r.status_code, r.headers.get("Location")))
    r = member.get(f"/admin/org/{dd.id}/")
    check("and the redirect is no way round the gate", r.status_code == 302 and "/admin/org" not in r.headers["Location"])
    r = ceo.post(f"/admin/org/{dd.id}/save", data={"what": "department", "op": "create", "name": "Left open"})
    check("a form left open on a DBA posts to its company's", r.status_code == 307
          and r.headers["Location"].endswith(f"/admin/org/{bbb.id}/save"))
    check("a DBA never gets an org row of its own",
          OrgPerson.query.filter_by(business_id=dd.id).count() == 0)
    dd.hub_slug, dd.hub_secret = "datadungeon", "dd-secret"
    db.session.commit()
    r = signed(anon, "/api/hub/org", {}, slug="datadungeon", secret="dd-secret")
    check("a DBA's own app reads its company's org", r.status_code == 200
          and r.get_json()["business"]["id"] == bbb.id, r.get_data(as_text=True)[:200])

    # A company with an org of its own is made a DBA of Built by Bean.
    side = Business(name="Side Co", slug="side-co")
    db.session.add(side)
    db.session.commit()
    sid = side.id
    for body in ({"what": "department", "op": "create", "name": "Engineering"},
                 {"what": "department", "op": "create", "name": "Field Ops", "tone": "teal"},
                 {"what": "person", "op": "create", "name": "Ty Lane", "email": "tlane@entertainhq.com"},
                 {"what": "person", "op": "create", "name": "Ann Other", "title": "Crew lead"}):
        ceo.post(f"/admin/org/{sid}/save", data=body)
    eng = OrgDepartment.query.filter_by(business_id=sid, name="Engineering").one()
    ops = OrgDepartment.query.filter_by(business_id=sid, name="Field Ops").one()
    ann = OrgPerson.query.filter_by(business_id=sid, name="Ann Other").one()
    side_ty = OrgPerson.query.filter_by(business_id=sid, name="Ty Lane").one()
    ceo.post(f"/admin/org/{sid}/save", data={"what": "person", "op": "update", "id": ann.id, "version": ann.version,
                                             "supervisor": str(side_ty.id), "has_depts": "1", "depts": [str(ops.id)]})
    ceo.post(f"/admin/org/{sid}/save", data={"what": "responsibility", "op": "create", "title": "Site safety",
                                             "dept": str(ops.id), "owner": str(side_ty.id)})
    ceo.post(f"/admin/org/{sid}/save", data={"what": "responsibility", "op": "create", "title": "Build servers",
                                             "dept": str(eng.id), "owner": str(ann.id)})
    bbb_ty = OrgPerson.query.filter_by(business_id=bbb.id, name="Ty Lane").one()
    bbb_eng = OrgDepartment.query.filter_by(business_id=bbb.id, name="Engineering").one()
    r = ceo.post(f"/admin/businesses/{sid}/edit", data={"name": "Side Co", "parent_id": str(bbb.id), "is_active": "1"},
                 follow_redirects=True)
    text = r.get_data(as_text=True)
    db.session.expire_all()
    check("made a DBA, it says what moved", "moved from Side Co" in text and "Built by Bean" in text, text[-600:] if "moved" not in text else "")
    check("nothing is left on the DBA", not any(m.query.filter_by(business_id=sid).count()
                                               for m in (OrgPerson, OrgDepartment, OrgResponsibility)))
    ann = db.session.get(OrgPerson, ann.id)
    check("a new person moves as they are", ann.business_id == bbb.id and ann.title == "Crew lead")
    check("the same person is folded onto the company's", db.session.get(OrgPerson, side_ty.id) is None
          and ann.supervisor_id == bbb_ty.id)
    check("a new department moves", db.session.get(OrgDepartment, ops.id).business_id == bbb.id
          and [d.name for d in ann.departments] == ["Field Ops"])
    check("the same department is folded onto the company's", db.session.get(OrgDepartment, eng.id) is None)
    safety = OrgResponsibility.query.filter_by(title="Site safety").one()
    servers = OrgResponsibility.query.filter_by(title="Build servers").one()
    check("responsibilities follow their people and departments",
          safety.business_id == bbb.id and safety.owner_id == bbb_ty.id
          and servers.dept_id == bbb_eng.id and servers.owner_id == ann.id)
    check("Side Co has no tab now", "Side Co" not in ceo.get(f"/admin/org/{bbb.id}/").get_data(as_text=True))
    import org_service as _os
    check("folding again moves nothing", _os.fold_into_parent(db.session.get(Business, sid)) is None)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All org checks passed.")
sys.exit(1 if FAIL else 0)
