"""Seal the board's other secrets

Issue #15 (2026-11-05), the half of #14 that was not vendor keys: the Mercury
token, the receipt mailboxes' app passwords, a company's restricted Stripe
key, the clients' and businesses' hub signing secrets and each support desk's
key were plain text. Their columns are now `SealedText` (secret_box), which
seals on save and opens on read; this seals the values already there and
widens the two VARCHAR(120) columns, because a sealed value is longer than
120 characters. Downgrade opens them and narrows the columns back.

With no SECRET_KEY it changes no values and says so; a plain value still
reads, and the next save seals it.

Revision ID: d5a8e3c1f927
Revises: c7e2a9f4b136
Create Date: 2026-11-05
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "d5a8e3c1f927"
down_revision = "c7e2a9f4b136"
branch_labels = None
depends_on = None

COLUMNS = (("bank_connections", "token"), ("receipt_mailboxes", "password"),
           ("businesses", "stripe_key"), ("businesses", "hub_secret"),
           ("clients", "ingest_secret"), ("support_apps", "desk_key"))
NARROW = (("businesses", "hub_secret"), ("clients", "ingest_secret"))


def _secret():
    try:
        from flask import current_app
        if current_app.config.get("SECRET_KEY"):
            return str(current_app.config["SECRET_KEY"])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("SECRET_KEY", "")


def _present(bind):
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    return [(t, c) for t, c in COLUMNS
            if t in tables and c in {x["name"] for x in insp.get_columns(t)}]


def _rewrite(bind, change):
    secret = _secret()
    if not secret:
        print("secrets: no SECRET_KEY here, no values changed")
        return
    for table, col in _present(bind):
        done = 0
        for rid, value in bind.execute(sa.text(
                f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''")).all():
            new = change(value, secret)
            if new != value:
                bind.execute(sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :id"), {"v": new, "id": rid})
                done += 1
        print(f"secrets: {table}.{col}: {done} rewritten")


def upgrade():
    import secret_box
    bind = op.get_bind()
    present = _present(bind)
    for table, col in NARROW:
        if (table, col) in present:
            with op.batch_alter_table(table) as batch:
                batch.alter_column(col, type_=sa.Text(), existing_type=sa.String(120),
                                   existing_nullable=True)
    _rewrite(bind, secret_box.seal)


def downgrade():
    import secret_box
    bind = op.get_bind()
    _rewrite(bind, secret_box.unseal)
    present = _present(bind)
    for table, col in NARROW:
        if (table, col) in present:
            with op.batch_alter_table(table) as batch:
                batch.alter_column(col, type_=sa.String(120), existing_type=sa.Text(),
                                   existing_nullable=True)
