"""Products, and a record of what was sold to whom

The catalogue of things that can be bought on their own, and one row per
purchase. The wording that goes into an add-on contract stays in
contract_docs.PRODUCTS, keyed by the same slug; what lands here is the part
that changes without a deploy - the price - and the two joins the contract
layer has no opinion about: which runbook applies, and who bought it.

Revision ID: f8b3c1d09a47
Revises: e2b9f480a1c5
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "f8b3c1d09a47"
down_revision = "e2b9f480a1c5"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    """Create both tables, unless something already has.

    create_app() calls db.create_all() on every boot, so anything that opens
    the app against this database - a deploy, or a script run by hand - builds
    whatever tables the models declare and the migrations have not made yet.
    In a normal deploy that is harmless: `flask db upgrade` runs first and
    create_all finds everything present. It stops being harmless the moment
    the app is pointed at the database before the migration ships. The table
    appears, the revision does not move, and the next deploy dies on CREATE
    TABLE - with gunicorn behind it in the same `&&`, so the site does not
    come back.

    That happened to this very migration while it was being written. Skipping
    what is already there costs one query and turns a downed site into a
    no-op.
    """
    existing = _tables()

    if "products" not in existing:
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=60), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("monthly_price", sa.Float(), nullable=True),
            sa.Column("playbook_slug", sa.String(length=60), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False,
                      server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("prompt_intro", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_products_slug"),
        )

    if "product_sales" not in existing:
        op.create_table(
            "product_sales",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            # Not nullable on purpose. A standalone purchase still gets a
            # project, because the runbook, the hosting fee and the tickets
            # for it all hang off one, and a sale with nowhere to put those is
            # a sale nobody can deliver.
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("monthly_price", sa.Float(), nullable=True),
            sa.Column("delivery_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # Same reasoning as the tables: create_all builds these from index=True on
    # the model, so they can already exist even when the table did not.
    have = {i["name"] for i in
            sa.inspect(op.get_bind()).get_indexes("product_sales")}
    for column in ("product_id", "client_id", "project_id"):
        name = f"ix_product_sales_{column}"
        if name not in have:
            op.create_index(name, "product_sales", [column])


def downgrade():
    op.drop_table("product_sales")
    op.drop_table("products")
