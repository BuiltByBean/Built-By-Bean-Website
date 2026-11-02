"""A business can be a division of another, and Data Dungeon is one

Michael, 2026-11-02: Data Dungeon "is technically not its own business
because it sits under my Built by Bean LLC, but it effectively is a business
... kind of like a division." So `businesses.parent_id` names the company a
division trades under, and Data Dungeon goes on file as Built by Bean's.

A division has no taxpayer number, permit or return of its own: its taxable
sales are Built by Bean LLC's and go on Built by Bean's return, which is why
the returns pages leave divisions out. It is a tile on Businesses with its
own logo, start date and revenue.

Its logo is its My Apps icon when one is on file. Its start date is not known
here, so it is left for Michael to type. The insert is skipped when the row is
already there, and the column, its foreign key and its index go in one batch,
as every migration here does them. Bound parameters throughout.

Revision ID: f3b9d27c4e18
Revises: d5b1e8f40a63
Create Date: 2026-11-02
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "f3b9d27c4e18"
down_revision = "d5b1e8f40a63"
branch_labels = None
depends_on = None

TABLE = "businesses"
FK = "fk_businesses_parent_id"
INDEX = "ix_businesses_parent_id"
PARENT_SLUG = "built-by-bean"
SLUG = "data-dungeon"
NOW = datetime(2026, 11, 2, 18, 0)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns():
    if TABLE not in _tables():
        return None  # create_all will build it complete
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    have = _columns()
    if have is None:
        return
    if "parent_id" not in have:
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(FK, TABLE, ["parent_id"], ["id"], ondelete="SET NULL")
            batch_op.create_index(INDEX, ["parent_id"])

    bind = op.get_bind()
    parent = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                          {"slug": PARENT_SLUG}).first()
    if parent is None:
        return  # nothing to be a division of; the form can add it later
    if bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                    {"slug": SLUG}).first() is not None:
        return

    logo_app_id = None
    if "app_links" in _tables():
        app = bind.execute(sa.text(
            "SELECT id FROM app_links WHERE LOWER(name) LIKE :name AND icon_file IS NOT NULL "
            "AND icon_file != '' ORDER BY id"), {"name": "%data dungeon%"}).first()
        logo_app_id = app[0] if app else None

    bind.execute(sa.text(
        "INSERT INTO businesses (name, short_name, slug, texas_taxpayer_number, "
        "sos_file_number, franchise_tax_webfile, sales_tax_webfile, sales_tax_frequency, "
        "taxable_share, naics_code, sales_source, admin_url, hub_base_url, hub_secret, "
        "hub_pull_note, notes, is_active, parent_id, logo_app_id, created_at, updated_at) "
        "VALUES (:name, :short_name, :slug, '', '', '', '', 'quarterly', 80, '', 'manual', '', "
        "'', '', '', :notes, :active, :parent_id, :logo_app_id, :now, :now)"),
        {"name": "Data Dungeon", "short_name": "Data Dungeon", "slug": SLUG,
         "notes": "A division of Built by Bean LLC. Its taxable sales go on Built by Bean's return.",
         "active": True, "parent_id": parent[0], "logo_app_id": logo_app_id, "now": NOW})


def downgrade():
    have = _columns()
    if have is None or "parent_id" not in have:
        return
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM businesses WHERE slug = :slug"), {"slug": SLUG})
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        # Wrapped: SQLite does not record a constraint's name, so a drop by
        # name is a no-op there and the table rebuild is what removes it.
        try:
            batch_op.drop_index(INDEX)
        except Exception:
            pass
        try:
            batch_op.drop_constraint(FK, type_="foreignkey")
        except Exception:
            pass
        batch_op.drop_column("parent_id")
