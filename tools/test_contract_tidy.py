# -*- coding: utf-8 -*-
"""Voiding and hiding contracts from the overview page.

A lot of what was on that list was tests, and there was no way to clear them:
void lived only on a contract's own page and always redirected back to it, and
nothing could be taken off the list at all. This proves the two presses and,
more importantly, the rule that keeps them safe:

  1. The overview lists everything, and the tiles count what is on the screen.
  2. Hide takes a FINISHED contract off the list, leaving the row and its
     envelope alone; the page then offers to show what is hidden.
  3. ?hidden=1 shows it, marked, with a press to put it back.
  4. A contract still OUT for signature cannot be hidden - a live signing link
     nobody is watching is the one thing a tidy-up must not leave behind.
  5. Voiding from the list comes back to the list, not to the detail page.
  6. A void the portal answers 404 to settles the row here (that envelope does
     not exist, so nothing is out for signature) and says so.
  7. A void that fails because the portal could not be REACHED changes nothing.

Run: python tools/test_contract_tidy.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-contracts-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Client, SignatureRequest, User  # noqa: E402
import pm.contract_routes as contract_routes  # noqa: E402
from signadoc_service import SignaDocError  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# The portal, stubbed. Nothing here reaches the network, and each test says
# what the portal answers.
class Portal:
    def __init__(self):
        self.voided = []
        self.raises = None

    def configured(self):
        return True

    def void_envelope(self, envelope_id, reason=""):
        if self.raises:
            raise self.raises
        self.voided.append((envelope_id, reason))
        return {"status": "voided"}


portal = Portal()
contract_routes.signadoc = portal
# Status is normally refreshed from the portal on the way in; there is no
# portal here and that is not what is being tested.
contract_routes.refresh_open_requests = lambda: 0


def row(**kw):
    base = dict(title="Engagement Letter", kind="engagement_letter",
                signer_name="Ty Lane", signer_email="ty@example.test",
                status="completed", created_at=datetime.now(timezone.utc))
    base.update(kw)
    r = SignatureRequest(**base)
    db.session.add(r)
    return r


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add_all([boss, Client(name="Test Owner", email="owner@example.test")])
    db.session.flush()
    signed = row(envelope_id="env-signed", title="Engagement Letter - Ty Lane")
    test_one = row(envelope_id="env-void", title="Engagement Letter - Hannah Bean", status="voided")
    live = row(envelope_id="env-live", title="SOW - Live One", status="sent", kind="sow")
    gone = row(envelope_id="env-gone", title="SOW - Portal Forgot", status="sent", kind="sow")
    db.session.commit()
    ids = {"signed": signed.id, "test_one": test_one.id, "live": live.id, "gone": gone.id}
    boss_id = boss.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True


def page(path="/admin/contracts/"):
    r = c.get(path)
    return r.status_code, r.data.decode("utf-8", "replace")


def listed(html, row_id):
    """Whether a contract has a row in the table.

    By its own link, not by the signer's name: a flash saying what was just
    hidden carries the title too, and the first version of this test read
    that and called the row still listed.
    """
    return f'href="/admin/contracts/{row_id}"' in html


print("THE LIST:")
code, html = page()
check("the overview draws", code == 200, code)
check("every contract is on it", all(listed(html, i) for i in ids.values()), code)
check("nothing says hidden yet", "Show hidden" not in html)

print("\nHIDING A FINISHED ONE:")
r = c.post(f"/admin/contracts/{ids['test_one']}/hide",
           data={"next": "/admin/contracts/"}, follow_redirects=False)
check("the press lands back on the list", r.status_code == 302 and r.headers["Location"].endswith("/admin/contracts/"),
      (r.status_code, r.headers.get("Location")))
with application.app_context():
    hidden_row = db.session.get(SignatureRequest, ids["test_one"])
    check("the row is flagged, not deleted", hidden_row is not None and hidden_row.archived_at is not None)
    check("and its envelope was never touched", portal.voided == [])
code, html = page()
check("it is off the list", not listed(html, ids["test_one"]))
check("the list offers to show it", "Show hidden (1)" in html, html.count("Show hidden"))
check("the others are still there", listed(html, ids["signed"]) and listed(html, ids["live"]))

print("\nSEEING AND UNHIDING IT:")
code, html = page("/admin/contracts/?hidden=1")
check("?hidden=1 shows it", listed(html, ids["test_one"]))
check("marked as hidden", "Hidden" in html)
check("with a press to put it back", f"/admin/contracts/{ids['test_one']}/unhide" in html)
r = c.post(f"/admin/contracts/{ids['test_one']}/unhide", data={"next": "/admin/contracts/"})
code, html = page()
check("unhiding puts it back on the list", listed(html, ids["test_one"]))

print("\nTHE RULE - A LIVE CONTRACT CANNOT BE HIDDEN:")
r = c.post(f"/admin/contracts/{ids['live']}/hide", data={"next": "/admin/contracts/"},
           follow_redirects=True)
body = r.data.decode("utf-8", "replace")
with application.app_context():
    still = db.session.get(SignatureRequest, ids["live"])
    check("it stays on the list", still.archived_at is None)
check("and the refusal says what to do instead", "Void it first" in body, body[-400:])
code, html = page()
check("the live one offers Void and not Hide",
      f"/admin/contracts/{ids['live']}/void" in html and f"/admin/contracts/{ids['live']}/hide" not in html)

print("\nVOIDING FROM THE LIST:")
r = c.post(f"/admin/contracts/{ids['live']}/void",
           data={"next": "/admin/contracts/", "reason": "a test row"}, follow_redirects=False)
check("it comes back to the list, not the detail page",
      r.status_code == 302 and r.headers["Location"].endswith("/admin/contracts/"), r.headers.get("Location"))
check("the portal was told, with the reason", portal.voided == [("env-live", "a test row")], portal.voided)
with application.app_context():
    check("and the row reads voided", db.session.get(SignatureRequest, ids["live"]).status == "voided")
code, html = page()
check("now it offers Hide", f"/admin/contracts/{ids['live']}/hide" in html)

print("\nWHEN THE PORTAL HAS NO SUCH ENVELOPE:")
portal.raises = SignaDocError("Envelope not found", 404)
r = c.post(f"/admin/contracts/{ids['gone']}/void", data={"next": "/admin/contracts/"}, follow_redirects=True)
body = r.data.decode("utf-8", "replace")
with application.app_context():
    check("the row is settled here, so it can be tidied away",
          db.session.get(SignatureRequest, ids["gone"]).status == "voided")
check("and the page says nothing was sent", "no such envelope" in body, body[-500:])

print("\nWHEN THE PORTAL CANNOT BE REACHED:")
with application.app_context():
    stuck = row(envelope_id="env-stuck", title="SOW - Network Down", status="sent", kind="sow")
    db.session.commit()
    stuck_id = stuck.id
portal.raises = SignaDocError("Could not reach SignaDoc: timed out")  # no status at all
r = c.post(f"/admin/contracts/{stuck_id}/void", data={"next": "/admin/contracts/"}, follow_redirects=True)
with application.app_context():
    check("THE POINT: a portal that did not answer has agreed to nothing",
          db.session.get(SignatureRequest, stuck_id).status == "sent",
          db.session.get(SignatureRequest, stuck_id).status)

print("\nTHE TILES COUNT WHAT IS SHOWN:")
portal.raises = None
with application.app_context():
    for r_ in SignatureRequest.query.filter(SignatureRequest.status == "voided").all():
        r_.archived_at = datetime.now(timezone.utc)
    db.session.commit()
    shown = SignatureRequest.query.filter(SignatureRequest.archived_at.is_(None)).count()
    hidden = SignatureRequest.query.filter(SignatureRequest.archived_at.isnot(None)).count()
code, html = page()
import re  # noqa: E402
tiles = [int(n) for n in re.findall(r'text-2xl font-bold text-white mt-1">([\d,]+)<', html)]
check("the tiles add up to the rows on the screen, not to every row",
      sum(tiles) == shown and hidden > 0, (tiles, shown, hidden))

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
