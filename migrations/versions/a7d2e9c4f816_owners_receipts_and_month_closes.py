"""Owners, receipts from every mailbox, and the monthly close

Michael, 2026-11-03: "we're effectively building out our own bookkeeping
system". The pieces a bookkeeper would otherwise keep:

  - business_owners: who owns each company and how much. Built by Bean is
    Michael's alone (he said so on its bank application the same day);
    EntertainHQ has three members, typed in from its own paperwork.
  - contribution and draw: an owner's own money going in or coming out is
    neither income nor an expense. The CHASE rule written this morning as a
    transfer is Michael putting his own money in, so it says so now.
  - receipt_mailboxes, receipts: every inbox his receipts land in, read for
    receipts and matched to the charge each one proves.
  - month_closes: a month declared finished, with the figures it closed on.

Revision ID: a7d2e9c4f816
Revises: f6c1d3a8b520
Create Date: 2026-11-03
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "a7d2e9c4f816"
down_revision = "f6c1d3a8b520"
branch_labels = None
depends_on = None


def _has(table):
    return sa.inspect(op.get_bind()).has_table(table)


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    for table, column, kind in (("vendor_rules", "owner_name", sa.String(120)),
                                ("bank_transactions", "owner_name", sa.String(120)),
                                ("bank_connections", "balances_json", sa.Text())):
        if column not in _cols(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(column, kind, nullable=True))

    if not _has("business_owners"):
        op.create_table(
            "business_owners",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("share_percent", sa.Float(), nullable=True),
            sa.Column("note", sa.String(300), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_owners_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_owners"),
        )
        op.create_index("ix_business_owners_business_id", "business_owners", ["business_id"])

    if not _has("month_closes"):
        op.create_table(
            "month_closes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("month", sa.Date(), nullable=False),
            sa.Column("expenses_total", sa.Float(), nullable=False, server_default="0"),
            sa.Column("income_total", sa.Float(), nullable=False, server_default="0"),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.String(300), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_month_closes_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_month_closes"),
            sa.UniqueConstraint("business_id", "month", name="uq_month_closes_business_month"),
        )
        op.create_index("ix_month_closes_business_id", "month_closes", ["business_id"])

    if not _has("receipt_mailboxes"):
        op.create_table(
            "receipt_mailboxes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("address", sa.String(200), nullable=False),
            sa.Column("imap_host", sa.String(120), nullable=False),
            sa.Column("password", sa.Text(), nullable=True),
            sa.Column("read_from", sa.Date(), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("last_ok", sa.Boolean(), nullable=True),
            sa.Column("last_note", sa.String(300), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL",
                                    name="fk_receipt_mailboxes_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_receipt_mailboxes"),
            sa.UniqueConstraint("address", name="uq_receipt_mailboxes_address"),
        )

    if not _has("receipts"):
        op.create_table(
            "receipts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mailbox_id", sa.Integer(), nullable=False),
            sa.Column("message_key", sa.String(200), nullable=False),
            sa.Column("sender", sa.String(200), nullable=True),
            sa.Column("vendor", sa.String(120), nullable=True),
            sa.Column("subject", sa.String(300), nullable=True),
            sa.Column("received_on", sa.Date(), nullable=True),
            sa.Column("amount", sa.Float(), nullable=True),
            sa.Column("filename", sa.String(300), nullable=True),
            sa.Column("original_name", sa.String(300), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("expense_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["mailbox_id"], ["receipt_mailboxes.id"], ondelete="CASCADE",
                                    name="fk_receipts_mailbox_id"),
            sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="SET NULL",
                                    name="fk_receipts_expense_id"),
            sa.PrimaryKeyConstraint("id", name="pk_receipts"),
            sa.UniqueConstraint("mailbox_id", "message_key", name="uq_receipts_mailbox_message"),
        )
        op.create_index("ix_receipts_mailbox_id", "receipts", ["mailbox_id"])
        op.create_index("ix_receipts_received_on", "receipts", ["received_on"])
        op.create_index("ix_receipts_status", "receipts", ["status"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    home = bind.execute(sa.text(
        "SELECT id FROM businesses WHERE sales_source = 'board' AND parent_id IS NULL "
        "ORDER BY id LIMIT 1")).scalar()
    if home is not None and not bind.execute(sa.text(
            "SELECT 1 FROM business_owners WHERE business_id = :b"), {"b": home}).first():
        bind.execute(sa.text(
            "INSERT INTO business_owners (business_id, name, share_percent, note, created_at) "
            "VALUES (:b, 'Michael Bean', 100, 'Sole owner, as stated on the Mercury application "
            "2026-11-03', :t)"), {"b": home, "t": now})

    bind.execute(sa.text(
        "UPDATE vendor_rules SET disposition = 'contribution', owner_name = 'Michael Bean', "
        "vendor = 'Michael Bean (from his Chase account)' WHERE pattern = 'CHASE'"))
    bind.execute(sa.text(
        "UPDATE bank_transactions SET disposition = 'contribution', owner_name = 'Michael Bean' "
        "WHERE disposition IN ('transfer', 'income') AND UPPER(counterparty) LIKE '%CHASE%' "
        "AND amount > 0"))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE vendor_rules SET disposition = 'transfer' WHERE disposition IN ('contribution', 'draw')"))
    bind.execute(sa.text(
        "UPDATE bank_transactions SET disposition = 'transfer' "
        "WHERE disposition IN ('contribution', 'draw')"))
    for table in ("receipts", "receipt_mailboxes", "month_closes", "business_owners"):
        if _has(table):
            op.drop_table(table)
    for table, column in (("bank_connections", "balances_json"),
                          ("bank_transactions", "owner_name"), ("vendor_rules", "owner_name")):
        if column in _cols(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
