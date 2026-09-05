"""Leads, from the public record

Every business in the Paris trade area, what the state publishes about it,
who to ask for, and one row per attempt to reach them. Three tables:
the business, the people at it, and the attempts.

Revision ID: b2c4e6a8f0d1
Revises: f1a3c5e7b9d2
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c4e6a8f0d1"
down_revision = "f1a3c5e7b9d2"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    # create_all runs on every boot and wins the race whenever the app is
    # opened against this database before the migration ships, so each table
    # is created only if nothing has made it already.
    existing = _tables()

    if "leads" not in existing:
        op.create_table(
            "leads",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("legal_name", sa.String(length=200), nullable=True),
            sa.Column("owner_name", sa.String(length=160), nullable=True),
            sa.Column("address", sa.String(length=240), nullable=True),
            sa.Column("city", sa.String(length=80), nullable=True),
            sa.Column("state", sa.String(length=10), nullable=True),
            sa.Column("zip_code", sa.String(length=12), nullable=True),
            sa.Column("county", sa.String(length=60), nullable=True),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("lon", sa.Float(), nullable=True),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("email", sa.String(length=200), nullable=True),
            sa.Column("website", sa.String(length=300), nullable=True),
            sa.Column("industry", sa.String(length=120), nullable=True),
            sa.Column("naics", sa.String(length=10), nullable=True),
            sa.Column("entity_type", sa.String(length=60), nullable=True),
            sa.Column("started_on", sa.Date(), nullable=True),
            sa.Column("locations", sa.Integer(), nullable=True),
            sa.Column("employees", sa.Integer(), nullable=True),
            sa.Column("revenue", sa.Float(), nullable=True),
            sa.Column("taxpayer_number", sa.String(length=40), nullable=True),
            sa.Column("osm_ref", sa.String(length=40), nullable=True),
            sa.Column("npi", sa.String(length=20), nullable=True),
            sa.Column("sources", sa.String(length=200), nullable=True),
            sa.Column("dedupe_key", sa.String(length=240), nullable=False),
            sa.Column("stage", sa.String(length=30), nullable=True),
            sa.Column("stage_changed_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("converted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_leads"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    name="fk_leads_client_id_clients",
                                    ondelete="SET NULL"),
            sa.UniqueConstraint("dedupe_key", name="uq_leads_dedupe_key"),
        )
        op.create_index("ix_leads_name", "leads", ["name"])
        op.create_index("ix_leads_city", "leads", ["city"])
        op.create_index("ix_leads_stage", "leads", ["stage"])
        op.create_index("ix_leads_taxpayer_number", "leads", ["taxpayer_number"])
        op.create_index("ix_leads_client_id", "leads", ["client_id"])

    if "lead_people" not in existing:
        op.create_table(
            "lead_people",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("role", sa.String(length=120), nullable=True),
            sa.Column("email", sa.String(length=200), nullable=True),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("source", sa.String(length=60), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_lead_people"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"],
                                    name="fk_lead_people_lead_id_leads",
                                    ondelete="CASCADE"),
        )
        op.create_index("ix_lead_people_lead_id", "lead_people", ["lead_id"])

    if "lead_touches" not in existing:
        op.create_table(
            "lead_touches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("channel", sa.String(length=20), nullable=False,
                      server_default="phone"),
            sa.Column("outcome", sa.String(length=20), nullable=False,
                      server_default="no_answer"),
            sa.Column("went", sa.String(length=10), nullable=True),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_lead_touches"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"],
                                    name="fk_lead_touches_lead_id_leads",
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                    name="fk_lead_touches_user_id_users",
                                    ondelete="SET NULL"),
        )
        op.create_index("ix_lead_touches_lead_id", "lead_touches", ["lead_id"])
        op.create_index("ix_lead_touches_user_id", "lead_touches", ["user_id"])


def downgrade():
    # Children before parents.
    existing = _tables()
    if "lead_touches" in existing:
        op.drop_table("lead_touches")
    if "lead_people" in existing:
        op.drop_table("lead_people")
    if "leads" in existing:
        op.drop_table("leads")
