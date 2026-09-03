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

    already = bind.execute(sa.text(
        "SELECT COUNT(*) FROM products WHERE slug = 'billing'")).scalar()
    if not already:
        bind.execute(sa.text("""
            INSERT INTO products
                (slug, name, summary, price, playbook_slug, is_active,
                 sort_order, prompt_intro)
            VALUES
                ('billing', 'Invoicing and payments',
                 'Invoices built from the work already recorded, and a way for '
                 'customers to pay them by card. The money settles into the '
                 'client''s own account - I never hold or handle it. Stripe '
                 'unless they ask for a different provider.',
                 2500, 'stripe', true, 20, '')
        """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM products WHERE slug = 'billing'"))
    bind.execute(sa.text("""
        INSERT INTO products (slug, name, summary, price, playbook_slug,
                              is_active, sort_order, prompt_intro)
        VALUES
            ('payments', 'Card payments',
             'Customers pay through the software. The money lands in the '
             'client''s own account; they stay merchant of record.',
             1000, 'stripe', true, 20, ''),
            ('invoicing', 'Invoice generation',
             'Invoices built from the work already recorded, as PDFs, without '
             'retyping any of it.',
             1000, NULL, true, 40, '')
    """))
