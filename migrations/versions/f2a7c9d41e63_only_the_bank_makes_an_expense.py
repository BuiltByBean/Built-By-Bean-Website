"""Only the bank line makes an expense; a session's log_expense is a tag

docs/finances_plan.md items 5, 6 and 8 (Michael, 2026-11-04).

- `expenses.bank_line_id` and `expenses.cost_entry_id`: an expense is part of
  a bank line, and a vendor's charge books one row per share of its report.
- `expense_tags`: what a session knows about a charge before the bank does.
- The rows the vendor syncs wrote are carried over by finance_carryover.apply,
  which raises (and so stops the deploy) if any company's yearly total would
  move for a reason that is not a double count or one of Michael's decisions.
  What it did is printed to the deploy log.
- Recurring expenses retire: every parent ends, every past row stays.

Every create is guarded on the table or column not existing, because
create_all runs on boot and wins the race.

Revision ID: f2a7c9d41e63
Revises: b8e4d2a6c013
Create Date: 2026-11-04
"""
import os
import sys

import sqlalchemy as sa
from alembic import op

revision = "f2a7c9d41e63"
down_revision = "b8e4d2a6c013"
branch_labels = None
depends_on = None

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _indexes(inspector, table):
    return {i["name"] for i in inspector.get_indexes(table)}


def upgrade():
    import finance_carryover

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    have = {c["name"] for c in inspector.get_columns("expenses")}
    with op.batch_alter_table("expenses") as batch:
        if "bank_line_id" not in have:
            batch.add_column(sa.Column("bank_line_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_expenses_bank_line_id", "bank_transactions",
                                     ["bank_line_id"], ["id"], ondelete="SET NULL")
        if "cost_entry_id" not in have:
            batch.add_column(sa.Column("cost_entry_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_expenses_cost_entry_id", "service_cost_entries",
                                     ["cost_entry_id"], ["id"], ondelete="SET NULL")
    inspector = sa.inspect(bind)
    names = _indexes(inspector, "expenses")
    if "ix_expenses_bank_line_id" not in names:
        op.create_index("ix_expenses_bank_line_id", "expenses", ["bank_line_id"])
    if "ix_expenses_cost_entry_id" not in names:
        op.create_index("ix_expenses_cost_entry_id", "expenses", ["cost_entry_id"])

    if "expense_tags" not in set(inspector.get_table_names()):
        op.create_table(
            "expense_tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("vendor", sa.String(200), nullable=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="SET NULL", name="fk_expense_tags_business_id"), nullable=True),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey(
                "clients.id", ondelete="SET NULL", name="fk_expense_tags_client_id"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey(
                "projects.id", ondelete="SET NULL", name="fk_expense_tags_project_id"), nullable=True),
            sa.Column("paid_by", sa.String(120), nullable=True),
            sa.Column("source", sa.String(120), nullable=True),
            sa.Column("line_id", sa.Integer(), sa.ForeignKey(
                "bank_transactions.id", ondelete="SET NULL", name="fk_expense_tags_line_id"), nullable=True),
            sa.Column("taken_at", sa.DateTime(), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    inspector = sa.inspect(bind)
    names = _indexes(inspector, "expense_tags")
    for col in ("occurred_on", "business_id", "client_id", "project_id", "line_id"):
        if f"ix_expense_tags_{col}" not in names:
            op.create_index(f"ix_expense_tags_{col}", "expense_tags", [col])

    report = finance_carryover.apply(bind)
    for line in finance_carryover.summary(report):
        print(f"  finances item 5: {line}", flush=True)

    # Recurring expenses retire (item 6). Past rows stay as they are.
    bind.execute(sa.text("UPDATE expenses SET is_recurring = :f, next_due_date = NULL "
                         "WHERE is_recurring = :t"), {"f": False, "t": True})


def downgrade():
    import finance_carryover

    bind = op.get_bind()
    finance_carryover.undo(bind)
    inspector = sa.inspect(bind)
    if "expense_tags" in set(inspector.get_table_names()):
        op.drop_table("expense_tags")
    names = _indexes(inspector, "expenses")
    for name in ("ix_expenses_bank_line_id", "ix_expenses_cost_entry_id"):
        if name in names:
            op.drop_index(name, table_name="expenses")
    have = {c["name"] for c in inspector.get_columns("expenses")}
    fks = {f["name"] for f in inspector.get_foreign_keys("expenses")}
    with op.batch_alter_table("expenses") as batch:
        for fk, col in (("fk_expenses_bank_line_id", "bank_line_id"), ("fk_expenses_cost_entry_id", "cost_entry_id")):
            if fk in fks:
                batch.drop_constraint(fk, type_="foreignkey")
            if col in have:
                batch.drop_column(col)
