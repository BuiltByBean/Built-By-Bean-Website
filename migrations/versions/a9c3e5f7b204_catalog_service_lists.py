"""The catalog: services added or hidden by hand, scale and features, per app

Issue #24, 2026-11-06. The code reading misses some services (YouTube, the
stores) and finds some an app no longer uses (EntertainHQ's retired
texting). Two lists Michael keeps per app, which the nightly reading does not
touch.

Revision ID: a9c3e5f7b204
Revises: f6a2d8c4e157
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "a9c3e5f7b204"
down_revision = "f6a2d8c4e157"
branch_labels = None
depends_on = None

COLUMNS = ("catalog_services_extra", "catalog_services_hidden", "catalog_scale", "catalog_highlights")


def _cols(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns("app_links")}


def upgrade():
    have = _cols(op.get_bind())
    missing = [c for c in COLUMNS if c not in have]
    if missing:
        with op.batch_alter_table("app_links") as batch:
            for name in missing:
                kind = sa.String(160) if name == "catalog_scale" else sa.Text()
                batch.add_column(sa.Column(name, kind, nullable=True))


def downgrade():
    have = _cols(op.get_bind())
    gone = [c for c in COLUMNS if c in have]
    if gone:
        with op.batch_alter_table("app_links") as batch:
            for name in gone:
                batch.drop_column(name)
