"""make service cost syncing safe to run every day

Two changes, both prerequisites for putting the sync on a schedule.

A flat monthly cost on the provider, for a vendor whose API will not tell you
what you are spending. Railway is the case in hand: its GraphQL schema exposes
CPU, memory, disk and network, and no measurement anywhere in it is denominated
in money, so the only way to book Railway is a figure a human sets once.

And the uniqueness key on a cost entry gains the mapping. It was
(provider, resource, period), which is right for one entry per resource per
period and wrong the moment a resource is split between two clients: the sync
writes one row per mapping, all four columns identical, and the second insert
violates the constraint and takes the whole sync down. Adding mapping_id makes
one row per allocation legal while still refusing a genuine duplicate.

mapping_id is nullable and Postgres treats NULLs as distinct, so the constraint
does not stop two unallocated rows for the same period. The sync guards that
itself by looking the entry up before writing.

Revision ID: c9b1f47ea230
Revises: a7f4e2b19c60
Create Date: 2026-08-31 12:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9b1f47ea230'
down_revision = 'a7f4e2b19c60'
branch_labels = None
depends_on = None

OLD = ("provider_id", "resource_identifier", "period_start", "period_end")
NEW = OLD + ("mapping_id",)


def _has_column(conn, table, column):
    return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _constraint_names(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_unique_constraints(table)}


def upgrade():
    conn = op.get_bind()

    if not _has_column(conn, "service_providers", "monthly_cost"):
        with op.batch_alter_table("service_providers", schema=None) as batch_op:
            batch_op.add_column(sa.Column("monthly_cost", sa.Float(), nullable=True))

    existing = _constraint_names(conn, "service_cost_entries")
    if "uq_service_cost_entry" in existing:
        with op.batch_alter_table("service_cost_entries", schema=None) as batch_op:
            batch_op.drop_constraint("uq_service_cost_entry", type_="unique")
    if "uq_service_cost_entry_alloc" not in existing:
        with op.batch_alter_table("service_cost_entries", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_service_cost_entry_alloc", list(NEW))


def downgrade():
    conn = op.get_bind()

    existing = _constraint_names(conn, "service_cost_entries")
    if "uq_service_cost_entry_alloc" in existing:
        with op.batch_alter_table("service_cost_entries", schema=None) as batch_op:
            batch_op.drop_constraint("uq_service_cost_entry_alloc", type_="unique")
    if "uq_service_cost_entry" not in existing:
        # Going back needs the narrower key to be true again, so collapse any
        # split allocations down to one row per resource per period first.
        op.execute(
            "DELETE FROM service_cost_entries WHERE id NOT IN ("
            "  SELECT MIN(id) FROM service_cost_entries"
            "  GROUP BY provider_id, resource_identifier, period_start, period_end"
            ")"
        )
        with op.batch_alter_table("service_cost_entries", schema=None) as batch_op:
            batch_op.create_unique_constraint("uq_service_cost_entry", list(OLD))

    if _has_column(conn, "service_providers", "monthly_cost"):
        with op.batch_alter_table("service_providers", schema=None) as batch_op:
            batch_op.drop_column("monthly_cost")
