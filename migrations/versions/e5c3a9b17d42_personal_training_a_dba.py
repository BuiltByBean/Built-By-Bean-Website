"""Personal Training goes on file as a DBA of Built by Bean, with its checks

Michael, 2026-11-04, of the check deposits on Built by Bean's Chase business
checking: "those were money from a personal training gig I used to do it was
the original purpose of my built by beans llc ... that income would count as
built by beans income but show it specifically as kind of a dba for my
purposes here under personal training."

So Personal Training is a division of Built by Bean LLC, as Data Dungeon is,
and every check deposit on the company's own Chase checking that was read as
money in now belongs to it. books_service counts a DBA's bank income in its
parent's figures, so Built by Bean's income goes up by exactly these lines
and shows them under their own name.

Only lines already settled as income move: a check on a personal account is
never the company's income, and anything Michael settled otherwise stays as
he settled it. Statement re-uploads skip lines already read, so the move
holds. Bound parameters throughout.

Revision ID: e5c3a9b17d42
Revises: b8e4d17a6c30
Create Date: 2026-11-04
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "e5c3a9b17d42"
down_revision = "b8e4d17a6c30"
branch_labels = None
depends_on = None

PARENT_SLUG = "built-by-bean"
SLUG = "personal-training"
KIND = "CHECK_DEPOSIT"
NOW = datetime(2026, 11, 4, 12, 0)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _ids(bind, slug):
    row = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"), {"slug": slug}).first()
    return row[0] if row else None


def upgrade():
    if not {"businesses", "bank_transactions", "bank_connections"} <= _tables():
        return
    bind = op.get_bind()
    parent = _ids(bind, PARENT_SLUG)
    if parent is None:
        return
    mine = _ids(bind, SLUG)
    if mine is None:
        bind.execute(sa.text(
            "INSERT INTO businesses (name, short_name, slug, texas_taxpayer_number, "
            "sos_file_number, franchise_tax_webfile, sales_tax_webfile, sales_tax_frequency, "
            "taxable_share, naics_code, sales_source, admin_url, hub_base_url, hub_secret, "
            "hub_pull_note, notes, is_active, parent_id, created_at, updated_at) "
            "VALUES (:name, :short_name, :slug, '', '', '', '', 'quarterly', 80, '812990', 'manual', "
            "'', '', '', '', :notes, :active, :parent_id, :now, :now)"),
            {"name": "Personal Training", "short_name": "Personal Training", "slug": SLUG,
             "notes": "The personal training work Built by Bean LLC was first formed for. "
                      "Its income is Built by Bean's and is shown under this name.",
             "active": True, "parent_id": parent, "now": NOW})
        mine = _ids(bind, SLUG)
    bind.execute(sa.text(
        "UPDATE bank_transactions SET business_id = :mine "
        "WHERE business_id = :parent AND disposition = 'income' AND description = :kind "
        "AND connection_id IN (SELECT id FROM bank_connections "
        "WHERE business_id = :parent AND provider = 'statement' AND COALESCE(kind, '') != 'personal')"),
        {"mine": mine, "parent": parent, "kind": KIND})


def downgrade():
    if not {"businesses", "bank_transactions"} <= _tables():
        return
    bind = op.get_bind()
    parent, mine = _ids(bind, PARENT_SLUG), _ids(bind, SLUG)
    if mine is None:
        return
    if parent is not None:
        bind.execute(sa.text("UPDATE bank_transactions SET business_id = :parent WHERE business_id = :mine"),
                     {"parent": parent, "mine": mine})
    if "expenses" in _tables() and parent is not None:
        bind.execute(sa.text("UPDATE expenses SET business_id = :parent WHERE business_id = :mine"),
                     {"parent": parent, "mine": mine})
    bind.execute(sa.text("DELETE FROM businesses WHERE id = :mine"), {"mine": mine})
