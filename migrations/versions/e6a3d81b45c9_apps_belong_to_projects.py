"""an app on the board knows which project it is

The board and the project list have been describing the same things with
nothing joining them: a Kuper Plumbing tile and a KuperPlumbing.com project,
side by side, each unaware of the other. Standing on the project there was no
way to reach the running app, its Railway service or its repo — all three of
which are on the tile, two clicks and a different page away.

Nullable, because half the board is mine rather than a client's. SET NULL on
delete, because closing an engagement does not take the app off the board —
the app is still running and still somewhere I go.

The backfill only claims the two pairs that are unambiguous today, and only
where the tile has no project yet. Everything else is a dropdown on the tile's
edit page.

Revision ID: e6a3d81b45c9
Revises: d2b9c4e07f31
Create Date: 2026-09-01 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6a3d81b45c9'
down_revision = 'd2b9c4e07f31'
branch_labels = None
depends_on = None


# (app tile name, project name) — matched exactly, both must already exist.
PAIRS = [
    ("Kuper Plumbing", "KuperPlumbing.com"),
    ("J&D Entertainment", "Talent Booker"),
]


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    if "app_links" not in tables:
        return

    if "project_id" not in {c["name"] for c in insp.get_columns("app_links")}:
        with op.batch_alter_table("app_links", schema=None) as batch_op:
            batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_app_links_project_id", "projects",
                                        ["project_id"], ["id"], ondelete="SET NULL")
            batch_op.create_index("ix_app_links_project_id", ["project_id"])

    if "projects" not in tables:
        return
    for app_name, project_name in PAIRS:
        conn.execute(sa.text(
            "UPDATE app_links SET project_id = "
            "(SELECT id FROM projects WHERE name = :p) "
            "WHERE name = :a AND project_id IS NULL "
            "AND EXISTS (SELECT 1 FROM projects WHERE name = :p)"),
            {"a": app_name, "p": project_name})


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "app_links" not in set(insp.get_table_names()):
        return
    if "project_id" in {c["name"] for c in insp.get_columns("app_links")}:
        with op.batch_alter_table("app_links", schema=None) as batch_op:
            batch_op.drop_index("ix_app_links_project_id")
            batch_op.drop_constraint("fk_app_links_project_id", type_="foreignkey")
            batch_op.drop_column("project_id")
