# -*- coding: utf-8 -*-
"""Who owns what, on every document the board sends (issue #20).

Renders every client document and the Founding Customer Agreement, reads the
PDFs back with pymupdf, and holds each to the words that have to be on it:

  1. Every client document (engagement letter, statement of work, add-on,
     hosting, addendum) carries the tightened ownership terms ONCE: not a work
     made for hire, the fee is not the price of the code, Feedback, the
     client's competitors, no reverse engineering, the client's brand never on
     another customer's product, confidentiality, and the client's own
     paperwork never overriding.
  2. The statement of work opens with the deal in plain words.
  3. The Founding Customer Agreement says it is not an investment, the product
     and its name are Built by Bean's, and what happens on a shutdown: notice,
     data, and the Founding Version licensed for their own business only.
  4. The revenue share does not pick up the client terms (they are written for
     somebody paying Built by Bean, and it is the other way round).
  5. The form draws, refuses an amount that is not one, previews, is on the
     Contracts page and can be revised, and signing it contracts the client
     and writes the project's fees.

Run: python tools/test_contract_ownership.py
"""
import glob
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-ownership-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import fitz  # noqa: E402

import contract_docs  # noqa: E402
import contract_effects  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Client, Project, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def text_of(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return " ".join(" ".join(page.get_text() for page in doc).split())


def newest_preview():
    files = glob.glob(os.path.join(TMP, "previews", "*.pdf"))
    return open(max(files, key=os.path.getmtime), "rb").read() if files else b""


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    louis = Client(name="Louis Lucas", email="louis@example.test", stage="lead")
    db.session.add_all([boss, louis])
    db.session.commit()
    boss_id, louis_id = boss.id, louis.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

# Each must appear once on every client document. A phrase that shows twice is
# a clause pasted twice, which is how two copies start to disagree.
ONCE = {
    "not a work made for hire": '"work made for hire" for the Client',
    "the fee is not the price of the code": "They are not the purchase price of any software",
    "work to their request is still ours": "made at the Client's request or to the Client's specification",
    "their competitors": "including the Client's competitors",
    "no exclusivity or revenue": "no exclusivity of any kind",
    "no reverse engineering": "reverse engineer, decompile",
    "no competing product": "build or help build a competing product",
    "their ideas become ours": '("Feedback")',
    "their brand never on another product": "never put the Client's name, logo or brand",
    "their data never shown to another customer": "will never disclose it to any other customer",
    "anonymous usage data": "aggregated, de-identified information",
    "accounts in their name are theirs": "registered in the Client's name belong to the Client",
    "confidentiality, source code named": "source code, architecture and technical design",
    "their paperwork never overrides": "controls over any purchase order",
    "Built by Bean may assign it": "including to a buyer of the software",
}


def hold_client_doc(label, text):
    for what, phrase in ONCE.items():
        n = text.count(phrase)
        check(f"{label}: {what}", n == 1, f"{n} times")
    check(f"{label}: the license is still perpetual", "perpetual" in text)
    check(f"{label}: no em dash", "—" not in text)


print("THE ENGAGEMENT LETTER:")
r = c.post("/admin/contracts/new/engagement-letter", data={
    "client_id": louis_id, "date": "2026-11-06",
    "project_description": "build a property listing app", "mvp_price": "2,500"})
check("it previews", r.status_code in (302, 303), r.status_code)
hold_client_doc("letter", text_of(newest_preview()))

print("\nTHE STATEMENT OF WORK:")
r = c.post("/admin/contracts/new/statement-of-work", data={
    "client_id": louis_id, "project_name": "Listings", "project_description": "A listing app.",
    "mvp_price": "2,500", "sow_date": "2026-11-06", "delivery_date": "2026-12-15",
    "features": ["Listings", "Search"], "hosting_fee": "50", "hosting_cycle": "monthly"})
check("it previews", r.status_code in (302, 303), r.status_code)
sow = text_of(newest_preview())
hold_client_doc("SOW", sow)
check("SOW: the deal in plain words comes first",
      "In plain words" in sow and sow.index("In plain words") < sow.index("1. PROJECT SUMMARY"),
      sow[:400])

print("\nTHE SHORTER DOCUMENTS:")
addon = contract_docs.build_addon(
    client_name="Louis Lucas", product_key="other", product_name="Texting", summary="Texts.",
    includes=["Texts"], client_provides=["A number"], lead_time="2 weeks", third_party="",
    one_time_fee="500", monthly_fee="", date_str="November 06, 2026", reference="")[0]
hold_client_doc("add-on", text_of(addon))
hosting = contract_docs.build_hosting(
    client_name="Louis Lucas", application="Listings", fee="50", cycle="monthly",
    start_date="December 01, 2026", date_str="November 06, 2026")[0]
hold_client_doc("hosting", text_of(hosting))
addendum = contract_docs.build_addendum(
    client_name="Louis Lucas", original_title="Statement of Work",
    original_date="November 06, 2026", description="Adds a page.", fee_change="",
    date_str="November 06, 2026", effective="December 01, 2026")[0]
hold_client_doc("addendum", text_of(addendum))

print("\nTHE REVENUE SHARE KEEPS ITS OWN TERMS:")
share = text_of(contract_docs.build_partnership(
    partner_name="Kenali Kendrick", venture="EntertainHQ", share_pct="35",
    date_str="November 06, 2026")[0])
check("no client ownership terms on it", "Client Materials" not in share
      and "controls over any purchase order" not in share)

print("\nTHE FOUNDING CUSTOMER AGREEMENT:")
FEATURES = ["Property listings with photos", "Lead capture from each listing"]


def founding(**kw):
    base = dict(client_name="Louis Lucas", product="Deed in Hand", features=FEATURES,
                build_fee="2,500", payment="50% due at signing; 50% on delivery",
                delivery_date="December 15, 2026", hosting_fee="25",
                date_str="November 06, 2026")
    base.update(kw)
    return text_of(contract_docs.build_founding(**base)[0])


f = founding()
for what, phrase in {
    "plain words first": "In plain words",
    "not an investment": "It is not making an investment, a loan or a contribution of capital",
    "no stake or share": "no equity, membership interest",
    "the benefit does not grow with the product": "does not grow with, the number of other customers",
    "no expectation of a return": "no expectation of any financial return",
    "not a partnership": "does not create a partnership",
    "every decision is Built by Bean's": "Every decision about the Product is Built by Bean LLC's alone",
    "the product is Built by Bean's": "Deed in Hand (the \"Product\"), and everything in it",
    "the name and logo are Built by Bean's": "The name Deed in Hand, its logo and its brand were created by Built by Bean LLC",
    "not a work made for hire": '"work made for hire" for the Customer',
    "may sell to their competitors": "including to the Customer's competitors",
    "their ideas become Built by Bean's": '("Feedback")',
    "lifetime use with no license fee": "lifetime, non-exclusive, non-transferable license",
    "a fixed hosting fee that only passes on real cost": "only to pass on a real increase in what it costs",
    "and never above other customers": "never above what Built by Bean LLC charges its other customers",
    "90 days notice on a shutdown": "at least ninety (90) days written notice",
    "the Founding Version's code on a shutdown": "(the \"Founding Version\")",
    "for their own business only": "solely to run the Customer's own business",
    "never the name with it": "It does not include the name Deed in Hand",
    "a sale of the product is not a shutdown": "is not a decision to stop offering it",
    "their data stays theirs": "will never disclose the Customer's data to any other customer",
    "confidentiality": "source code, architecture and technical design",
    "their paperwork never overrides": "controls over any purchase order",
}.items():
    n = f.count(phrase)
    check(what, n == 1, f"{n} times")
check("the features are on it", all(x in f for x in FEATURES))
check("the fees are on it", "$2,500" in f and "$25/month" in f)
check("no $50 per day late fee", "$50 per day" not in f)
check("no third-party section unless asked", "DATA FROM THIRD PARTIES" not in f)
check("no em dash", "—" not in f)
g = founding(third_party_data="MLS and IDX listing data")
check("third-party data adds its own section",
      "DATA FROM THIRD PARTIES" in g and "MLS and IDX listing data" in g)
check("and the shutdown section moves along with it",
      "9. IF THE PRODUCT IS EVER SHUT DOWN" in g and "8. IF THE PRODUCT IS EVER SHUT DOWN" in f)

print("\nTHE FORM:")
r = c.get("/admin/contracts/new/founding")
check("it draws", r.status_code == 200, r.status_code)
check("the contracts page offers it", b"new/founding" in c.get("/admin/contracts/").data)
r = c.post("/admin/contracts/new/founding", data={
    "client_id": louis_id, "product": "Deed in Hand", "features": "Listings\nLeads",
    "build_fee": "lots", "hosting_fee": "25", "date": "2026-11-06"})
check("a build fee that is not an amount is refused",
      r.status_code == 302 and "/new/founding" in r.headers.get("Location", ""))
r = c.post("/admin/contracts/new/founding", data={
    "client_id": louis_id, "product": "Deed in Hand", "features": "Listings\n- Leads",
    "build_fee": "2,500", "hosting_fee": "25", "hosting_cycle": "monthly",
    "delivery_date": "2026-12-15", "date": "2026-11-06"})
check("it previews", r.status_code == 302 and "/preview" in r.headers.get("Location", ""),
      r.headers.get("Location"))
p = text_of(newest_preview())
check("what was typed is what is on it", "Leads" in p and "$2,500" in p and "$25/month" in p
      and "Deed in Hand" in p)
import pm.contract_routes as contract_routes  # noqa: E402
check("a declined one can be revised from its form",
      contract_routes.FORM_ENDPOINTS.get("founding") == "contracts.founding_form")

print("\nSIGNING IT:")
with application.test_request_context():
    client = db.session.get(Client, louis_id)
    effects = contract_effects.sow_effects(
        client=client, project=None, project_name="Deed in Hand", price=2500.0,
        mvp_date=None, maintenance_days=None, hosting_fee=25.0, hosting_cycle="monthly")
    project = contract_effects.apply_now(effects)
    client = db.session.get(Client, louis_id)
    check("the client is contracted", client.stage == "contracted", client.stage)
    project = Project.query.filter_by(client_id=louis_id, name="Deed in Hand").first()
    check("the project is made with its fees",
          project is not None and project.budget == 2500.0 and project.hosting_fee == 25.0,
          (project and project.budget, project and project.hosting_fee))
    check("and it is under contract", project is not None and project.phase == "contracted",
          project and project.phase)

print("\n" + ("all passed" if not FAIL else f"{len(FAIL)} FAILED: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
