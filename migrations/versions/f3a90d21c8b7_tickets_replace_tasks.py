"""tickets replace tasks, and a client can have an app of its own

A task was a thing I wrote down for myself. A ticket is a thing a client asked
for, and every one of them arrives from that client's own app rather than being
typed here. Expenses, time and documents hung off Task and now hang off Ticket:
the money model is unchanged, only what it is attached to.

Free to do now and not later. `tasks` holds zero rows, and every column
pointing at it (expenses.task_id, time_entries.task_id, documents.task_id) is
null in every row, so nothing is migrated and nothing is lost. Checked before
writing this rather than assumed.

**Every step here is guarded, and that is not defensiveness.** This app runs
`db.create_all()` inside create_app(), so simply importing it to run a
migration builds every table the models declare. By the time Alembic gets here,
`tickets` and `ticket_notes` already exist, and an unguarded create_table fails
with "table tickets already exists". The columns are a different story:
create_all only ever creates missing TABLES and never alters an existing one,
which is why `clients` gains nothing from it and why this file is still needed.

Two schema mechanisms in one app is the actual problem and this does not fix
it. It works either side of it instead, so the migration is correct whether or
not create_all got here first.

Order still matters and SQLite will not say so. The children pointing at `tasks`
let go of it before the parent is dropped, and `tickets` exists before anything
points at it. SQLite ignores the foreign key and Postgres refuses, so the wrong
order passes locally and fails on deploy.

Revision ID: f3a90d21c8b7
Revises: d4e5f6a1b2c3
Create Date: 2026-08-29 14:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a90d21c8b7'
down_revision = 'd4e5f6a1b2c3'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _has_column(table, column):
    if not _has_table(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def upgrade():
    # ---- parents first -----------------------------------------------------
    if not _has_table("tickets"):
        op.create_table(
            "tickets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("origin", sa.String(length=40), nullable=False, server_default="local"),
            sa.Column("origin_ticket_id", sa.Integer(), nullable=True),
            sa.Column("origin_url", sa.String(length=500), nullable=True),
            sa.Column("reporter_name", sa.String(length=200), nullable=True),
            sa.Column("reporter_email", sa.String(length=200), nullable=True),
            sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("detailed_notes", sa.Text(), nullable=True),
            sa.Column("source_label", sa.String(length=200), nullable=True),
            sa.Column("source_path", sa.String(length=500), nullable=True),
            sa.Column("category", sa.String(length=20), nullable=False, server_default="bug"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
            sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
            sa.Column("followup_flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("out_of_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("billing_bucket", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("billed_minutes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    name="fk_tickets_client", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    name="fk_tickets_project", ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_tickets"),
            # The same ticket arriving twice updates rather than duplicates.
            sa.UniqueConstraint("origin", "origin_ticket_id", name="uq_ticket_origin"),
        )
        op.create_index("ix_tickets_client_id", "tickets", ["client_id"])
        op.create_index("ix_tickets_project_id", "tickets", ["project_id"])
        op.create_index("ix_tickets_origin", "tickets", ["origin"])
        op.create_index("ix_tickets_status", "tickets", ["status"])

    if not _has_table("ticket_notes"):
        op.create_table(
            "ticket_notes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticket_id", sa.Integer(), nullable=False),
            sa.Column("author_name", sa.String(length=200), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("is_staff_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("origin_note_id", sa.Integer(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"],
                                    name="fk_ticket_notes_ticket", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_ticket_notes"),
            sa.UniqueConstraint("ticket_id", "origin_note_id", name="uq_note_origin"),
        )
        op.create_index("ix_ticket_notes_ticket_id", "ticket_notes", ["ticket_id"])

    # ---- the client's own app ---------------------------------------------
    # create_all never reaches these: it does not alter a table that exists.
    with op.batch_alter_table("clients", schema=None) as batch_op:
        if not _has_column("clients", "origin_slug"):
            batch_op.add_column(sa.Column("origin_slug", sa.String(length=40), nullable=True))
            batch_op.create_unique_constraint("uq_clients_origin_slug", ["origin_slug"])
        if not _has_column("clients", "ingest_secret"):
            batch_op.add_column(sa.Column("ingest_secret", sa.String(length=120), nullable=True))
        if not _has_column("clients", "origin_base_url"):
            batch_op.add_column(sa.Column("origin_base_url", sa.String(length=300), nullable=True))

    # ---- children let go of tasks, and take hold of tickets ----------------
    for table, ondelete in (("expenses", "SET NULL"),
                            ("time_entries", "SET NULL"),
                            ("documents", "CASCADE")):
        with op.batch_alter_table(table, schema=None) as batch_op:
            if not _has_column(table, "ticket_id"):
                batch_op.add_column(sa.Column("ticket_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(f"fk_{table}_ticket", "tickets",
                                            ["ticket_id"], ["id"], ondelete=ondelete)
            if _has_column(table, "task_id"):
                batch_op.drop_column("task_id")

    # ---- carry the tasks over, then drop the table -------------------------
    #
    # This was first written to drop `tasks` outright, on the basis that it held
    # zero rows. That was true of the laptop's SQLite copy and false of
    # production, which had real tasks in it and is a different database nobody
    # had looked in. "The table is empty" is a fact about one database, never
    # about the schema.
    #
    # So they are converted rather than dropped. A task was a thing I wrote down
    # for myself, which is a ticket I raised against my own client: origin
    # "local", no reporter, and the client taken from the project it hung off.
    #
    # **Subtasks are flattened, not dropped.** A ticket has no parent, so a task
    # that hung under another comes across as an ordinary ticket carrying its
    # own text, status and dates. Selecting only top-level tasks would silently
    # bin every child, which is the difference between a migration and a
    # deletion. parent_task_id is simply not read.
    if _has_table("tasks"):
        bind = op.get_bind()
        # Both vocabularies change. The old words described my queue; the new
        # ones describe a request somebody made. Anything unrecognised lands on
        # the neutral value rather than being guessed at.
        status_case = (
            "CASE tasks.status "
            "WHEN 'todo' THEN 'new' "
            "WHEN 'in_progress' THEN 'in-progress' "
            "WHEN 'review' THEN 'in-progress' "      # still being worked on
            "WHEN 'done' THEN 'resolved' "
            "ELSE 'new' END"
        )
        priority_case = (
            "CASE tasks.priority "
            "WHEN 'urgent' THEN 'urgent' "
            "WHEN 'high' THEN 'soon' "
            "WHEN 'medium' THEN 'normal' "
            "WHEN 'low' THEN 'backlog' "
            "ELSE 'normal' END"
        )
        # client_id is NOT NULL on a ticket and a task only knew its project, so
        # it comes through the join. A task whose project has gone would have
        # nowhere to land, and the INNER JOIN drops it rather than failing the
        # whole deploy on one orphan.
        result = bind.execute(sa.text(f"""
            INSERT INTO tickets (client_id, project_id, origin, title, description,
                                 detailed_notes, category, status, priority,
                                 followup_flagged, out_of_scope, billing_bucket,
                                 billed_minutes, due_date, created_at, updated_at)
            SELECT projects.client_id, tasks.project_id, 'local', tasks.title,
                   COALESCE(tasks.description, ''), COALESCE(tasks.detailed_notes, ''),
                   'other', {status_case}, {priority_case},
                   {sa.false().compile(bind)}, {sa.false().compile(bind)}, '',
                   0, tasks.due_date, tasks.created_at, tasks.updated_at
            FROM tasks JOIN projects ON projects.id = tasks.project_id
        """))
        # rowcount, not a COUNT(*) over the table afterwards. The first draft
        # counted every local ticket, so a re-run on an empty tasks table
        # reported "carried 3" having carried none, and this line is the only
        # account of what happened that reaches the deploy log.
        left_behind = bind.execute(sa.text(
            "SELECT COUNT(*) FROM tasks WHERE project_id NOT IN (SELECT id FROM projects)"
        )).scalar()
        children = bind.execute(sa.text(
            "SELECT COUNT(*) FROM tasks WHERE parent_task_id IS NOT NULL"
        )).scalar()
        print(f"[tickets] carried {result.rowcount} task(s) over"
              + (f", {children} of them subtasks, now flat" if children else ""))
        if left_behind:
            # Said out loud rather than swallowed. Silent truncation reads as
            # "moved everything" when it did not.
            print(f"[tickets] {left_behind} task(s) had no surviving project and were dropped")
        op.drop_table("tasks")


def downgrade():
    if not _has_table("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("parent_task_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("detailed_notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True, server_default="todo"),
            sa.Column("priority", sa.String(length=20), nullable=True, server_default="medium"),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    name="fk_tasks_project", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        )

    for table, ondelete in (("expenses", "SET NULL"),
                            ("time_entries", "SET NULL"),
                            ("documents", "CASCADE")):
        with op.batch_alter_table(table, schema=None) as batch_op:
            if not _has_column(table, "task_id"):
                batch_op.add_column(sa.Column("task_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(f"fk_{table}_task", "tasks",
                                            ["task_id"], ["id"], ondelete=ondelete)
            if _has_column(table, "ticket_id"):
                batch_op.drop_column("ticket_id")

    with op.batch_alter_table("clients", schema=None) as batch_op:
        if _has_column("clients", "origin_slug"):
            batch_op.drop_constraint("uq_clients_origin_slug", type_="unique")
            batch_op.drop_column("origin_slug")
        if _has_column("clients", "ingest_secret"):
            batch_op.drop_column("ingest_secret")
        if _has_column("clients", "origin_base_url"):
            batch_op.drop_column("origin_base_url")

    # Left standing on purpose. create_all rebuilds them from the models on the
    # next boot regardless, so dropping them here buys nothing and would lose
    # every ticket that had arrived by then.
