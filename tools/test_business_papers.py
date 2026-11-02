# -*- coding: utf-8 -*-
"""A business's three dates, its age, and its paperwork on file.

Michael, 2026-11-02: when a business was first an idea, when it launched, how
old it is; and the LLC documents LegalZoom holds, kept on the board for each
business. This boots the board on a throwaway SQLite database and proves:

  1. Age reads the way a person says it, in whole calendar months, and a
     business turns a month older on the day of the month it launched.
  2. The tile leads with the date it names: Launched, else Formed, else
     Conceived ("In the works"), and a formation date never reads as a launch.
  3. The form keeps all three dates and refuses an idea dated after its launch.
  4. Papers: kept with their kind, opened under their own name with nosniff,
     removed from the disk with their row; a file of the wrong kind is refused
     by name; one title is not stamped onto several files.

Run: python tools/test_business_papers.py
"""
import io
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-papers-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Business, BusinessDocument, User  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
br.get_stripe_invoice_totals = lambda ttl=300: {"revenue": 0.0}

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
PDF = b"%PDF-1.4\n" + b"0" * 200


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("AGE:")
T = date(2026, 11, 2)
for day, want in ((date(2024, 1, 17), "2 years, 9 months"), (date(2025, 11, 2), "1 year"),
                  (date(2026, 10, 3), "4 weeks"), (date(2026, 10, 2), "1 month"),
                  (date(2026, 10, 30), "3 days"), (date(2026, 11, 2), "Today"),
                  (date(2026, 12, 1), "Not yet"), (date(2025, 12, 3), "10 months")):
    got = br.age(day, today=T)
    check(f"{day} reads {want}", got == want, got)

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   formed_on=date(2024, 1, 17), sales_source="manual")
    idea = Business(name="Next Thing", slug="next-thing", conceived_on=date(2026, 6, 1),
                    sales_source="manual")
    db.session.add_all([boss, bbb, idea])
    db.session.commit()
    ids = dict(boss=boss.id, bbb=bbb.id, idea=idea.id)
    print("\nTHE MILESTONE:")
    check("formed, not launched: the tile says Formed", bbb.milestone == ("Formed", date(2024, 1, 17)))
    check("only an idea: the tile says Conceived", idea.milestone == ("Conceived", date(2026, 6, 1)))
    bbb.launched_on = date(2024, 3, 1)
    check("launched: the tile says Launched", bbb.milestone == ("Launched", date(2024, 3, 1)))
    bbb.launched_on = None
    db.session.commit()

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

page = c.get("/admin/businesses").get_data(as_text=True)
check("the list labels a formation date as Formed", "Formed" in page and "Launched" not in page)
check("and an idea as in the works", "In the works" in page)

print("\nTHE FORM:")
base = {"name": "Built by Bean LLC", "short_name": "Built by Bean", "slug": "built-by-bean",
        "sales_source": "manual", "is_active": "1", "formed_on": "2024-01-17"}
c.post(f"/admin/businesses/{ids['bbb']}/edit",
       data=dict(base, conceived_on="2023-09-01", launched_on="2024-03-01"))
with application.app_context():
    b = db.session.get(Business, ids["bbb"])
    check("all three dates are kept", (b.conceived_on, b.formed_on, b.launched_on)
          == (date(2023, 9, 1), date(2024, 1, 17), date(2024, 3, 1)))
r = c.post(f"/admin/businesses/{ids['bbb']}/edit",
           data=dict(base, conceived_on="2024-06-01", launched_on="2024-03-01"), follow_redirects=True)
with application.app_context():
    check("an idea after its launch is refused", db.session.get(Business, ids["bbb"]).conceived_on
          == date(2023, 9, 1) and "idea has to come before" in r.get_data(as_text=True))
page = c.get(f"/admin/businesses/{ids['bbb']}").get_data(as_text=True)
check("the page shows its age", ">Age<" in page)
check("and all three dates", all(x in page for x in ("Conceived", "Formed", "Launched")))

print("\nTHE PAPERS:")
r = c.post(f"/admin/businesses/{ids['bbb']}/documents",
           data={"kind": "formation", "title": "Certificate of Formation, filed by LegalZoom",
                 "document": (io.BytesIO(PDF), "cof.pdf")}, content_type="multipart/form-data")
with application.app_context():
    doc = BusinessDocument.query.one()
    doc_id, stored = doc.id, doc.stored_name
    check("a paper is kept with its kind and title",
          doc.kind == "formation" and doc.title.startswith("Certificate of Formation"))
    check("on the volume, under business_documents",
          os.path.exists(os.path.join(TMP, "business_documents", stored)))
page = c.get(f"/admin/businesses/{ids['bbb']}").get_data(as_text=True)
check("the business page lists it", "Certificate of Formation, filed by LegalZoom" in page)
r = c.get(f"/admin/businesses/documents/{doc_id}")
check("it opens as itself", r.status_code == 200 and r.data == PDF and r.mimetype == "application/pdf")
check("with nosniff", r.headers.get("X-Content-Type-Options") == "nosniff")

r = c.post(f"/admin/businesses/{ids['bbb']}/documents",
           data={"kind": "nonsense", "title": "One title",
                 "document": [(io.BytesIO(PDF), "ein.pdf"), (io.BytesIO(PDF), "oa.pdf"),
                              (io.BytesIO(b"MZ" + b"0" * 100), "virus.exe")]},
           content_type="multipart/form-data", follow_redirects=True)
with application.app_context():
    rows = BusinessDocument.query.order_by(BusinessDocument.id).all()
    check("several files at once are kept", len(rows) == 3, len(rows))
    check("an unknown kind is filed as Other", rows[1].kind == "other")
    check("one title is not stamped on several files", rows[1].title == "" and rows[2].title == "")
check("the wrong kind of file is refused by name", "virus.exe" in r.get_data(as_text=True))

c.post(f"/admin/businesses/documents/{doc_id}/delete")
with application.app_context():
    check("removing it drops the row", db.session.get(BusinessDocument, doc_id) is None)
check("and the file", not os.path.exists(os.path.join(TMP, "business_documents", stored)))
with application.app_context():
    b = db.session.get(Business, ids["idea"])
    db.session.add(BusinessDocument(business_id=b.id, stored_name="x.pdf", original_name="x.pdf"))
    db.session.commit()
    db.session.delete(b)
    db.session.commit()
    check("a business deleted takes its paper rows with it",
          BusinessDocument.query.filter_by(original_name="x.pdf").count() == 0)

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("ALL PASS")
