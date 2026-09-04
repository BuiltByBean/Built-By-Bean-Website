"""Products get a category

The products page was one long list. A sale is discussed in an order - the
build itself, getting paid, reaching people, the paperwork, running the
day, their own site and systems - and the page now reads in that order,
one card per category with its count.

One column, backfilled by slug for everything the shelf has held so far.
Anything the door creates later says its category or lands in "running
the day", which is where most of what gets sold lives.

Revision ID: c4a9d17e5b20
Revises: b2c7e9d41f05
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "c4a9d17e5b20"
down_revision = "b2c7e9d41f05"
branch_labels = None
depends_on = None


# slug -> category. Old slugs are here too, because a database that never
# ran the later renames still gets the right answer.
CATEGORIES = {
    "custom-build": "build",
    "billing": "money", "payments": "money", "invoicing": "money",
    "texting": "comms", "email": "comms", "reviews": "comms",
    "signadoc": "documents",
    "scheduling": "operations", "inventory": "operations",
    "time-mileage": "operations", "roster": "operations",
    "content": "connect", "api-connection": "connect", "crm-sync": "connect",
}


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("products")}
    if "category" not in columns:
        op.add_column("products", sa.Column(
            "category", sa.String(length=20), nullable=False,
            server_default="operations"))
        op.create_index("ix_products_category", "products", ["category"])

    for slug, category in CATEGORIES.items():
        bind.execute(sa.text(
            "UPDATE products SET category = :category WHERE slug = :slug"),
            {"category": category, "slug": slug})


def downgrade():
    op.drop_index("ix_products_category", table_name="products")
    op.drop_column("products", "category")
