"""Every vendor account says which vendor it is with, and where it was found

Michael, 2026-11-05: Vendors becomes its own page with one tile per vendor
and its accounts under it, and the night adds vendors it finds on the bank
and in the apps' code. `vendor` is the grouping (an account's `name` is how it
syncs: Claude is "flat"); `discovered_from` says where the night found one.
Every existing account is given its vendor from its display name, without
the account in brackets: "Railway (EntertainHQ)" is Railway.

Revision ID: b3e8c1f5d742
Revises: a6d1f3b8c427
Create Date: 2026-11-05
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "b3e8c1f5d742"
down_revision = "a6d1f3b8c427"
branch_labels = None
depends_on = None


def _cols(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns("service_providers")}


def upgrade():
    bind = op.get_bind()
    cols = _cols(bind)
    if "vendor" not in cols:
        op.add_column("service_providers", sa.Column("vendor", sa.String(100), nullable=True))
    if "discovered_from" not in cols:
        op.add_column("service_providers", sa.Column("discovered_from", sa.String(200), nullable=True))
    for pid, name, display in bind.execute(sa.text(
            "SELECT id, name, display_name FROM service_providers WHERE vendor IS NULL OR vendor = ''")).all():
        vendor = re.sub(r"\s*\(.*\)\s*$", "", display or "").strip() or name
        bind.execute(sa.text("UPDATE service_providers SET vendor = :v WHERE id = :id"), {"v": vendor, "id": pid})


def downgrade():
    bind = op.get_bind()
    # The night's finds have no meaning to the old code, which would try to
    # sync a "bank" or "code" account and fail every night.
    bind.execute(sa.text("DELETE FROM service_providers WHERE name IN ('bank', 'code')"))
    cols = _cols(bind)
    with op.batch_alter_table("service_providers") as batch:
        if "discovered_from" in cols:
            batch.drop_column("discovered_from")
        if "vendor" in cols:
            batch.drop_column("vendor")
