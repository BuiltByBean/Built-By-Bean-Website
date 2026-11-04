"""Converted leads take their client's stage

A converted lead was pinned at In conversation for good while its client moved
on. From now on a flush keeps the two in step
(models._converted_lead_follows_its_client); this brings the leads already
converted up to where their clients are. No schema change.

Revision ID: c6d2e8a41f97
Revises: b4e9c2a7d153
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa


revision = "c6d2e8a41f97"
down_revision = "b4e9c2a7d153"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "UPDATE leads SET stage = (SELECT clients.stage FROM clients "
        "WHERE clients.id = leads.client_id) "
        "WHERE client_id IS NOT NULL AND EXISTS "
        "(SELECT 1 FROM clients WHERE clients.id = leads.client_id "
        "AND clients.stage IS NOT NULL)"))


def downgrade():
    # The pinned stage was a fault, not a fact worth restoring.
    pass
