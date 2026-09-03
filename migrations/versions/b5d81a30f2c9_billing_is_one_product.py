"""Invoicing and card payments become one product

Sold apart, they were $1,000 each. A client asking to bill customers and get
paid hears one thing, and two thousand-dollar line items for it reads as being
charged twice for the same outcome - which is the objection this catalogue
exists to avoid.

One product at $2,500. More than the $2,000 the two used to make together,
deliberately: it is two builds rather than one, money handling carries a
liability texting does not, and the offer is "the payment provider of your
choice" - Stripe is known cold, anything else is a fresh integration that
cannot be absorbed at the old price.

Revision ID: b5d81a30f2c9
Revises: a2e64b17c308
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "b5d81a30f2c9"
down_revision = "a2e64b17c308"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Refuse rather than cascade. The foreign key from product_sales deletes
    # sales with their product, so merging two catalogue rows must never be
    # the thing that quietly erases a record of something somebody bought.
    sold = bind.execute(sa.text(
        "SELECT COUNT(*) FROM product_sales s JOIN products p ON p.id = s.product_id "
        "WHERE p.slug IN ('invoicing', 'payments')"
    )).scalar()
    if sold:
        raise RuntimeError(
            f"{sold} sale(s) reference 'invoicing' or 'payments'. Move them to "
            "'billing' by hand before merging, or they will be deleted with the "
            "products they point at."
        )

    bind.execute(sa.text(
        "DELETE FROM products WHERE slug IN ('invoicing', 'payments')"))

    # On a database whose products table came from db.create_all() at today's
    # model shape, includes_hosting already exists as NOT NULL with only a
    # Python-side default, so an INSERT that omits it fails. When this
    # migration first ran in production the column did not exist yet - so it
    # is named only where it is present. This board hit the omission on
    # 2026-09-03, on a stale local database walking the chain fresh.
    cols = {c["name"] for c in sa.inspect(bind).get_columns("products")}
    extra_col = ", includes_hosting" if "includes_hosting" in cols else ""
    extra_val = ", true" if "includes_hosting" in cols else ""

    already = bind.execute(sa.text(
        "SELECT COUNT(*) FROM products WHERE slug = 'billing'")).scalar()
    if not already:
        # Bound parameters rather than inline literals: the original inline
        # SQL leaned on newline string-literal concatenation, which Postgres
        # performs and SQLite refuses, so the migration only ran where it had
        # already run.
        bind.execute(sa.text(f"""
            INSERT INTO products
                (slug, name, summary, price, playbook_slug, is_active,
                 sort_order, prompt_intro{extra_col})
            VALUES
                (:slug, :name, :summary, 2500, 'stripe', true, 20, ''{extra_val})
        """), {
            "slug": "billing", "name": "Invoicing and payments",
            "summary": "Invoices built from the work already recorded, and a "
                       "way for customers to pay them by card. The money "
                       "settles into the client's own account - I never hold "
                       "or handle it. Stripe unless they ask for a different "
                       "provider.",
        })


def downgrade():
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("products")}
    extra_col = ", includes_hosting" if "includes_hosting" in cols else ""
    extra_val = ", true" if "includes_hosting" in cols else ""
    bind.execute(sa.text("DELETE FROM products WHERE slug = 'billing'"))
    statement = sa.text(f"""
        INSERT INTO products (slug, name, summary, price, playbook_slug,
                              is_active, sort_order, prompt_intro{extra_col})
        VALUES (:slug, :name, :summary, :price, :playbook, true, :order,
                ''{extra_val})
    """)
    bind.execute(statement, {
        "slug": "payments", "name": "Card payments",
        "summary": "Customers pay through the software. The money lands in "
                   "the client's own account; they stay merchant of record.",
        "price": 1000, "playbook": "stripe", "order": 20,
    })
    bind.execute(statement, {
        "slug": "invoicing", "name": "Invoice generation",
        "summary": "Invoices built from the work already recorded, as PDFs, "
                   "without retyping any of it.",
        "price": 1000, "playbook": None, "order": 40,
    })
