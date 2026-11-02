"""A business's three dates, and its paperwork on file

Michael, 2026-11-02: when a business was first an idea, when it launched,
and how old it is; and the LLC documents LegalZoom holds, kept here for each
business he has an LLC for.

  * businesses.conceived_on and launched_on, beside the formed_on that is
    already there (the day the LLC was filed). Age is worked out, not stored.
  * business_documents: one row per paper, the file on the volume under
    business_documents/ by a random name, as a return's confirmation is.

The columns go in one batch; the table is guarded on not existing, because
create_all runs on boot and may have made it first. Constraints are named.

Revision ID: a8e4c1d9f2b7
Revises: f3b9d27c4e18
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "a8e4c1d9f2b7"
down_revision = "f3b9d27c4e18"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    if table not in _tables():
        return None
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _columns("businesses")
    if have is None:
        return  # create_all will build it complete
    missing = [c for c in ("conceived_on", "launched_on") if c not in have]
    if missing:
        with op.batch_alter_table("businesses", schema=None) as batch_op:
            for name in missing:
                batch_op.add_column(sa.Column(name, sa.Date(), nullable=True))

    if "business_documents" not in _tables():
        op.create_table(
            "business_documents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="other"),
            sa.Column("title", sa.String(length=200), nullable=True),
            sa.Column("stored_name", sa.String(length=100), nullable=False),
            sa.Column("original_name", sa.String(length=300), nullable=False),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("size", sa.Integer(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_documents_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_documents"),
        )
        op.create_index("ix_business_documents_business_id", "business_documents", ["business_id"])


def downgrade():
    # The child table first, then the columns.
    if "business_documents" in _tables():
        op.drop_index("ix_business_documents_business_id", table_name="business_documents")
        op.drop_table("business_documents")
    have = _columns("businesses")
    if have is None:
        return
    present = [c for c in ("launched_on", "conceived_on") if c in have]
    if present:
        with op.batch_alter_table("businesses", schema=None) as batch_op:
            for name in present:
                batch_op.drop_column(name)
