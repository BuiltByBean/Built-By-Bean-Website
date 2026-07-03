"""Widen expenses.description from VARCHAR(300) to TEXT

Timer/time-entry work write-ups can be long (the mirror billable_time expense
copies the full time-entry description, which is TEXT). VARCHAR(300) caused a
StringDataRightTruncation 500 on save. Widen to TEXT to match.

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a1b2c3"
down_revision = "c3d4e5f6a1b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.alter_column(
            "description",
            existing_type=sa.String(length=300),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.alter_column(
            "description",
            existing_type=sa.Text(),
            type_=sa.String(length=300),
            existing_nullable=True,
        )
