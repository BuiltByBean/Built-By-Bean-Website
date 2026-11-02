"""A service tile adopts the playbook named like it, and Zapier comes off

Michael, 2026-11-02: "It's also saying there's no playbook for Mercury."
The Mercury and LegalZoom playbooks were filed through the door that
afternoon, after the map's tiles had been seeded without them, so the tiles
still read as having none. A service tile with no playbook now takes the
one whose slug or name matches its own, on every business.

And "I have no idea what Zapier even is. Double check that we're actually
using that." EntertainHQ's code and config never name it; its docs mention
it only for the tools tenants migrate from, and a planned endpoint their
own Zapier could post to. So the seeded Zapier tile and its lines go.

Revision ID: c0e4b7d2a915
Revises: b6d1f3a8c729
Create Date: 2026-11-02
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "c0e4b7d2a915"
down_revision = "b6d1f3a8c729"
branch_labels = None
depends_on = None

SEEDED = "Seeded from the repo on 2026-11-02; confirm it."


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def adopt(bind):
    """Every service with no playbook takes the one named like it."""
    playbooks = bind.execute(sa.text("SELECT id, slug, display_name FROM playbooks")).fetchall()
    by_slug = {p[1]: p[0] for p in playbooks}
    by_name = {_slug(p[2]): p[0] for p in playbooks}
    rows = bind.execute(sa.text(
        "SELECT id, name FROM business_nodes WHERE kind = 'service' AND playbook_id IS NULL AND name != ''")).fetchall()
    for nid, name in rows:
        pb = by_slug.get(_slug(name)) or by_name.get(_slug(name))
        if pb:
            bind.execute(sa.text("UPDATE business_nodes SET playbook_id = :pb WHERE id = :id"), {"pb": pb, "id": nid})


def upgrade():
    if not {"business_nodes", "business_edges", "playbooks", "businesses"} <= _tables():
        return
    bind = op.get_bind()
    adopt(bind)
    biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = 'entertainhq'")).first()
    if biz is None:
        return
    for row in bind.execute(sa.text(
            "SELECT id FROM business_nodes WHERE business_id = :b AND kind = 'service' AND name = 'Zapier' "
            "AND notes = :seeded"), {"b": biz[0], "seeded": SEEDED}).fetchall():
        bind.execute(sa.text("DELETE FROM business_edges WHERE from_node_id = :id OR to_node_id = :id"), {"id": row[0]})
        bind.execute(sa.text("DELETE FROM business_nodes WHERE id = :id"), {"id": row[0]})


def downgrade():
    pass
