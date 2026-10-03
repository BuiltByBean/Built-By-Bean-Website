# -*- coding: utf-8 -*-
"""Sending a filed PDF whose signature lines this board cannot know.

The send page used to have one press, and it put a signature box and a date
box at the bottom of the last page. That is right for most contracts and
wrong for a document signed in several places, or by several people - the
EntertainHQ company agreement is signed six times by its manager alone. The
second press stops at a draft in SignaDoc and hands over to its editor.

  1. The send page offers both presses.
  2. Place fields makes a DRAFT: send=False, and no fields at all - never the
     default box, which is the guess this path exists to avoid.
  3. It lands in the portal's editor for that envelope.
  4. The row is written now, as a draft, so the board tracks it from the
     start; its page offers the editor again, not a fresh link it cannot send.
  5. The ordinary Send still sends, with the default fields.
  6. When the draft goes out from the editor, the refresh learns who the
     signer is, so Send a fresh link works on it like any other.

Run: python tools/test_place_fields.py
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-place-fields-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
# Documents are written to the upload folder, never to a bucket, here.
for key in ("AWS_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
    os.environ.pop(key, None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Client, SignatureRequest, User  # noqa: E402
import pm.contract_routes as contract_routes  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


PORTAL = "https://sign.example.test"


class Portal:
    """The signing portal, stubbed. It answers the way the real import does:
    a draft has no links, a sent envelope has one per signer."""

    def __init__(self):
        self.calls = []
        self.envelopes = {}
        self.n = 0

    def configured(self):
        return True

    def editor_url(self, envelope_id):
        return f"{PORTAL}/envelopes/{envelope_id}/edit"

    def send_for_signature(self, pdf_bytes, **kw):
        self.calls.append(kw)
        self.n += 1
        env_id = f"env-{self.n}"
        signers = kw.get("signers") or [{"id": "client", "name": kw.get("signer_name"),
                                         "email": kw.get("signer_email")}]
        if kw.get("send") is False:
            self.envelopes[env_id] = {"id": env_id, "status": "draft", "signers": signers}
            return {"id": env_id, "status": "draft", "mailMode": "smtp", "links": []}
        self.envelopes[env_id] = {"id": env_id, "status": "sent", "signers": signers}
        return {"id": env_id, "status": "sent", "mailMode": "smtp",
                "links": [{"signerId": s["id"], "url": f"{PORTAL}/sign/{s['id']}"} for s in signers]}

    def list_envelopes(self):
        return list(self.envelopes.values())

    def get_envelope(self, envelope_id):
        return {"id": envelope_id, "signers": [], "events": []}


portal = Portal()
contract_routes.signadoc = portal

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    owner = Client(name="EntertainHQ LLC", email="hello@example.test")
    db.session.add_all([boss, owner])
    db.session.flush()
    doc = contract_routes.file_document(
        b"%PDF-1.4\n% a company agreement\n", "Company Agreement - Michael.pdf",
        client_id=owner.id)
    db.session.commit()
    boss_id, doc_id = boss.id, doc.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

FORM = {"title": "Company Agreement - Michael", "signer_name": "Michael Bean",
        "signer_email": "michael@example.test", "message": ""}

print("THE SEND PAGE:")
r = c.get(f"/admin/contracts/send/{doc_id}")
html = r.data.decode("utf-8", "replace")
check("it draws", r.status_code == 200, r.status_code)
check("it offers Send for signature", "Send for signature" in html)
check("and Place fields in SignaDoc, as its own press",
      'name="place_fields" value="1"' in html and "Place fields in SignaDoc" in html)

print("\nPLACE FIELDS:")
r = c.post(f"/admin/contracts/send/{doc_id}", data={**FORM, "place_fields": "1"})
call = portal.calls[-1] if portal.calls else {}
check("the portal is asked for a DRAFT", call.get("send") is False, call.get("send"))
check("with no fields on it - never the default box", call.get("fields") == [], call.get("fields"))
check("the press lands in that envelope's editor",
      r.status_code == 302 and r.headers.get("Location") == f"{PORTAL}/envelopes/env-1/edit",
      (r.status_code, r.headers.get("Location")))
with application.app_context():
    draft = SignatureRequest.query.filter_by(envelope_id="env-1").first()
    check("the row is written now, as a draft", draft is not None and draft.status == "draft",
          draft and draft.status)
    check("against the document it came from", draft is not None and draft.source_document_id == doc_id)
    draft_id = draft.id if draft else None

print("\nTHE DRAFT'S OWN PAGE:")
r = c.get(f"/admin/contracts/{draft_id}")
html = r.data.decode("utf-8", "replace")
check("it draws", r.status_code == 200, r.status_code)
check("it offers the editor again", f"{PORTAL}/envelopes/env-1/edit" in html)
check("and not a fresh link it has nobody to send to", "Send a fresh link" not in html)

print("\nTHE ORDINARY SEND STILL SENDS:")
r = c.post(f"/admin/contracts/send/{doc_id}", data=FORM)
call = portal.calls[-1]
check("send is left on", call.get("send") is not False, call.get("send"))
check("with the default fields", call.get("fields") == contract_routes.DEFAULT_FIELDS, call.get("fields"))
with application.app_context():
    sent = SignatureRequest.query.filter_by(envelope_id="env-2").first()
    check("to the contract's page, not the editor",
          r.status_code == 302 and r.headers.get("Location", "").endswith(f"/admin/contracts/{sent.id}"),
          r.headers.get("Location"))

print("\nWHEN THE DRAFT GOES OUT FROM THE EDITOR:")
# He placed the fields and sent it in the portal; the signer's id there is
# whatever the editor kept, and the address is what he typed there.
portal.envelopes["env-1"] = {"id": "env-1", "status": "sent",
                             "signers": [{"id": "sgn-ab12", "name": "Michael Edward Bean",
                                          "email": "michael@example.test"}]}
with application.app_context():
    changed = contract_routes.refresh_open_requests()
    row = db.session.get(SignatureRequest, draft_id)
    check("the refresh sees it went out", row.status == "sent", row.status)
    check("and learns the signer, so Resend can reach them", row.signer_ref == "sgn-ab12", row.signer_ref)
    check("taking the name the portal has", row.signer_name == "Michael Edward Bean", row.signer_name)
r = c.get(f"/admin/contracts/{draft_id}")
html = r.data.decode("utf-8", "replace")
check("its page now offers a fresh link", "Send a fresh link" in html)
check("and no longer the editor", f"{PORTAL}/envelopes/env-1/edit" not in html)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
