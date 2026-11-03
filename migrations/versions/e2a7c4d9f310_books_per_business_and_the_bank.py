"""Every expense in a business's books, and each business's bank read nightly

Michael, 2026-11-03: "I need my expense tracking automated to like the
highest degree ... broken out specifically by business as well, so that way
I'm not accidentally double counting."

  - expenses.business_id: whose books an expense is in. Every row that exists
    was booked as Built by Bean's (the board had one business's books), so
    they are filed there; the revalidation since April moves any that are
    not.
  - bank_connections, bank_transactions, vendor_rules: the bank feed
    (bank_feed.py). One line per money movement, the rule that says what a
    counterparty is, and the expense a settled line makes.
  - Three rules to start, the vendors whose own sync already books the money
    (Railway, Cloudflare, Claude), so their card charges are evidence and
    never a second expense.

Revision ID: e2a7c4d9f310
Revises: d8e3a6f1b204
Create Date: 2026-11-03
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "e2a7c4d9f310"
down_revision = "d8e3a6f1b204"
branch_labels = None
depends_on = None

FK = "fk_expenses_business_id"
SEEDS = (
    # pattern, vendor, provider name, display name to prefer
    ("RAILWAY", "Railway", "railway", "Railway"),
    ("CLOUDFLARE", "Cloudflare", "cloudflare", "Cloudflare"),
    ("ANTHROPIC", "Claude", "flat", "Claude"),
    ("CLAUDE AI", "Claude", "flat", "Claude"),
)


def _has(table):
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("expenses")}
    if "business_id" not in cols:
        with op.batch_alter_table("expenses") as batch:
            batch.add_column(sa.Column("business_id", sa.Integer(), nullable=True))
            batch.create_index("ix_expenses_business_id", ["business_id"])
    if FK not in {fk.get("name") for fk in sa.inspect(bind).get_foreign_keys("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.create_foreign_key(FK, "businesses", ["business_id"], ["id"], ondelete="SET NULL")

    home = bind.execute(sa.text(
        "SELECT id FROM businesses WHERE sales_source = 'board' AND parent_id IS NULL "
        "ORDER BY id LIMIT 1")).scalar()
    if home is None:
        home = bind.execute(sa.text(
            "SELECT id FROM businesses WHERE parent_id IS NULL ORDER BY id LIMIT 1")).scalar()
    if home is not None:
        done = bind.execute(sa.text(
            "UPDATE expenses SET business_id = :b WHERE business_id IS NULL"), {"b": home})
        print(f"expenses: {done.rowcount} filed under business {home}")

    if not _has("bank_connections"):
        op.create_table(
            "bank_connections",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("label", sa.String(120), nullable=True),
            sa.Column("token", sa.Text(), nullable=True),
            sa.Column("synced_from", sa.Date(), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("last_ok", sa.Boolean(), nullable=True),
            sa.Column("last_note", sa.String(300), nullable=True),
            sa.Column("accounts_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_bank_connections_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_bank_connections"),
        )
        op.create_index("ix_bank_connections_business_id", "bank_connections", ["business_id"])

    if not _has("vendor_rules"):
        op.create_table(
            "vendor_rules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pattern", sa.String(120), nullable=False),
            sa.Column("vendor", sa.String(120), nullable=True),
            sa.Column("disposition", sa.String(12), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.String(300), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL",
                                    name="fk_vendor_rules_business_id"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL",
                                    name="fk_vendor_rules_client_id"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL",
                                    name="fk_vendor_rules_project_id"),
            sa.ForeignKeyConstraint(["provider_id"], ["service_providers.id"], ondelete="SET NULL",
                                    name="fk_vendor_rules_provider_id"),
            sa.PrimaryKeyConstraint("id", name="pk_vendor_rules"),
            sa.UniqueConstraint("pattern", name="uq_vendor_rules_pattern"),
        )

    if not _has("bank_transactions"):
        op.create_table(
            "bank_transactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("external_id", sa.String(80), nullable=False),
            sa.Column("account_id", sa.String(80), nullable=True),
            sa.Column("account_name", sa.String(120), nullable=True),
            sa.Column("status", sa.String(12), nullable=True),
            sa.Column("kind", sa.String(40), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("counterparty", sa.String(200), nullable=True),
            sa.Column("description", sa.String(300), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("merchant_category", sa.String(80), nullable=True),
            sa.Column("bank_category", sa.String(60), nullable=True),
            sa.Column("card_id", sa.String(60), nullable=True),
            sa.Column("link", sa.String(300), nullable=True),
            sa.Column("disposition", sa.String(12), nullable=False),
            sa.Column("rule_id", sa.Integer(), nullable=True),
            sa.Column("expense_id", sa.Integer(), nullable=True),
            sa.Column("suggestion_json", sa.Text(), nullable=True),
            sa.Column("raw_json", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["connection_id"], ["bank_connections.id"], ondelete="CASCADE",
                                    name="fk_bank_transactions_connection_id"),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_bank_transactions_business_id"),
            sa.ForeignKeyConstraint(["rule_id"], ["vendor_rules.id"], ondelete="SET NULL",
                                    name="fk_bank_transactions_rule_id"),
            sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="SET NULL",
                                    name="fk_bank_transactions_expense_id"),
            sa.PrimaryKeyConstraint("id", name="pk_bank_transactions"),
            sa.UniqueConstraint("connection_id", "external_id",
                                name="uq_bank_transactions_connection_external"),
        )
        op.create_index("ix_bank_transactions_connection_id", "bank_transactions", ["connection_id"])
        op.create_index("ix_bank_transactions_business_id", "bank_transactions", ["business_id"])
        op.create_index("ix_bank_transactions_occurred_on", "bank_transactions", ["occurred_on"])
        op.create_index("ix_bank_transactions_disposition", "bank_transactions", ["disposition"])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for pattern, vendor, provider_name, display in SEEDS:
        if bind.execute(sa.text("SELECT 1 FROM vendor_rules WHERE pattern = :p"),
                        {"p": pattern}).first():
            continue
        provider = bind.execute(sa.text(
            "SELECT id FROM service_providers WHERE name = :n AND account_client_id IS NULL "
            "AND account_business_id IS NULL ORDER BY (display_name = :d) DESC, id LIMIT 1"),
            {"n": provider_name, "d": display}).scalar()
        bind.execute(sa.text(
            "INSERT INTO vendor_rules (pattern, vendor, disposition, business_id, category, "
            "provider_id, note, created_at) VALUES (:p, :v, :d, NULL, 'hosting', :pr, :n, :t)"),
            {"p": pattern, "v": vendor, "d": "covered" if provider else "expense",
             "pr": provider, "n": "Seeded: its own sync books this money", "t": now})


def downgrade():
    bind = op.get_bind()
    for table in ("bank_transactions", "vendor_rules", "bank_connections"):
        if _has(table):
            op.drop_table(table)
    if FK in {fk.get("name") for fk in sa.inspect(bind).get_foreign_keys("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.drop_constraint(FK, type_="foreignkey")
    if "business_id" in {c["name"] for c in sa.inspect(bind).get_columns("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.drop_index("ix_expenses_business_id")
            batch.drop_column("business_id")
