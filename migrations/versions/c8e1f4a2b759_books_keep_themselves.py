"""The books keep themselves: statement balances, card alerts, books flags

A statement source keeps the balance its upload ended on and the balance
before its oldest row, and the last four digits its bank's alerts name it by
(models.BankConnection). Chase's per-transaction alert emails become
`card_alerts`, and what the nightly books run finds wrong is `books_flags`,
one Needs attention row each (books_upkeep.py).

Every create is guarded on the table not existing, because create_all runs on
boot and wins the race; every column on its not existing, for the same reason.

Revision ID: c8e1f4a2b759
Revises: b4e9c2a7d153
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "c8e1f4a2b759"
down_revision = "b4e9c2a7d153"
branch_labels = None
depends_on = None

COLUMNS = [
    ("balance", sa.Float()),
    ("balance_on", sa.Date()),
    ("opening_balance", sa.Float()),
    ("opening_on", sa.Date()),
    ("last_four", sa.String(8)),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    have = {c["name"] for c in inspector.get_columns("bank_connections")}
    with op.batch_alter_table("bank_connections") as batch:
        for name, kind in COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, kind, nullable=True))
    tables = set(inspector.get_table_names())
    if "card_alerts" not in tables:
        op.create_table(
            "card_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("mailbox_id", sa.Integer(), sa.ForeignKey(
                "receipt_mailboxes.id", ondelete="CASCADE", name="fk_card_alerts_mailbox_id"),
                nullable=False),
            sa.Column("message_key", sa.String(200), nullable=False),
            sa.Column("last_four", sa.String(8), nullable=True),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("merchant", sa.String(200), nullable=True),
            sa.Column("subject", sa.String(300), nullable=True),
            sa.Column("line_id", sa.Integer(), sa.ForeignKey(
                "bank_transactions.id", ondelete="SET NULL", name="fk_card_alerts_line_id"),
                nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("mailbox_id", "message_key", name="uq_card_alerts_mailbox_message"),
        )
        op.create_index("ix_card_alerts_mailbox_id", "card_alerts", ["mailbox_id"])
        op.create_index("ix_card_alerts_line_id", "card_alerts", ["line_id"])
    if "books_flags" not in tables:
        op.create_table(
            "books_flags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("key", sa.String(80), nullable=False, server_default=""),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_books_flags_business_id"),
                nullable=True),
            sa.Column("title", sa.String(200), nullable=False, server_default=""),
            sa.Column("detail", sa.String(300), nullable=True),
            sa.Column("link", sa.String(300), nullable=True),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("items_json", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("kind", "key", name="uq_books_flags_kind_key"),
        )
        op.create_index("ix_books_flags_business_id", "books_flags", ["business_id"])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "books_flags" in tables:
        op.drop_table("books_flags")
    if "card_alerts" in tables:
        op.drop_table("card_alerts")
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bank_connections")}
    with op.batch_alter_table("bank_connections") as batch:
        for name, _ in reversed(COLUMNS):
            if name in have:
                batch.drop_column(name)
