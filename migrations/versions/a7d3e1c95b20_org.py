"""Org: every business's people, chart, departments and responsibilities

Michael, 2026-11-04: Team becomes Org, one tab per business, and the board is
the one store EntertainHQ's admin reads and saves through the hub. Four tables
for the org, one for what the board knows about it, and `business_owners`
learns which person each owner is.

No rows are written here. EntertainHQ's org comes over through the door
(/api/hub/org/import or /api/guidance/org/import), never from a file in this
public repo.

Every create is guarded on the table or column not existing, because
create_all runs on boot and wins the race. Children drop before parents.

Revision ID: a7d3e1c95b20
Revises: f2a7c9d41e63
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "a7d3e1c95b20"
down_revision = "f2a7c9d41e63"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index(table, name, cols):
    if name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, cols)


def upgrade():
    have = _tables()
    if "org_people" not in have:
        op.create_table(
            "org_people",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_org_people_business_id"), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("title", sa.String(120), nullable=True),
            sa.Column("email", sa.String(200), nullable=True),
            sa.Column("phone", sa.String(40), nullable=True),
            sa.Column("supervisor_id", sa.Integer(), sa.ForeignKey(
                "org_people.id", ondelete="SET NULL", name="fk_org_people_supervisor_id"), nullable=True),
            sa.Column("app_ref", sa.String(60), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("business_id", "app_ref", name="uq_org_people_business_app_ref"),
        )
    _index("org_people", "ix_org_people_business_id", ["business_id"])
    _index("org_people", "ix_org_people_supervisor_id", ["supervisor_id"])

    if "org_departments" not in have:
        op.create_table(
            "org_departments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_org_departments_business_id"), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("tone", sa.String(12), nullable=False, server_default="gold"),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("app_ref", sa.String(60), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.UniqueConstraint("business_id", "app_ref", name="uq_org_departments_business_app_ref"),
        )
    _index("org_departments", "ix_org_departments_business_id", ["business_id"])

    if "org_person_depts" not in have:
        op.create_table(
            "org_person_depts",
            sa.Column("person_id", sa.Integer(), sa.ForeignKey(
                "org_people.id", ondelete="CASCADE", name="fk_org_person_depts_person_id"), primary_key=True),
            sa.Column("dept_id", sa.Integer(), sa.ForeignKey(
                "org_departments.id", ondelete="CASCADE", name="fk_org_person_depts_dept_id"), primary_key=True),
        )
    _index("org_person_depts", "ix_org_person_depts_dept_id", ["dept_id"])

    if "org_responsibilities" not in have:
        op.create_table(
            "org_responsibilities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_org_responsibilities_business_id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("owner_id", sa.Integer(), sa.ForeignKey(
                "org_people.id", ondelete="SET NULL", name="fk_org_responsibilities_owner_id"), nullable=True),
            sa.Column("dept_id", sa.Integer(), sa.ForeignKey(
                "org_departments.id", ondelete="SET NULL", name="fk_org_responsibilities_dept_id"), nullable=True),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(200), nullable=True),
            sa.Column("app_ref", sa.String(60), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("business_id", "app_ref", name="uq_org_responsibilities_business_app_ref"),
        )
    _index("org_responsibilities", "ix_org_responsibilities_business_id", ["business_id"])
    _index("org_responsibilities", "ix_org_responsibilities_owner_id", ["owner_id"])
    _index("org_responsibilities", "ix_org_responsibilities_dept_id", ["dept_id"])

    if "org_state" not in have:
        op.create_table(
            "org_state",
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_org_state_business_id"), primary_key=True),
            sa.Column("app_logins_json", sa.Text(), nullable=True),
            sa.Column("reported_at", sa.DateTime(), nullable=True),
            sa.Column("imported_at", sa.DateTime(), nullable=True),
            sa.Column("edited_at", sa.DateTime(), nullable=True),
        )

    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business_owners")}
    if "person_id" not in cols:
        with op.batch_alter_table("business_owners") as batch:
            batch.add_column(sa.Column("person_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_business_owners_person_id", "org_people",
                                     ["person_id"], ["id"], ondelete="SET NULL")
    _index("business_owners", "ix_business_owners_person_id", ["person_id"])


def downgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business_owners")}
    if "person_id" in cols:
        if "ix_business_owners_person_id" in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("business_owners")}:
            op.drop_index("ix_business_owners_person_id", table_name="business_owners")
        with op.batch_alter_table("business_owners") as batch:
            batch.drop_constraint("fk_business_owners_person_id", type_="foreignkey")
            batch.drop_column("person_id")
    have = _tables()
    for table in ("org_state", "org_responsibilities", "org_person_depts", "org_departments", "org_people"):
        if table in have:
            op.drop_table(table)
