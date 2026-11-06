"""Built by Bean's own LegalZoom account, on the evidence of its 2024 order

Issue #18, 2026-11-06. LegalZoom formed both LLCs (Michael: "I have two llc's
with legal zoom"). EntertainHQ's order ($301.00, 2026-10-03) is in its books;
Built by Bean's ($301.00, order 80675586, 2024-01-17, "You're now official!
Congrats on forming Built by Bean LLC") is older than the books' first bank
line and was found in the receipt mailbox (/books/mail-search). The Vendors
page keeps an account only on evidence, so this account carries that order as
its evidence (`discovered_from` "mail: ..."), not in use, and the nightly
books pass leaves it.

Downgrade takes the account this made off, or puts back the note of one that
was already there.

Revision ID: e8b4c2d6a913
Revises: d5a8e3c1f927
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "e8b4c2d6a913"
down_revision = "d5a8e3c1f927"
branch_labels = None
depends_on = None

EVIDENCE = "mail: order 80675586, $301.00 on 2024-01-17, formed Built by Bean LLC"


def _cols(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns("service_providers")}


def upgrade():
    bind = op.get_bind()
    if "vendor" not in _cols(bind):
        return
    row = bind.execute(sa.text(
        "SELECT id, discovered_from FROM service_providers WHERE lower(coalesce(vendor, display_name)) = 'legalzoom' "
        "AND account_client_id IS NULL AND account_business_id IS NULL ORDER BY id LIMIT 1")).first()
    if row is not None:
        bind.execute(sa.text("UPDATE service_providers SET discovered_from = :e, is_active = :f WHERE id = :id"),
                     {"e": EVIDENCE, "f": False, "id": row[0]})
        print(f"LegalZoom: account {row[0]} keeps its 2024 order as evidence (was {row[1]!r})")
    else:
        bind.execute(sa.text(
            "INSERT INTO service_providers (name, display_name, vendor, is_active, credentials_json, discovered_from) "
            "VALUES ('bank', 'LegalZoom', 'LegalZoom', :f, '{}', :e)"), {"f": False, "e": EVIDENCE})
        print("LegalZoom: Built by Bean's account made from its 2024 order")


def downgrade():
    bind = op.get_bind()
    if "vendor" not in _cols(bind):
        return
    bind.execute(sa.text("DELETE FROM service_providers WHERE discovered_from = :e AND name = 'bank' "
                         "AND id NOT IN (SELECT provider_id FROM service_cost_entries)"), {"e": EVIDENCE})
