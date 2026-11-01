"""The store versions an app wears

A phone app on My Apps is shipped twice, to the App Store and to Google
Play, and the two store pages show one product with one version. The tile
now carries the two store ids (Apple bundle id, Android package name) and
the last answer each public store page gave for the live version, so the
board shows at a glance whether the stores agree and which one is still in
review. Asked for on 2026-11-01 ("make sure the versions match between the
App Store and the Google Play Store").

Nullable and empty. Nothing is fetched here: a migration that reaches out to
other people's servers is a deploy that hangs on somebody else's outage.

Revision ID: e2a7c41d9b60
Revises: d9a25e6c1b47
"""
from alembic import op
import sqlalchemy as sa


revision = "e2a7c41d9b60"
down_revision = "d9a25e6c1b47"
branch_labels = None
depends_on = None


COLUMNS = (
    ("app_store_bundle_id", lambda: sa.String(length=200)),
    ("play_package", lambda: sa.String(length=200)),
    ("store_versions", lambda: sa.Text()),
    ("store_checked_at", lambda: sa.DateTime()),
)


def _present():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("app_links")}


def upgrade():
    # create_all runs on boot and wins the race, so a column may already be
    # here on an environment that booted before this landed. Guarded rather
    # than assumed (CLAUDE.md, migrations).
    have = _present()
    todo = [(n, t) for n, t in COLUMNS if n not in have]
    if not todo:
        return
    with op.batch_alter_table("app_links") as batch:
        for name, type_ in todo:
            batch.add_column(sa.Column(name, type_(), nullable=True))


def downgrade():
    have = _present()
    todo = [n for n, _ in reversed(COLUMNS) if n in have]
    if not todo:
        return
    with op.batch_alter_table("app_links") as batch:
        for name in todo:
            batch.drop_column(name)
