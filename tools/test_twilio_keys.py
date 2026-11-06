"""Twilio accounts connect with their own API keys, billed to whoever pays.

Michael, 2026-11-05: connect every Twilio account (Kenali's for J&D, his own
for EntertainHQ, Cason's). The sync logged in with the account's main auth
token, the edit form wrote that token back into the page as an input's value,
and Billed to offered only clients, so his EntertainHQ account could not say
EntertainHQ LLC paid for it.

    python tools/test_twilio_keys.py
"""
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-twilio-keys-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, User, Client, Business, ServiceProvider  # noqa: E402
import service_costs_service  # noqa: E402
import secret_box  # noqa: E402

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False
FAIL = []
CALLS = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}   {name}" + ("" if cond else f"  [{str(detail)[:300]}]"))
    if not cond:
        FAIL.append(name)


class Answer:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise service_costs_service.requests.HTTPError(f"{self.status_code} Client Error: Unauthorized for url: x")


def fake_get(url, params=None, auth=None, timeout=None, **kw):
    CALLS.append((url, auth))
    if auth != ("SKgood", "goodsecret"):
        return Answer(401, {})
    if url.endswith("/Usage/Records/Monthly.json"):
        return Answer(200, {"usage_records": [
            {"category": "sms-outbound", "price": "4.20", "start_date": "2026-11-01", "end_date": "2026-11-05"}]})
    return Answer(200, {"friendly_name": "EntertainHQ texting"})


service_costs_service.requests.get = fake_get

with app.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", slug="builtbybean", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", slug="entertainhq", sales_source="manual")
    kenali = Client(name="Kenali Kendrick", email="k@example.test")
    db.session.add_all([boss, bbb, ehq, kenali])
    db.session.flush()
    tw = ServiceProvider(name="twilio", display_name="Twilio", vendor="Twilio", account_client_id=kenali.id,
                         credentials_json=json.dumps({"account_sid": "ACjd", "auth_token": "OLDTOKEN"}))
    # What the bank found: Built by Bean's own Twilio charges, no account yet.
    found = ServiceProvider(name="bank", display_name="Twilio", vendor="Twilio", credentials_json="{}",
                            discovered_from="bank: TWILIO")
    db.session.add_all([tw, found])
    db.session.commit()
    TW, EHQ, BOSS = tw.id, ehq.id, boss.id

c = app.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(BOSS)
    s["_fresh"] = True

print("1. a saved secret never comes back to the page")
page = c.get(f"/admin/service-costs/providers/{TW}/edit").get_data(as_text=True)
check("the auth token is not in the page", "OLDTOKEN" not in page)
check("the box says one is saved", "Saved. Leave blank to keep it" in page)
check("the form asks for an API key", 'name="twilio_api_key_sid"' in page and 'name="twilio_api_key_secret"' in page)
check("Billed to offers the other company, never the board's own twice",
      "EntertainHQ LLC (its own card)" in page and "Built by Bean LLC (its own card)" not in page)

print("2. a new key, billed to EntertainHQ")
r = c.post(f"/admin/service-costs/providers/{TW}/edit", data={
    "twilio_account_sid": "ACehq", "twilio_api_key_sid": "SKgood", "twilio_api_key_secret": "goodsecret",
    "twilio_auth_token": "", "is_active": "on", "account_client_id": f"b:{EHQ}", "vendor": "Twilio"},
    follow_redirects=True)
flash = r.get_data(as_text=True)
with app.app_context():
    p = db.session.get(ServiceProvider, TW)
    creds = secret_box.loads(p.credentials_json)
    check("the key is saved and the old token kept", creds["api_key_sid"] == "SKgood"
          and creds["api_key_secret"] == "goodsecret" and creds["auth_token"] == "OLDTOKEN", creds)
    check("billed to EntertainHQ LLC, no client", p.account_business_id == EHQ and p.account_client_id is None,
          (p.account_business_id, p.account_client_id))
    check("the save synced it with the API key, not the token",
          CALLS and all(a == ("SKgood", "goodsecret") for _, a in CALLS) and not p.sync_error, (CALLS, p.sync_error))
    check("and named the account Twilio calls it", p.account_label == "EntertainHQ texting")
check("the press says Twilio answered", "Twilio answered (EntertainHQ texting)" in flash)

print("3. leaving the secrets blank keeps them")
c.post(f"/admin/service-costs/providers/{TW}/edit", data={
    "twilio_account_sid": "ACehq", "twilio_api_key_sid": "SKgood", "twilio_api_key_secret": "",
    "twilio_auth_token": "", "is_active": "on", "account_client_id": f"b:{EHQ}"})
with app.app_context():
    creds = secret_box.loads(db.session.get(ServiceProvider, TW).credentials_json)
    check("both secrets are still there", creds["api_key_secret"] == "goodsecret" and creds["auth_token"] == "OLDTOKEN")

print("4. a wrong key says so in words")
r = c.post(f"/admin/service-costs/providers/{TW}/edit", data={
    "twilio_account_sid": "ACehq", "twilio_api_key_sid": "SKbad", "twilio_api_key_secret": "nope",
    "is_active": "on", "account_client_id": f"b:{EHQ}"}, follow_redirects=True)
check("the press says the key was turned down", "Twilio turned the key down" in r.get_data(as_text=True))

print("5. a new account is read on the press")
CALLS.clear()
r = c.post("/admin/service-costs/providers/new", data={
    "name": "twilio", "twilio_account_sid": "ACkuper", "twilio_api_key_sid": "SKgood",
    "twilio_api_key_secret": "goodsecret", "account_client_id": ""}, follow_redirects=True)
with app.app_context():
    new = ServiceProvider.query.filter_by(name="twilio").order_by(ServiceProvider.id.desc()).first()
    check("it is added and synced", new.id != TW and not new.sync_error and CALLS, (new.id, new.sync_error))
    check("its vendor is Twilio, under the one tile", new.vendor_name == "Twilio")
    check("and the bank's placeholder for Built by Bean gave way to it",
          ServiceProvider.query.filter_by(name="bank").count() == 0)

print("6. a link opens Add account filled in, all but the key")
sid = "AC" + "0123456789abcdef" * 2
page = c.get(f"/admin/service-costs/providers/new?type=twilio&billed_to=b:{EHQ}&sid={sid}&vendor=Twilio").get_data(as_text=True)
check("Twilio is chosen", "providerType: 'twilio'" in page)
check("the account id is in", f'value="{sid}"' in page)
check("and who pays", f"b:{EHQ}" in page)
bad = c.get("/admin/service-costs/providers/new?type=evil'x&sid=nope&billed_to=b:999").get_data(as_text=True)
check("anything else on the link is ignored", "evil" not in bad and 'value="nope"' not in bad and "providerType: ''" in bad)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
