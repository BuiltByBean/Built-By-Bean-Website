# -*- coding: utf-8 -*-
"""The Data Dungeon profit share, and the signing links that are no longer kept.

What is proved:

  1. The form asks for exactly three things about the person - full legal name,
     current address, personal email - and refuses to build without all three.
  2. The words Michael agreed are on the page: 1% of the Profit Pool, NO CAP
     with a $1,000,000 / $10,000 example, the same for a sale with a
     $20,000,000 / $200,000 example, his own pay not an expense, no ownership
     or say from this agreement (with future roles not ruled out), his right
     to cancel at any time, inheritance to children, Texas.
  3. It goes to Michael first and then to the person, at the email typed on
     the form, and it is not turned into a client.
  4. Ported from Talent Booker (its LM-145, 2026-10-06): no signer's link is
     stored. Copy link mints one at the press and hands it back once, with
     no-store, and the row still holds no link afterwards.
  5. Ported from Talent Booker (2026-10-07): a signer the portal calls
     "completed" reads Signed, not Completed and not Waiting.

Run: python tools/test_profit_share_contract.py
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-profit-share-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import re  # noqa: E402

import contract_docs  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Client, SignatureRequest, User  # noqa: E402
import pm.contract_routes as contract_routes  # noqa: E402
import signadoc_service as _real_signadoc  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


PORTAL = "https://sign.example.test"


class Portal:
    """The signing portal, stubbed the way test_place_fields stubs it, plus
    the per-signer notify call that Resend and Copy link use."""

    # Pure arithmetic on the anchors, so the real one is used.
    fields_for = staticmethod(_real_signadoc.fields_for)

    def __init__(self):
        self.calls, self.notifies, self.envelopes, self.n = [], [], {}, 0
        self.signer_status = "pending"

    def configured(self):
        return True

    def editor_url(self, envelope_id):
        return f"{PORTAL}/envelopes/{envelope_id}/edit"

    def send_for_signature(self, pdf_bytes, **kw):
        self.calls.append(kw)
        self.n += 1
        env_id = f"env-{self.n}"
        signers = kw.get("signers")
        self.envelopes[env_id] = {"id": env_id, "status": "sent", "signers": signers}
        return {"id": env_id, "status": "sent", "mailMode": "smtp",
                "links": [{"signerId": s["id"], "url": f"{PORTAL}/sign/{s['id']}-first"}
                          for s in signers]}

    def list_envelopes(self):
        return list(self.envelopes.values())

    def get_envelope(self, envelope_id):
        env = self.envelopes.get(envelope_id, {})
        return {"id": envelope_id, "events": [],
                "signers": [dict(s, status=self.signer_status) for s in env.get("signers", [])]}

    def resend(self, envelope_id, signer_id, email=True):
        self.notifies.append((envelope_id, signer_id, email))
        return {"url": f"{PORTAL}/sign/{signer_id}-fresh-{len(self.notifies)}",
                "emailed": email, "mailMode": "smtp"}


portal = Portal()
contract_routes.signadoc = portal

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    db.session.commit()
    boss_id = boss.id
    clients_before = Client.query.count()

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

NAME = "Jordan Alexander Whitfield"
ADDRESS = "4821 Shoal Creek Blvd, Apt 12, Austin, TX 78756"
EMAIL = "jordan.whitfield@example.test"


print("THE FORM:")
r = c.get("/admin/contracts/new/profit-share")
body = r.data.decode("utf-8", "replace")
check("it draws", r.status_code == 200, r.status_code)
for field in ("participant_name", "participant_address", "participant_email"):
    check(f"it has a blank for {field}", f'name="{field}"' in body)
check("no client picker: these people are not clients", 'name="client_id"' not in body)
_no_comments = re.sub(r"<!--.*?-->", "", body, flags=re.S)
check("and no native select (LM-2)", "<select" not in _no_comments)
check("the contracts page links to it",
      "new/profit-share" in c.get("/admin/contracts/").data.decode("utf-8", "replace"))


print("\nALL THREE OR NOTHING:")
FORM = {"participant_name": NAME, "participant_address": ADDRESS,
        "participant_email": EMAIL, "date": "2026-10-27"}
for missing in ("participant_name", "participant_address", "participant_email"):
    r = c.post("/admin/contracts/new/profit-share", data={**FORM, missing: "  "})
    check(f"refused without {missing}",
          r.status_code == 302 and r.headers["Location"].endswith("/new/profit-share"),
          (r.status_code, r.headers.get("Location")))


print("\nTHE WORDS ON THE PAGE:")
pdf_bytes = contract_docs.build_profit_share(
    participant_name=NAME, participant_address=ADDRESS, date_str="October 27, 2026",
    countersign=True)[0]
try:
    import fitz
except ImportError:
    fitz = None
    check("pymupdf is installed, so the rendered page was read back", False,
          "pip install pymupdf")
if fitz:
    path = os.path.join(TMP, "ps.pdf")
    with open(path, "wb") as fh:
        fh.write(pdf_bytes)
    doc = fitz.open(path)
    text = " ".join(" ".join(p.get_text() for p in doc).split())
    doc.close()
    for phrase, what in (
            (NAME, "their full legal name"),
            (ADDRESS, "their current address"),
            ("1% of that month's Profit Pool", "1% of the monthly profit pool"),
            ("There is no cap, ceiling or maximum on the Profit Share", "NO CAP on the monthly share"),
            ("totals $1,000,000 in a year, the Participant's Profit Share for that year is $10,000",
             "the $1M -> $10K example"),
            ("There is no cap, ceiling or maximum on the Sale Payment", "NO CAP on a sale"),
            ("sold for a Sale Profit of $20,000,000, the Participant's Sale Payment would be $200,000",
             "the $20M sale -> $200K example"),
            ("1% of profits, paid monthly", "the share line says 1% of profits, paid monthly"),
            ("Nothing in this Agreement prevents the Participant from later being offered or "
             "receiving employment, ownership, equity, stock, options",
             "future employment or ownership is not ruled out"),
            ("1% of the Sale Profit", "1% of the sale"),
            ("do not include any salary, draws or distributions paid to the Company's owner",
             "his own pay is not an expense"),
            ("does not give the Participant any ownership", "no ownership"),
            ("no right to vote on, approve, be consulted on or direct any decision",
             "no say in the business"),
            ("reserves the right to cancel this Agreement at any time", "he can cancel at any time"),
            ("pass to the Participant's children", "it passes to their children"),
            ("solely responsible for all taxes", "their taxes are theirs"),
            ("Form 1099", "a 1099"),
            ("laws of the State of Texas", "Texas law")):
        check(what, phrase in text, phrase)
    check("no tax deduction from the pool any more", "Taxes for a month" not in text)
    check("no em dash anywhere", "\N{EM DASH}" not in text)
    check("Michael's block keeps its Title line", "Title:" in text)


print("\nPREVIEW, THEN SEND:")
r = c.post("/admin/contracts/new/profit-share", data=FORM)
check("it previews first", r.status_code == 302 and "/preview/" in r.headers["Location"],
      r.headers.get("Location"))
token = r.headers["Location"].rstrip("/").split("/preview/")[-1]
page = c.get(f"/admin/contracts/preview/{token}").data.decode("utf-8", "replace")
check("the preview names who it is for, not 'No client'", NAME in page and "No client" not in page)
check("and fills the signer in from the form", f'value="{EMAIL}"' in page)
check("and says it comes to Michael first", "your</span> signature" in page)

send = {**FORM, "previewed": "1", "preview_token": token, "preview_action": "send",
        "signer_name": NAME, "signer_email": EMAIL}
r = c.post("/admin/contracts/new/profit-share", data=send)
call = portal.calls[-1] if portal.calls else {}
signers = call.get("signers") or []
check("Michael signs first, then them",
      [s.get("id") for s in signers] == ["bbb", "client"] and call.get("signing_order") == "sequential",
      (signers, call.get("signing_order")))
check("at the personal email typed on the form",
      len(signers) == 2 and signers[1].get("email") == EMAIL, signers)
check("Michael is sent straight to sign it",
      r.status_code == 302 and r.headers["Location"].startswith(f"{PORTAL}/sign/bbb"),
      r.headers.get("Location"))
field_types = sorted({(f["signerId"], f["type"]) for f in call.get("fields", [])})
check("they get a signature and a date field",
      ("client", "signature") in field_types and ("client", "date") in field_types, field_types)

with application.app_context():
    row = SignatureRequest.query.filter_by(kind="profit_share").first()
    check("the row is its own kind", row is not None and row.kind_label == "Profit share",
          row and row.kind_label)
    check("it is not filed against a client", row is not None and row.client_id is None)
    check("THE PORT: no signing link is stored", row is not None and not row.signing_url,
          row and row.signing_url)
    check("and nobody became a client", Client.query.count() == clients_before)
    row_id = row.id if row else 0
check("a declined one reopens this form",
      contract_routes.FORM_ENDPOINTS.get("profit_share") == "contracts.profit_share_form")


print("\nCOPY LINK, MINTED AT THE PRESS:")
detail = c.get(f"/admin/contracts/{row_id}").data.decode("utf-8", "replace")
check("the page offers Copy link", "Copy link" in detail)
check("and prints no link of anybody's", f"{PORTAL}/sign/" not in detail, re.findall(r".{60}sign.example.test/sign/[^\"<s]*", detail))
r = c.post(f"/admin/contracts/{row_id}/link")
data = r.get_json() or {}
check("the press gets a fresh link", r.status_code == 200
      and str(data.get("url", "")).startswith(f"{PORTAL}/sign/client-fresh"), (r.status_code, data))
check("without emailing anybody", portal.notifies and portal.notifies[-1][2] is False,
      portal.notifies)
check("and it is not cached", "no-store" in (r.headers.get("Cache-Control") or ""))
with application.app_context():
    check("the row still holds no link afterwards",
          not db.session.get(SignatureRequest, row_id).signing_url)

r = c.post(f"/admin/contracts/{row_id}/resend")
with application.app_context():
    check("Resend does not store one either",
          not db.session.get(SignatureRequest, row_id).signing_url)


print("\nTHE PORTAL'S WORD FOR SIGNED:")
portal.signer_status = "completed"
detail = c.get(f"/admin/contracts/{row_id}").data.decode("utf-8", "replace")
check("a signer the portal calls completed reads Signed",
      ">Signed</p>" in detail, re.findall(r'text-surface-200">([^<]*)</p>', detail))
portal.signer_status = "pending"
detail = c.get(f"/admin/contracts/{row_id}").data.decode("utf-8", "replace")
check("and one still to sign reads Waiting", ">Waiting</p>" in detail)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
