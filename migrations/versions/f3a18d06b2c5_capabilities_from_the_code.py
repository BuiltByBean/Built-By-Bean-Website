"""Capabilities read from the code, not the ledger

Cerebro said neither Kuper Plumbing nor Talent Booker had text messaging,
because it read only the sales table and texting was built into both
before the products catalogue existed. A product now carries what it
looks like in a codebase - twilio for texting, stripe for billing - and
the nightly audit records where each signature fires, so a cell can say
"in the code" when no sale was ever logged.

Revision ID: f3a18d06b2c5
Revises: e2f07c95a1b4
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "f3a18d06b2c5"
down_revision = "e2f07c95a1b4"
branch_labels = None
depends_on = None


# (slug, pattern, globs, exclude, fixture). A vendor's name in the code is
# the product being there; only the products with an unambiguous vendor
# get a signature, because "scheduling" in a codebase means nothing.
SIGNATURES = [
    ("texting", r"\btwilio\b|TWILIO_", "**/*.py,requirements.txt,package.json",
     "node_modules/", "from twilio.rest import Client"),
    ("billing", r"\bstripe\b|STRIPE_", "**/*.py,requirements.txt,package.json",
     "node_modules/", "import stripe"),
    ("signadoc", r"signadoc|SIGNADOC_", "**/*.py", None,
     'SIGNADOC_URL = os.environ["SIGNADOC_URL"]'),
    ("email", r"\bresend\b|RESEND_API", "**/*.py,requirements.txt,package.json",
     "node_modules/", 'RESEND_API_KEY = os.environ["RESEND_API_KEY"]'),
]


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    have = _columns(bind, "products")
    for name, kind in (("presence_pattern", sa.Text()), ("presence_globs", sa.String(300)),
                       ("presence_exclude", sa.String(300)), ("presence_fixture", sa.Text())):
        if name not in have:
            op.add_column("products", sa.Column(name, kind, nullable=True))

    if not sa.inspect(bind).has_table("product_audits"):
        op.create_table(
            "product_audits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("repo", sa.String(length=200), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("sha", sa.String(length=64), nullable=True),
            sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sample_json", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_product_audits"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    name="fk_product_audits_product_id", ondelete="CASCADE"),
            sa.UniqueConstraint("repo", "product_id", name="uq_product_audits_repo_product"),
        )
        op.create_index("ix_product_audits_repo", "product_audits", ["repo"])
        op.create_index("ix_product_audits_product_id", "product_audits", ["product_id"])

    update = sa.text(
        "UPDATE products SET presence_pattern = :pattern, presence_globs = :globs, "
        "presence_exclude = :exclude, presence_fixture = :fixture "
        "WHERE slug = :slug AND presence_pattern IS NULL")
    for slug, pattern, globs, exclude, fixture in SIGNATURES:
        bind.execute(update, {"slug": slug, "pattern": pattern, "globs": globs,
                              "exclude": exclude, "fixture": fixture})


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("product_audits"):
        op.drop_index("ix_product_audits_product_id", table_name="product_audits")
        op.drop_index("ix_product_audits_repo", table_name="product_audits")
        op.drop_table("product_audits")
    have = _columns(bind, "products")
    with op.batch_alter_table("products") as batch:
        for name in ("presence_pattern", "presence_globs", "presence_exclude",
                     "presence_fixture"):
            if name in have:
                batch.drop_column(name)
