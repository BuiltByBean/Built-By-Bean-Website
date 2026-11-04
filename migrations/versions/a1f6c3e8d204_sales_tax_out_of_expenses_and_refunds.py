"""Sales tax paid to the state is not an expense, and a refund is carried

expenses.sales_tax_remitted and expenses.sales_tax_filing_id: the part of a
Comptroller charge that was the state's money. Income already leaves sales tax
out, so counting the payment as an expense took it off the profit twice:
$996.60 of the $1,193.22 paid on 2026-11-02. expenses.amount becomes what the
payment really cost (penalties, interest and the card fee), and every total in
the app is right without changing how it reads the column.

invoices.amount_refunded: Stripe leaves a refunded invoice "paid" with
amount_paid untouched. The importer fills it from Stripe on its next run.

Only the company whose income is net of sales tax is touched: a company on its
own Stripe or app counts sales gross, and there the payment is the deduction
that takes the tax back out. The rule matched here is the one in
books_service.settle_sales_tax, written out because a migration must not change
what it does when the code does.

Revision ID: a1f6c3e8d204
Revises: d1a4f7c2e938
Create Date: 2026-11-03
"""
import re
from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op

revision = "a1f6c3e8d204"
down_revision = "d1a4f7c2e938"
branch_labels = None
depends_on = None

FK = "fk_expenses_sales_tax_filing_id"
INDEX = "ix_expenses_sales_tax_filing_id"
STATE_TAX_PAYMENT = re.compile(r"comptroller|texas tax|state tax|webfile", re.I)


def _day(value):
    return date.fromisoformat(str(value)[:10])


def _settle_what_is_there(bind):
    filings = bind.execute(sa.text(
        "SELECT f.id, f.business_id, f.tax_due, f.discount, f.amount_paid, f.filed_at "
        "FROM sales_tax_filings f WHERE f.filed_at IS NOT NULL ORDER BY f.id")).mappings().all()
    for filing in filings:
        business = bind.execute(sa.text("SELECT id, parent_id, sales_source FROM businesses WHERE id = :b"),
                                {"b": filing["business_id"]}).mappings().first()
        if business is None:
            continue
        root_id = business["parent_id"] or business["id"]
        root = bind.execute(sa.text("SELECT sales_source FROM businesses WHERE id = :b"),
                            {"b": root_id}).mappings().first()
        if root is None or root["sales_source"] != "board":
            continue
        paid = round(filing["amount_paid"] or 0.0, 2)
        if paid <= 0:
            continue
        # Already settled, so a second charge in range is never taken for it.
        if bind.execute(sa.text("SELECT 1 FROM expenses WHERE sales_tax_filing_id = :f"),
                        {"f": filing["id"]}).first():
            continue
        family = [root_id] + [r[0] for r in bind.execute(
            sa.text("SELECT id FROM businesses WHERE parent_id = :b"), {"b": root_id}).fetchall()]
        filed = _day(filing["filed_at"])
        found = []
        for member in family:
            for row in bind.execute(sa.text(
                    "SELECT id, amount, description, date FROM expenses WHERE business_id = :b "
                    "AND sales_tax_filing_id IS NULL AND time_entry_id IS NULL"), {"b": member}).mappings():
                day = _day(row["date"])
                charged = round(row["amount"] or 0.0, 2)
                if (filed - timedelta(days=3) <= day <= filed + timedelta(days=10)
                        and STATE_TAX_PAYMENT.search(row["description"] or "")
                        and paid <= charged <= paid * 1.03 + 0.01):
                    found.append((round(charged - paid, 2), row["id"], charged))
        if not found:
            print(f"sales tax: filing {filing['id']} has no charge on the books yet")
            continue
        _, expense_id, charged = min(found)
        tax = min(round(max(0.0, (filing["tax_due"] or 0.0) - (filing["discount"] or 0.0)), 2), charged)
        bind.execute(sa.text(
            "UPDATE expenses SET amount = :amount, sales_tax_remitted = :tax, sales_tax_filing_id = :f "
            "WHERE id = :e"),
            {"amount": round(charged - tax, 2), "tax": tax, "f": filing["id"], "e": expense_id})
        print(f"sales tax: expense {expense_id} of {charged:.2f} carried {tax:.2f} to the state, "
              f"costs {charged - tax:.2f}")


def upgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("expenses")}
    if "sales_tax_remitted" not in cols:
        with op.batch_alter_table("expenses") as batch:
            batch.add_column(sa.Column("sales_tax_remitted", sa.Float(), nullable=False, server_default="0"))
    if "sales_tax_filing_id" not in cols:
        with op.batch_alter_table("expenses") as batch:
            batch.add_column(sa.Column("sales_tax_filing_id", sa.Integer(), nullable=True))
    insp = sa.inspect(bind)
    if FK not in {fk.get("name") for fk in insp.get_foreign_keys("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.create_foreign_key(FK, "sales_tax_filings", ["sales_tax_filing_id"], ["id"],
                                     ondelete="SET NULL")
    if INDEX not in {i["name"] for i in sa.inspect(bind).get_indexes("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.create_index(INDEX, ["sales_tax_filing_id"])
    if "amount_refunded" not in {c["name"] for c in sa.inspect(bind).get_columns("invoices")}:
        with op.batch_alter_table("invoices") as batch:
            batch.add_column(sa.Column("amount_refunded", sa.Float(), nullable=False, server_default="0"))
    _settle_what_is_there(bind)


def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("expenses")}
    if "sales_tax_remitted" in cols:
        # Each charge goes back to what it was: dropping the column without
        # this would lose the tax out of the books for good.
        for row in bind.execute(sa.text("SELECT id, amount, sales_tax_remitted FROM expenses "
                                        "WHERE sales_tax_remitted <> 0")).mappings().all():
            bind.execute(sa.text("UPDATE expenses SET amount = :a WHERE id = :e"),
                         {"a": round((row["amount"] or 0.0) + row["sales_tax_remitted"], 2), "e": row["id"]})
    if "amount_refunded" in {c["name"] for c in sa.inspect(bind).get_columns("invoices")}:
        with op.batch_alter_table("invoices") as batch:
            batch.drop_column("amount_refunded")
    if INDEX in {i["name"] for i in sa.inspect(bind).get_indexes("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.drop_index(INDEX)
    if FK in {fk.get("name") for fk in sa.inspect(bind).get_foreign_keys("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.drop_constraint(FK, type_="foreignkey")
    with op.batch_alter_table("expenses") as batch:
        if "sales_tax_filing_id" in cols:
            batch.drop_column("sales_tax_filing_id")
        if "sales_tax_remitted" in cols:
            batch.drop_column("sales_tax_remitted")
