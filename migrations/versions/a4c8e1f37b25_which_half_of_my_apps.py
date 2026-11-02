"""Which half of My Apps a tile sits in

My Apps split by project: attached meant Client work, unattached meant Mine.
On 2026-11-01 Michael said the two are not the same question: "robinson &
co, let's cook, piped dev and christ community church" are not current client
work, just his dev work, and "data dungeon should be moved into the client
work area" although it has no client. Detaching the projects would take those
apps off their project pages, and register_app re-attaches a project on its
next call, so the tile carries its own answer instead: board_group "client" or
"mine", NULL to follow the project as before.

The five are found by the projects the board holds them under, or by the
tile's own name where one is not attached, and the migration prints each tile
it sets so the deploy log says what moved.

Revision ID: a4c8e1f37b25
Revises: e2a7c41d9b60
"""
from alembic import op
import sqlalchemy as sa


revision = "a4c8e1f37b25"
down_revision = "e2a7c41d9b60"
branch_labels = None
depends_on = None


# Project names as the live board held them on 2026-11-01, and tile names
# for a tile with no project attached.
MINE_PROJECTS = ("Robinsonandco Project Manager", "Christ Community Church", "Lets Cook", "Piped")
MINE_NAMES = ("robinson%", "let%s cook%", "piped%", "christ community%")
CLIENT_NAMES = ("data dungeon%",)
CLIENT_HOSTS = ("%datadungeon.io%",)


def _present():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("app_links")}


def _set(bind, group, ids):
    for app_id in ids:
        bind.execute(sa.text("UPDATE app_links SET board_group = :g WHERE id = :i"),
                     {"g": group, "i": app_id})


def upgrade():
    # create_all runs on boot and wins the race, so the column may already be
    # here (CLAUDE.md, migrations).
    if "board_group" not in _present():
        with op.batch_alter_table("app_links") as batch:
            batch.add_column(sa.Column("board_group", sa.String(length=10), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT a.id, a.name, a.url, a.board_group, p.name AS project "
        "FROM app_links a LEFT JOIN projects p ON p.id = a.project_id")).mappings().all()

    def like(value, patterns):
        import fnmatch
        v = (value or "").lower()
        return any(fnmatch.fnmatch(v, p.replace("%", "*")) for p in patterns)

    mine = [r for r in rows if r["project"] in MINE_PROJECTS or like(r["name"], MINE_NAMES)]
    client = [r for r in rows if like(r["name"], CLIENT_NAMES) or like(r["url"], CLIENT_HOSTS)]
    # Only a tile nobody has chosen for yet: a re-run, or a choice already
    # made on the edit form, is left alone.
    mine = [r for r in mine if r["board_group"] is None]
    client = [r for r in client if r["board_group"] is None and r not in mine]
    _set(bind, "mine", [r["id"] for r in mine])
    _set(bind, "client", [r["id"] for r in client])
    for label, picked in (("Mine", mine), ("Client work", client)):
        print(f"My Apps: {label}: " + (", ".join(r["name"] for r in picked) or "nothing to move"))


def downgrade():
    if "board_group" in _present():
        with op.batch_alter_table("app_links") as batch:
            batch.drop_column("board_group")
