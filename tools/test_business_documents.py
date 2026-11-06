# -*- coding: utf-8 -*-
"""Which papers each company must hold, the warning when one is missing, and
the signed door a company's own app reads them through (issue #31).

Michael, 2026-11-06: "a place where I store my business like IRS documents
and ... my Texas sales license ... pointed out to me when there is no upload
... if I'm over in the Entertain HQ admin portal ... you can see kind of
really nice PDF overlays." This boots the board on a throwaway SQLite
database and proves:

  1. What a company must hold follows what it is (business_papers): a formed
     company its Certificate of Formation and IRS EIN letter, one that
     collects Texas sales tax its permit, one with several owners its company
     agreement, a DBA only its Assumed Name Certificate, an idea nothing.
  2. The business page draws each one held, missing (with its own Upload and
     Not needed) or set aside (with Ask for it), and no paper twice.
  3. Needs attention carries one row per company missing a paper, naming
     each, the sidebar badge counts it, and an upload clears it at once.
     Nobody but the CEO sees the rows or can press anything.
  4. The hub: a company's app lists and fetches only its own papers, signed;
     another company's id answers exactly like an id that does not exist; a
     DBA's app never sees its company's papers; every answer is private,
     no-store; a bad signature is refused.

Run: python tools/test_business_documents.py
"""
import base64
import io
import os
import pathlib
import re
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-docs-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, BusinessDocument, BusinessLocation,  # noqa: E402
                    BusinessOwner, DeadlineDone, User)
import business_papers  # noqa: E402
import hub  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 0.0}

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
PDF = b"%PDF-1.4\n" + b"1" * 300
PERMIT = b"%PDF-1.4\n" + b"2" * 300


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", role="cmo")
    hannah.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   formed_on=date(2024, 1, 17), sales_source="manual")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   texas_taxpayer_number="32108463343", sales_tax_webfile="RT123456",
                   sales_source="hub", hub_slug="entertainhq", hub_secret="s3cret")
    idea = Business(name="Next Thing", slug="next-thing", conceived_on=date(2026, 6, 1),
                    sales_source="manual")
    db.session.add_all([boss, hannah, bbb, ehq, idea])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="data-dungeon", parent_id=bbb.id, sales_source="manual",
                  hub_slug="data-dungeon", hub_secret="dd-secret")
    db.session.add(dd)
    db.session.add(BusinessLocation(business_id=bbb.id, label="Paris", webfile_number="00001"))
    for name in ("Michael Bean", "Kenali Kendrick", "Third Member"):
        db.session.add(BusinessOwner(business_id=ehq.id, name=name))
    db.session.add(BusinessOwner(business_id=bbb.id, name="Michael Bean", share_percent=100))
    db.session.commit()
    ids = dict(boss=boss.id, hannah=hannah.id, bbb=bbb.id, ehq=ehq.id, idea=idea.id, dd=dd.id)

    print("WHAT EACH MUST HOLD:")
    got = {k: business_papers.required_kinds(db.session.get(Business, v))
           for k, v in (("bbb", bbb.id), ("ehq", ehq.id), ("idea", idea.id), ("dd", dd.id))}
    check("a single-owner company that sells in Texas: formation, EIN, permit",
          got["bbb"] == ["formation", "ein", "sales_permit"], got["bbb"])
    check("three members add their company agreement",
          got["ehq"] == ["formation", "ein", "sales_permit", "operating"], got["ehq"])
    check("an idea the state has nothing on holds nothing", got["idea"] == [], got["idea"])
    check("a DBA holds only its Assumed Name Certificate", got["dd"] == ["assumed_name"], got["dd"])
    labels = dict(BusinessDocument.KINDS)
    check("the two new kinds are offered", labels.get("ein") == "IRS EIN letter"
          and labels.get("sales_permit") == "Sales and use tax permit")
    check("every required kind is a kind the form offers",
          all(k in labels for k in business_papers.WHY))


def as_user(uid):
    cl = application.test_client()
    with cl.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return cl


c = as_user(ids["boss"])


def attention():
    return c.get("/admin/attention/").get_data(as_text=True)


def badge_total():
    with application.test_request_context():
        from flask_login import login_user
        from pm.attention_routes import attention_counts
        with application.app_context():
            login_user(db.session.get(User, ids["boss"]))
            business_papers.forget()
            return attention_counts()["papers"]


print("\nTHE BUSINESS PAGE:")
page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
missing = re.findall(r'data-paper-missing="([a-z_]+)"', page)
check("each missing paper is its own row", missing == ["formation", "ein", "sales_permit", "operating"], missing)
check("with its own Upload form for that kind",
      page.count('name="kind" value="ein"') == 1 and 'aria-label="Upload the IRS EIN letter"' in page)
check("and a Not needed press", page.count(">Not needed</button>") == 4)
check("the card says how many are missing", "4 missing" in page)
check("the card is a live region", 'data-live="papers"' in page)

print("\nNEEDS ATTENTION:")
page = attention()
rows = re.findall(r'data-papers-row="(\d+)"', page)
check("one row per company missing a paper (Built by Bean, Data Dungeon, EntertainHQ)",
      sorted(rows) == sorted([str(ids["bbb"]), str(ids["dd"]), str(ids["ehq"])]), rows)
check("the row names every missing paper",
      "Missing Certificate of Formation, IRS EIN letter, Sales and use tax permit, Operating Agreement" in page)
check("an idea is not asked for anything", f'data-papers-row="{ids["idea"]}"' not in page)
check("the sidebar badge counts the same rows", badge_total() == 3, badge_total())
check("the row opens the company's Documents card",
      f'/admin/businesses/{ids["ehq"]}#documents' in page)

print("\nUPLOADING CLEARS IT:")
r = c.post(f"/admin/businesses/{ids['ehq']}/documents",
           data={"kind": "ein", "document": (io.BytesIO(PDF), "EntertainHQ LLC IRS Letter.pdf")},
           content_type="multipart/form-data", follow_redirects=True)
page = r.get_data(as_text=True)
check("the EIN letter is held", 'data-paper-missing="ein"' not in page and "EntertainHQ LLC IRS Letter.pdf" in page)
card = page[page.index('data-live="papers"'):]
check("and drawn once, as one row", len(re.findall(r'data-paper="\d+"', card)) == 1
      and card.count(">EntertainHQ LLC IRS Letter.pdf</p>") == 1)
check("three now missing", "3 missing" in page)
c.post(f"/admin/businesses/{ids['ehq']}/documents",
       data={"kind": "sales_permit", "document": (io.BytesIO(PERMIT), "Texas Sales and Use Tax Permit.pdf")},
       content_type="multipart/form-data")
page = attention()
check("the attention row names only what is still missing",
      "Missing Certificate of Formation, Operating Agreement" in page)
c.post(f"/admin/businesses/{ids['ehq']}/papers/formation/needed", data={"needed": "0"})
c.post(f"/admin/businesses/{ids['ehq']}/papers/operating/needed", data={"needed": "0"})
page = attention()
check("set aside as not needed, the company's row goes", f'data-papers-row="{ids["ehq"]}"' not in page)
check("and the badge with it, at once", badge_total() == 2, badge_total())
page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
check("the page says it was set aside, with Ask for it",
      'data-paper-waived="operating"' in page and ">Ask for it</button>" in page)
check("All on file", "All on file" in page)
c.post(f"/admin/businesses/{ids['ehq']}/papers/operating/needed", data={"needed": "1"})
page = attention()
check("Ask for it brings it back", "Missing Operating Agreement" in page)
r = c.post(f"/admin/businesses/{ids['ehq']}/papers/assumed_name/needed", data={"needed": "0"})
check("a kind it is not asked for cannot be set aside", r.status_code == 404, r.status_code)
with application.app_context():
    check("and nothing was written", not DeadlineDone.query.filter(
        DeadlineDone.key.like(f"paper:{ids['ehq']}:assumed_name")).count())

print("\nONLY THE CEO:")
h = as_user(ids["hannah"])
page = h.get("/admin/attention/").get_data(as_text=True)
check("another login sees no paper rows", "data-papers-row" not in page)
r = h.post(f"/admin/businesses/{ids['ehq']}/papers/operating/needed", data={"needed": "0"})
with application.app_context():
    check("and cannot set one aside", not DeadlineDone.query.filter_by(
        key=f"paper:{ids['ehq']}:operating").count() and r.status_code in (302, 403), r.status_code)
r = h.get(f"/admin/businesses/{ids['ehq']}")
check("or open the business page", r.status_code in (302, 403), r.status_code)

with application.app_context():
    ehq_docs = {d.kind: d.id for d in BusinessDocument.query.filter_by(business_id=ids["ehq"])}
    db.session.add(BusinessDocument(business_id=ids["bbb"], kind="ein", stored_name="bbb-ein.pdf",
                                    original_name="Built by Bean EIN.pdf", size=10))
    db.session.commit()
    bbb_doc = BusinessDocument.query.filter_by(business_id=ids["bbb"]).one().id
r = c.get(f"/admin/businesses/documents/{ehq_docs['ein']}")
check("a paper opens as itself, private and nosniff",
      r.data == PDF and r.headers.get("Cache-Control") == "private, no-store"
      and r.headers.get("X-Content-Type-Options") == "nosniff", r.headers.get("Cache-Control"))
r = application.test_client().get(f"/admin/businesses/documents/{ehq_docs['ein']}")
check("and to nobody signed out", r.status_code in (302, 401) and PDF not in r.data, r.status_code)

print("\nTHE HUB:")
anon = application.test_client()


def signed(path, payload, slug="entertainhq", secret="s3cret"):
    body = hub.canonical(payload)
    ts, sig = hub.sign(secret, body)
    return anon.post(path, data=body, content_type="application/json",
                     headers={hub.ORIGIN_HEADER: slug, hub.TIMESTAMP_HEADER: ts, hub.SIGNATURE_HEADER: sig})


r = anon.post("/api/hub/documents", data=b"{}", content_type="application/json",
              headers={hub.ORIGIN_HEADER: "entertainhq", hub.TIMESTAMP_HEADER: "1", hub.SIGNATURE_HEADER: "x"})
check("a bad signature is refused", r.status_code == 401, r.status_code)
r = signed("/api/hub/documents", {}, secret="wrong")
check("so is the wrong secret", r.status_code == 401, r.status_code)
r = signed("/api/hub/documents", {})
data = r.get_json() or {}
check("its own app lists its papers", r.status_code == 200
      and sorted(d["kind"] for d in data.get("documents", [])) == ["ein", "sales_permit"], data)
check("and none of another company's",
      all(d["id"] != bbb_doc for d in data.get("documents", [])))
check("with what it must hold and the state of each",
      {x["kind"]: x["state"] for x in data.get("required", [])}
      == {"formation": "waived", "ein": "held", "sales_permit": "held", "operating": "missing"},
      data.get("required"))
check("the list is private, no-store", r.headers.get("Cache-Control") == "private, no-store")
r = signed("/api/hub/documents/get", {"id": ehq_docs["sales_permit"]})
got = r.get_json() or {}
check("it fetches its own paper whole", r.status_code == 200
      and base64.b64decode(got.get("data", "")) == PERMIT and got.get("kind") == "sales_permit")
check("private, no-store", r.headers.get("Cache-Control") == "private, no-store")
mine = signed("/api/hub/documents/get", {"id": bbb_doc})
none = signed("/api/hub/documents/get", {"id": 999999})
check("another company's paper answers exactly like one that does not exist",
      mine.status_code == none.status_code == 404 and mine.get_json() == none.get_json())
r = signed("/api/hub/documents", {}, slug="data-dungeon", secret="dd-secret")
data = r.get_json() or {}
check("a DBA's app never sees its company's papers",
      r.status_code == 200 and data.get("documents") == []
      and [x["kind"] for x in data.get("required", [])] == ["assumed_name"], data)
r = signed("/api/hub/documents/get", {"id": bbb_doc}, slug="data-dungeon", secret="dd-secret")
check("nor fetch one", r.status_code == 404, r.status_code)
r = signed("/api/hub/documents/get", {"id": "x"})
check("a nonsense id is a 404, not a crash", r.status_code == 404, r.status_code)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
