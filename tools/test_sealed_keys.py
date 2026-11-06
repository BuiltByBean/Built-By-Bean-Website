"""Vendor keys are sealed in the database (issue #14).

Saving an account seals its secrets, a sync opens them, a key saved before
still reads, the migration seals what is there and its downgrade opens it,
and a key sealed under another SECRET_KEY stops the sync in words.

    python tools/test_sealed_keys.py
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-sealed-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ["SECRET_KEY"] = "test-secret-for-sealing"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, User, ServiceProvider  # noqa: E402
import secret_box  # noqa: E402
import service_costs_service  # noqa: E402

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}   {name}" + ("" if cond else f"  [{str(detail)[:300]}]"))
    if not cond:
        FAIL.append(name)


def migrate(direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = ROOT / "migrations" / "versions" / "c7e2a9f4b136_seal_vendor_keys.py"
    spec = importlib.util.spec_from_file_location("m_seal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, direction)()


seen = []
service_costs_service.requests.get = lambda url, params=None, auth=None, timeout=None, **kw: (
    seen.append(auth) or type("A", (), {"status_code": 200, "raise_for_status": lambda s: None,
                                        "json": lambda s: {"usage_records": [], "friendly_name": "x"}})())

with app.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    old = ServiceProvider(name="twilio", display_name="Twilio", vendor="Twilio",
                          credentials_json=json.dumps({"account_sid": "ACold", "auth_token": "PLAINTOKEN"}))
    db.session.add_all([boss, old])
    db.session.commit()
    BOSS, OLD = boss.id, old.id

print("1. the helper")
sealed = secret_box.seal("abc", "k1")
check("a sealed value is not the value", sealed.startswith("enc:v1:") and "abc" not in sealed)
check("and opens again", secret_box.unseal(sealed, "k1") == "abc")
check("sealing twice does not wrap it again", secret_box.seal(sealed, "k1") == sealed)
check("a plain value reads as it is", secret_box.unseal("plain", "k1") == "plain")
try:
    secret_box.unseal(sealed, "another-key")
    check("another SECRET_KEY cannot open it", False)
except secret_box.SealError as err:
    check("another SECRET_KEY cannot open it, and says what to do", "Paste the key in again" in str(err))
creds = secret_box.seal_creds({"account_sid": "AC1", "workspace_id": "w", "api_key_secret": "s", "api_token": "t"}, "k1")
check("only the secret fields are sealed", creds["account_sid"] == "AC1" and creds["workspace_id"] == "w"
      and secret_box.is_sealed(creds["api_key_secret"]) and secret_box.is_sealed(creds["api_token"]))

print("2. a key saved before still syncs")
with app.app_context():
    count, error = service_costs_service.sync_provider(OLD)
    check("the plain token is used", error is None and seen[-1] == ("ACold", "PLAINTOKEN"), (error, seen))

print("3. the migration seals what is there, the downgrade opens it")
with app.app_context():
    migrate("upgrade")
    db.session.expire_all()
    raw = db.session.get(ServiceProvider, OLD).credentials_json
    check("no secret left in the column", "PLAINTOKEN" not in raw and "enc:v1:" in raw, raw)
    check("the id is still readable", json.loads(raw)["account_sid"] == "ACold")
    count, error = service_costs_service.sync_provider(OLD)
    check("the sync opens it", error is None and seen[-1] == ("ACold", "PLAINTOKEN"), (error, seen[-1:]))
    migrate("downgrade")
    db.session.expire_all()
    check("downgrade puts it back plain", json.loads(db.session.get(ServiceProvider, OLD).credentials_json)
          == {"account_sid": "ACold", "auth_token": "PLAINTOKEN"})
    migrate("upgrade")

print("4. saving from the page seals")
c = app.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(BOSS)
    s["_fresh"] = True
c.post("/admin/service-costs/providers/new", data={
    "name": "twilio", "twilio_account_sid": "ACnew", "twilio_api_key_sid": "SKnew",
    "twilio_api_key_secret": "NEWSECRET", "account_client_id": ""})
with app.app_context():
    new = ServiceProvider.query.filter(ServiceProvider.id != OLD, ServiceProvider.name == "twilio").one()
    check("the new secret is sealed in the column", "NEWSECRET" not in new.credentials_json
          and "enc:v1:" in new.credentials_json, new.credentials_json)
    check("and the sync used it", seen[-1] == ("SKnew", "NEWSECRET"), seen[-1:])
    NEW = new.id
page = c.get(f"/admin/service-costs/providers/{NEW}/edit").get_data(as_text=True)
check("the edit page shows neither the secret nor its sealed form",
      "NEWSECRET" not in page and "enc:v1:" not in page and "Saved. Leave blank to keep it" in page)
c.post(f"/admin/service-costs/providers/{NEW}/edit", data={
    "twilio_account_sid": "ACnew", "twilio_api_key_sid": "SKnew", "twilio_api_key_secret": "",
    "is_active": "on", "account_client_id": ""})
with app.app_context():
    p = db.session.get(ServiceProvider, NEW)
    check("a blank edit keeps the sealed secret, sealed once",
          secret_box.loads(p.credentials_json)["api_key_secret"] == "NEWSECRET"
          and "enc:v1:enc:v1:" not in p.credentials_json)

print("5. a changed SECRET_KEY is said, not swallowed")
with app.app_context():
    app.config["SECRET_KEY"] = "a-different-secret"
    count, error = service_costs_service.sync_provider(NEW)
    check("the sync records why", error and "Paste the key in again" in error, error)
    app.config["SECRET_KEY"] = "test-secret-for-sealing"

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
