"""The board's other secrets are sealed in the database (issue #15).

The Mercury token, the mailbox app passwords, a company's Stripe key, the hub
signing secrets and the support desk keys are SealedText: sealed in the
column, plain in Python. A value saved before reads as it is, the migration
seals what is there and its downgrade opens it, a value another SECRET_KEY
sealed reads as "" without breaking the page, and "is one set" still works.

    python tools/test_sealed_secrets.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-sealed-secrets-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ["SECRET_KEY"] = "test-secret-for-sealing"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from models import (db, Client, Business, BankConnection, ReceiptMailbox,  # noqa: E402
                    SupportApp)

app = create_app()
FAIL = []
PLAIN = {
    ("clients", "ingest_secret"): "client-hub-secret-123",
    ("businesses", "hub_secret"): "business-hub-secret-456",
    ("businesses", "stripe_key"): "rk_live_restricted_789",
    ("bank_connections", "token"): "secret-token:mercury:abc",
    ("receipt_mailboxes", "password"): "abcd efgh ijkl mnop",
    ("support_apps", "desk_key"): "desk-bearer-key-xyz",
}


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}   {name}" + ("" if cond else f"  [{str(detail)[:300]}]"))
    if not cond:
        FAIL.append(name)


def raw(table, col):
    with db.engine.connect() as c:
        return c.execute(text(f"SELECT {col} FROM {table} ORDER BY id LIMIT 1")).scalar()


def migrate(direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = ROOT / "migrations" / "versions" / "d5a8e3c1f927_seal_the_other_secrets.py"
    spec = importlib.util.spec_from_file_location("m_seal_rest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, direction)()


with app.app_context():
    db.create_all()
    client = Client(name="Kenali Kendrick", email="k@example.test", ingest_secret=PLAIN[("clients", "ingest_secret")])
    biz = Business(name="EntertainHQ LLC", slug="entertainhq", sales_source="manual",
                   hub_secret=PLAIN[("businesses", "hub_secret")], stripe_key=PLAIN[("businesses", "stripe_key")])
    db.session.add_all([client, biz])
    db.session.flush()
    db.session.add_all([
        BankConnection(business_id=biz.id, token=PLAIN[("bank_connections", "token")]),
        ReceiptMailbox(address="m@example.test", business_id=biz.id, password=PLAIN[("receipt_mailboxes", "password")]),
        SupportApp(origin="entertainhq", name="EntertainHQ", kind="desk", desk_key=PLAIN[("support_apps", "desk_key")]),
    ])
    db.session.commit()

    print("1. saved sealed, read plain")
    for (table, col), value in PLAIN.items():
        stored = raw(table, col)
        check(f"{table}.{col} is sealed in the column", stored.startswith("enc:v1:") and value not in stored, stored)
    db.session.expire_all()
    check("and plain when the board reads it",
          db.session.get(Client, client.id).ingest_secret == PLAIN[("clients", "ingest_secret")]
          and db.session.get(Business, biz.id).stripe_key == PLAIN[("businesses", "stripe_key")]
          and BankConnection.query.one().token == PLAIN[("bank_connections", "token")]
          and ReceiptMailbox.query.one().password == PLAIN[("receipt_mailboxes", "password")]
          and SupportApp.query.one().desk_key == PLAIN[("support_apps", "desk_key")])
    check("asking whether one is set still works (stripe_books' filter)",
          Business.query.filter(Business.stripe_key.isnot(None), Business.stripe_key != "").count() == 1)
    check("an empty one stays empty", raw("clients", "name") and Client(name="x", email="x@example.test").ingest_secret in ("", None))

    print("2. the migration: what was saved plain is sealed, and the way back")
    with db.engine.begin() as c:
        for (table, col), value in PLAIN.items():
            c.execute(text(f"UPDATE {table} SET {col} = :v"), {"v": value})
    check("(set back to plain, as production holds them)", raw("bank_connections", "token") == PLAIN[("bank_connections", "token")])
    db.session.expire_all()
    check("a plain value still reads", BankConnection.query.one().token == PLAIN[("bank_connections", "token")])
    migrate("upgrade")
    check("upgrade seals every one", all(raw(t, c).startswith("enc:v1:") for t, c in PLAIN), [raw(t, c)[:12] for t, c in PLAIN])
    db.session.expire_all()
    check("and they read plain", ReceiptMailbox.query.one().password == PLAIN[("receipt_mailboxes", "password")])
    migrate("downgrade")
    check("downgrade opens every one", all(raw(t, c) == v for (t, c), v in PLAIN.items()))
    migrate("upgrade")
    check("and upgrade again", all(raw(t, c).startswith("enc:v1:") for t, c in PLAIN))

    print("3. another SECRET_KEY")
    app.config["SECRET_KEY"] = "a-different-secret"
    db.session.expire_all()
    try:
        c = db.session.get(Client, client.id)
        check("a client still loads, its secret reads as not set", c is not None and c.ingest_secret == "")
    except Exception as err:  # noqa: BLE001
        check("a client still loads, its secret reads as not set", False, err)
    app.config["SECRET_KEY"] = "test-secret-for-sealing"

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
