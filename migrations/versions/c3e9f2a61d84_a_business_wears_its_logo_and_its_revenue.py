"""A business wears its logo and its revenue

The Businesses page was the tax desk: WebFile numbers and the next return on
every card. Michael, 2026-11-01: "as my business grows I want these done
differently. Where I can see the business", with the name, the logo, the start
date and the lifetime revenue up front, and the tax inside each business.

A logo is an uploaded image or the icon of one of its apps on My Apps. The two
businesses on the board get their app's icon here, found by the tile's address
or name, and the migration prints what it picked so the deploy log says so.
Revenue for a business whose sales come over the hub is kept here as its app
last reported it; nothing is fetched by a migration.

Revision ID: c3e9f2a61d84
Revises: a4c8e1f37b25
"""
from alembic import op
import sqlalchemy as sa


revision = "c3e9f2a61d84"
down_revision = "a4c8e1f37b25"
branch_labels = None
depends_on = None


COLUMNS = (
    ("logo_file", lambda: sa.String(length=120)),
    ("logo_app_id", lambda: sa.Integer()),
    ("revenue_total", lambda: sa.Float()),
    ("revenue_as_of", lambda: sa.DateTime()),
)
FK = "fk_businesses_logo_app_id"

# Business slug -> how to find its app's tile: an address fragment, then a
# name pattern. First match with an icon wins.
LOGOS = {
    "built-by-bean": ("builtbybeans.com", "built by bean%"),
    "entertainhq": ("entertainhq.com", "entertainhq%"),
}


def _present():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("businesses")}


def _fks():
    return {fk.get("name") for fk in sa.inspect(op.get_bind()).get_foreign_keys("businesses")}


def upgrade():
    # create_all runs on boot and wins the race, so a column may already be
    # here (CLAUDE.md, migrations).
    have = _present()
    todo = [(n, t) for n, t in COLUMNS if n not in have]
    if todo:
        with op.batch_alter_table("businesses") as batch:
            for name, type_ in todo:
                batch.add_column(sa.Column(name, type_(), nullable=True))
    if FK not in _fks():
        with op.batch_alter_table("businesses") as batch:
            batch.create_foreign_key(FK, "app_links", ["logo_app_id"], ["id"], ondelete="SET NULL")

    bind = op.get_bind()
    for slug, (host, name) in LOGOS.items():
        row = bind.execute(sa.text(
            "SELECT id, logo_app_id, logo_file FROM businesses WHERE slug = :s"), {"s": slug}).first()
        if row is None:
            print(f"Businesses: {slug}: not on this board")
            continue
        if row.logo_app_id or row.logo_file:
            print(f"Businesses: {slug}: already has a logo")
            continue
        tile = bind.execute(sa.text(
            "SELECT id, name FROM app_links WHERE icon_file IS NOT NULL AND icon_file <> '' "
            "AND (lower(url) LIKE :h OR lower(name) LIKE :n) ORDER BY id"),
            {"h": f"%{host}%", "n": name}).first()
        if tile is None:
            print(f"Businesses: {slug}: no My Apps tile with an icon found")
            continue
        bind.execute(sa.text("UPDATE businesses SET logo_app_id = :a WHERE id = :b"),
                     {"a": tile.id, "b": row.id})
        print(f"Businesses: {slug}: logo from the {tile.name} tile")


def downgrade():
    if FK in _fks():
        with op.batch_alter_table("businesses") as batch:
            batch.drop_constraint(FK, type_="foreignkey")
    have = _present()
    todo = [n for n, _ in reversed(COLUMNS) if n in have]
    if todo:
        with op.batch_alter_table("businesses") as batch:
            for name in todo:
                batch.drop_column(name)
