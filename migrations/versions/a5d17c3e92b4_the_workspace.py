"""The Workspace: tasks (carrying every note across), team chat, and what a
project's repo and domain say about it

Every note becomes a task with the SAME id, its words, its date and its four
links. Open notes go into Backlog and done ones into Done with the day they
were finished, all given to the owner (Michael's account, else the first
CEO) and already seen, because they are his own list and nothing on it is
news. The notes table goes after the copy; the downgrade builds it again and
puts every task back as a note, people and columns aside.

Every create is guarded on the table not existing, because create_all runs
on boot (and inside `flask db upgrade`) and wins the race: the new tables are
usually there, empty, before this runs, which is why the copy is an INSERT
and never a rename.

Revision ID: a5d17c3e92b4
Revises: c6d2e8f41a93
Create Date: 2026-11-04
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "a5d17c3e92b4"
down_revision = "c6d2e8f41a93"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _create_tables():
    have = _tables()
    if "work_tasks" not in have:
        op.create_table(
            "work_tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("stage", sa.String(length=20), nullable=False, server_default="backlog"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("playbook_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_work_tasks"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"],
                                    name="fk_work_tasks_created_by_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    name="fk_work_tasks_client_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    name="fk_work_tasks_project_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    name="fk_work_tasks_product_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"],
                                    name="fk_work_tasks_playbook_id", ondelete="SET NULL"),
        )
        for col in ("stage", "done_at", "due_on", "created_by_id", "client_id",
                    "project_id", "product_id", "playbook_id"):
            op.create_index(f"ix_work_tasks_{col}", "work_tasks", [col])

    if "work_task_people" not in have:
        op.create_table(
            "work_task_people",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("seen_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_work_task_people"),
            sa.ForeignKeyConstraint(["task_id"], ["work_tasks.id"],
                                    name="fk_work_task_people_task_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                    name="fk_work_task_people_user_id", ondelete="CASCADE"),
            sa.UniqueConstraint("task_id", "user_id", name="uq_work_task_people"),
        )
        op.create_index("ix_work_task_people_task_id", "work_task_people", ["task_id"])
        op.create_index("ix_work_task_people_user_id", "work_task_people", ["user_id"])

    if "team_conversations" not in have:
        op.create_table(
            "team_conversations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=True),
            sa.Column("pair_key", sa.String(length=40), nullable=True),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("last_message_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_team_conversations"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"],
                                    name="fk_team_conversations_created_by_id", ondelete="SET NULL"),
            sa.UniqueConstraint("pair_key", name="uq_team_conversations_pair_key"),
        )
        op.create_index("ix_team_conversations_created_by_id", "team_conversations", ["created_by_id"])
        op.create_index("ix_team_conversations_last_message_at", "team_conversations", ["last_message_at"])

    if "team_conversation_members" not in have:
        op.create_table(
            "team_conversation_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("last_read_at", sa.DateTime(), nullable=True),
            sa.Column("joined_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_team_conversation_members"),
            sa.ForeignKeyConstraint(["conversation_id"], ["team_conversations.id"],
                                    name="fk_team_conversation_members_conversation_id",
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                    name="fk_team_conversation_members_user_id", ondelete="CASCADE"),
            sa.UniqueConstraint("conversation_id", "user_id", name="uq_team_conversation_members"),
        )
        op.create_index("ix_team_conversation_members_conversation_id",
                        "team_conversation_members", ["conversation_id"])
        op.create_index("ix_team_conversation_members_user_id",
                        "team_conversation_members", ["user_id"])

    if "team_messages" not in have:
        op.create_table(
            "team_messages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("author_id", sa.Integer(), nullable=True),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_team_messages"),
            sa.ForeignKeyConstraint(["conversation_id"], ["team_conversations.id"],
                                    name="fk_team_messages_conversation_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["author_id"], ["users.id"],
                                    name="fk_team_messages_author_id", ondelete="SET NULL"),
        )
        op.create_index("ix_team_messages_conversation_id", "team_messages", ["conversation_id"])
        op.create_index("ix_team_messages_author_id", "team_messages", ["author_id"])
        op.create_index("ix_team_messages_created_at", "team_messages", ["created_at"])

    if "team_message_links" not in have:
        op.create_table(
            "team_message_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("message_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("record_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_team_message_links"),
            sa.ForeignKeyConstraint(["message_id"], ["team_messages.id"],
                                    name="fk_team_message_links_message_id", ondelete="CASCADE"),
        )
        op.create_index("ix_team_message_links_message_id", "team_message_links", ["message_id"])
        op.create_index("ix_team_message_links_kind_record", "team_message_links",
                        ["kind", "record_id"])


def _owner_id(bind):
    """Michael's account: `Mbean` (CLAUDE.md, Users), else the first CEO."""
    row = bind.execute(sa.text(
        "SELECT id FROM users WHERE lower(username) = 'mbean' ORDER BY id")).first()
    if row:
        return row[0]
    row = bind.execute(sa.text(
        "SELECT id FROM users WHERE role IN ('ceo', 'owner', 'admin') ORDER BY id")).first()
    return row[0] if row else None


def _carry_notes_across():
    bind = op.get_bind()
    if "notes" not in _tables():
        return
    owner = _owner_id(bind)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    taken = {r[0] for r in bind.execute(sa.text("SELECT id FROM work_tasks"))}
    notes = bind.execute(sa.text(
        "SELECT id, title, body, done_at, due_on, client_id, project_id, product_id, "
        "playbook_id, created_at, updated_at FROM notes ORDER BY id")).fetchall()

    # Each column in the order the Notes page showed it: dated first and
    # soonest first, undated newest first.
    def order(n):
        return (n.due_on is None, str(n.due_on or ""), -n.id)

    position = {"backlog": 0, "done": 0}
    for n in sorted(notes, key=order):
        if n.id in taken:
            continue
        stage = "done" if n.done_at else "backlog"
        bind.execute(sa.text(
            "INSERT INTO work_tasks (id, title, body, stage, position, done_at, due_on, "
            "created_by_id, client_id, project_id, product_id, playbook_id, created_at, updated_at) "
            "VALUES (:id, :title, :body, :stage, :position, :done_at, :due_on, :owner, "
            ":client_id, :project_id, :product_id, :playbook_id, :created_at, :updated_at)"),
            {"id": n.id, "title": n.title, "body": n.body or "", "stage": stage,
             "position": position[stage], "done_at": n.done_at, "due_on": n.due_on,
             "owner": owner, "client_id": n.client_id, "project_id": n.project_id,
             "product_id": n.product_id, "playbook_id": n.playbook_id,
             "created_at": n.created_at or now, "updated_at": n.updated_at or now})
        position[stage] += 1
        if owner:
            bind.execute(sa.text(
                "INSERT INTO work_task_people (task_id, user_id, seen_at, created_at) "
                "VALUES (:t, :u, :now, :now)"), {"t": n.id, "u": owner, "now": now})

    # Ids were written by hand, so Postgres's counter has to be told where
    # they got to or the first new task collides with note one.
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('work_tasks', 'id'), "
            "COALESCE((SELECT MAX(id) FROM work_tasks), 0) + 1, false)"))
    op.drop_table("notes")


def upgrade():
    _create_tables()
    have = _columns("projects")
    with op.batch_alter_table("projects") as batch:
        if "build_started_on" not in have:
            batch.add_column(sa.Column("build_started_on", sa.Date(), nullable=True))
        if "go_live_source" not in have:
            batch.add_column(sa.Column("go_live_source", sa.String(length=200), nullable=True))
    _carry_notes_across()


def downgrade():
    bind = op.get_bind()
    if "notes" not in _tables():
        op.create_table(
            "notes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("due_on", sa.Date(), nullable=True),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("playbook_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_notes"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    name="fk_notes_client_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    name="fk_notes_project_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    name="fk_notes_product_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"],
                                    name="fk_notes_playbook_id", ondelete="SET NULL"),
        )
        for col in ("done_at", "due_on", "client_id", "project_id", "product_id", "playbook_id"):
            op.create_index(f"ix_notes_{col}", "notes", [col])

    if "work_tasks" in _tables():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        taken = {r[0] for r in bind.execute(sa.text("SELECT id FROM notes"))}
        for t in bind.execute(sa.text(
                "SELECT id, title, body, stage, done_at, due_on, client_id, project_id, "
                "product_id, playbook_id, created_at, updated_at FROM work_tasks ORDER BY id")).fetchall():
            if t.id in taken:
                continue
            done_at = (t.done_at or t.updated_at or now) if t.stage == "done" else None
            bind.execute(sa.text(
                "INSERT INTO notes (id, title, body, done_at, due_on, client_id, project_id, "
                "product_id, playbook_id, created_at, updated_at) VALUES (:id, :title, :body, "
                ":done_at, :due_on, :client_id, :project_id, :product_id, :playbook_id, "
                ":created_at, :updated_at)"),
                {"id": t.id, "title": t.title, "body": t.body or "", "done_at": done_at,
                 "due_on": t.due_on, "client_id": t.client_id, "project_id": t.project_id,
                 "product_id": t.product_id, "playbook_id": t.playbook_id,
                 "created_at": t.created_at, "updated_at": t.updated_at})
        if bind.dialect.name == "postgresql":
            bind.execute(sa.text(
                "SELECT setval(pg_get_serial_sequence('notes', 'id'), "
                "COALESCE((SELECT MAX(id) FROM notes), 0) + 1, false)"))

    # Children before parents.
    for table in ("team_message_links", "team_messages", "team_conversation_members",
                  "team_conversations", "work_task_people", "work_tasks"):
        if table in _tables():
            op.drop_table(table)

    have = _columns("projects")
    with op.batch_alter_table("projects") as batch:
        if "go_live_source" in have:
            batch.drop_column("go_live_source")
        if "build_started_on" in have:
            batch.drop_column("build_started_on")
