"""The Legal library: the laws behind each product's decisions, with proof copies

Michael, 2026-11-07: legal runs the way Best Practices does but kept apart
from it. Five tables (models.LegalEntry, LegalSource, LegalEntrySource,
LegalTouch, LegalCheck), each create guarded on the table not existing because
create_all runs on boot and wins the race. Children are dropped before parents.

Revision ID: a7c2e9d14b58
Revises: f1d3b5a7c962
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c2e9d14b58"
down_revision = "f1d3b5a7c962"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _tables()
    if "legal_entries" not in have:
        op.create_table(
            "legal_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("product", sa.String(80), nullable=False, server_default=""),
            sa.Column("topic", sa.String(60), nullable=False, server_default=""),
            sa.Column("jurisdiction", sa.String(120), nullable=False, server_default=""),
            sa.Column("laws_md", sa.Text(), nullable=True),
            sa.Column("requires_md", sa.Text(), nullable=True),
            sa.Column("decision_md", sa.Text(), nullable=True),
            sa.Column("recorded_in_md", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="watch"),
            sa.Column("notes_md", sa.Text(), nullable=True),
            sa.Column("lawyer_question", sa.Text(), nullable=True),
            sa.Column("issues", sa.String(300), nullable=True),
            sa.Column("filed_by", sa.String(120), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("check_result", sa.String(16), nullable=False, server_default="never"),
            sa.UniqueConstraint("slug", name="uq_legal_entries_slug"),
        )
        op.create_index("ix_legal_entries_product", "legal_entries", ["product"])
        op.create_index("ix_legal_entries_topic", "legal_entries", ["topic"])
        op.create_index("ix_legal_entries_status", "legal_entries", ["status"])
    if "legal_sources" not in have:
        op.create_table(
            "legal_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(120), nullable=False),
            sa.Column("title", sa.String(400), nullable=False, server_default=""),
            sa.Column("site", sa.String(200), nullable=True),
            sa.Column("url", sa.String(700), nullable=False, server_default=""),
            sa.Column("pdf_url", sa.String(700), nullable=True),
            sa.Column("kind", sa.String(20), nullable=True),
            sa.Column("jurisdiction", sa.String(120), nullable=True),
            sa.Column("fetch_how", sa.String(12), nullable=False, server_default="script"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("repo_copy", sa.String(300), nullable=True),
            sa.Column("repo_sha256", sa.String(64), nullable=True),
            sa.Column("repo_substance", sa.String(64), nullable=True),
            sa.Column("repo_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("repo_bytes", sa.Integer(), nullable=True),
            sa.Column("content_type", sa.String(80), nullable=True),
            sa.Column("copy_file", sa.String(160), nullable=True),
            sa.Column("board_sha256", sa.String(64), nullable=True),
            sa.Column("board_substance", sa.String(64), nullable=True),
            sa.Column("board_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("board_bytes", sa.Integer(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("last_check", sa.String(16), nullable=False, server_default="never"),
            sa.Column("live_substance", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("key", name="uq_legal_sources_key"),
        )
    if "legal_entry_sources" not in have:
        op.create_table(
            "legal_entry_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("citation", sa.String(400), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["entry_id"], ["legal_entries.id"], ondelete="CASCADE",
                                    name="fk_legal_entry_sources_entry_id"),
            sa.ForeignKeyConstraint(["source_id"], ["legal_sources.id"], ondelete="CASCADE",
                                    name="fk_legal_entry_sources_source_id"),
            sa.UniqueConstraint("entry_id", "source_id", name="uq_legal_entry_sources"),
        )
        op.create_index("ix_legal_entry_sources_entry_id", "legal_entry_sources", ["entry_id"])
        op.create_index("ix_legal_entry_sources_source_id", "legal_entry_sources", ["source_id"])
    if "legal_touches" not in have:
        op.create_table(
            "legal_touches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("app_id", sa.Integer(), nullable=True),
            sa.Column("app_name", sa.String(160), nullable=False, server_default=""),
            sa.Column("functions_json", sa.Text(), nullable=True),
            sa.Column("routes_json", sa.Text(), nullable=True),
            sa.Column("note", sa.String(400), nullable=True),
            sa.ForeignKeyConstraint(["entry_id"], ["legal_entries.id"], ondelete="CASCADE",
                                    name="fk_legal_touches_entry_id"),
            sa.ForeignKeyConstraint(["app_id"], ["app_links.id"], ondelete="SET NULL",
                                    name="fk_legal_touches_app_id"),
        )
        op.create_index("ix_legal_touches_entry_id", "legal_touches", ["entry_id"])
        op.create_index("ix_legal_touches_app_id", "legal_touches", ["app_id"])
    if "legal_checks" not in have:
        op.create_table(
            "legal_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("by", sa.String(120), nullable=True),
            sa.Column("status", sa.String(12), nullable=False, server_default="running"),
            sa.Column("checked", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("changed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unreachable", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("by_hand", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detail_json", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
        )


def downgrade():
    have = _tables()
    for name in ("legal_checks", "legal_touches", "legal_entry_sources", "legal_sources", "legal_entries"):
        if name in have:
            op.drop_table(name)
