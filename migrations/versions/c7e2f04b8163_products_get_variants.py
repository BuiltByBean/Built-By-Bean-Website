"""Which one, within a product

A product is the shape of the work. A variant is whose platform it lands on:
invoicing is the same build every time and the hard half is which payment
provider it connects to. Same for an API connection - the same job whether the
far end is Tripleseat or something nobody has met yet.

Catalogued as they are met. The first sale against a new system writes its
variant, so the second client on that platform picks it from a list.

Revision ID: c7e2f04b8163
Revises: b5d81a30f2c9
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "c7e2f04b8163"
down_revision = "b5d81a30f2c9"
branch_labels = None
depends_on = None


# (product slug, variant slug, name, playbook slug, sort)
#
# Only what is actually known. A guess at which providers Michael will be
# asked for would be a catalogue of things he has never set up, and the point
# of these is that each one has been done at least once.
SEED = [
    ("billing", "stripe", "Stripe", "stripe", 0),
    ("texting", "twilio", "Twilio", "twilio", 0),
    ("email", "resend", "Resend", "resend", 0),
    ("email", "gmail-smtp", "Gmail SMTP", "gmail-smtp", 10),
    ("api-connection", "tripleseat", "Tripleseat", "tripleseat", 0),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Guarded for the same reason every table here is: create_app calls
    # db.create_all() on boot and the deploy's `flask db upgrade` loads the app
    # first, so the table can already exist by the time this runs.
    if "product_variants" not in set(inspector.get_table_names()):
        op.create_table(
            "product_variants",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=60), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("playbook_slug", sa.String(length=60), nullable=True),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False,
                      server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("product_id", "slug",
                                name="uq_product_variant_slug"),
        )
        op.create_index("ix_product_variants_product_id", "product_variants",
                        ["product_id"])

    columns = {c["name"] for c in inspector.get_columns("product_sales")}
    if "variant_id" not in columns:
        op.add_column("product_sales",
                      sa.Column("variant_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_product_sales_variant_id", "product_sales",
                              "product_variants", ["variant_id"], ["id"],
                              ondelete="SET NULL")
        op.create_index("ix_product_sales_variant_id", "product_sales",
                        ["variant_id"])

    # The API connection product, renamed from the placeholder the catalogue
    # was seeded with. "crm-sync" described one use of it; pulling data from a
    # system somebody already runs is the job, whether or not that system is
    # a CRM. The summary travels as a bound parameter because the inline
    # version leaned on newline string-literal concatenation, which Postgres
    # performs and SQLite refuses.
    bind.execute(sa.text("""
        UPDATE products
           SET slug = 'api-connection',
               name = 'API connection',
               summary = :summary
         WHERE slug = 'crm-sync'
    """), {"summary": "Reading from, and writing back to, a system the "
                      "business already runs on. The build is the same shape "
                      "each time; which platform it connects to is the part "
                      "that decides the work."})

    have_products = {row[0]: row[1] for row in
                     bind.execute(sa.text("SELECT slug, id FROM products"))}
    for product_slug, slug, name, playbook, order in SEED:
        product_id = have_products.get(product_slug)
        if product_id is None:
            continue
        exists = bind.execute(sa.text(
            "SELECT 1 FROM product_variants WHERE product_id = :p AND slug = :s"
        ), {"p": product_id, "s": slug}).first()
        if exists:
            continue
        bind.execute(sa.text("""
            INSERT INTO product_variants
                (product_id, slug, name, playbook_slug, is_active, sort_order, notes)
            VALUES (:p, :s, :n, :pb, true, :o, '')
        """), {"p": product_id, "s": slug, "n": name, "pb": playbook, "o": order})


def downgrade():
    op.drop_index("ix_product_sales_variant_id", table_name="product_sales")
    op.drop_constraint("fk_product_sales_variant_id", "product_sales",
                       type_="foreignkey")
    op.drop_column("product_sales", "variant_id")
    op.drop_table("product_variants")
    op.execute("""
        UPDATE products SET slug = 'crm-sync',
                            name = 'Sync with a system you already use'
         WHERE slug = 'api-connection'
    """)
