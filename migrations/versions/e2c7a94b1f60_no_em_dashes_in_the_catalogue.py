"""Take the em dashes out of the catalogue text, and the mojibake with them

Catalogue rule "No em dashes, anywhere". Sweeping the repo only fixes the
source; the prose that rides into every build prompt lives in the database,
put there by migrations that have already run, so it needs its own pass.

Two characters, not one.

The first is the em dash itself. The second is what an em dash becomes when
UTF-8 bytes E2 80 94 are read back as cp1252: U+00E2 U+20AC U+201D, which
renders as a-euro-quote and appeared on the Mydoma Studio runbook fourteen
times in one field. The board did not do that. The write path escapes
non-ASCII before it sends, so the text arrived already broken from whichever
session composed it on a Windows box, and the row stored faithfully what it
was given. Repaired here rather than left, because it is unreadable and
because nothing legitimate ever contains that run.

Columns are checked against the schema before being touched, so a table that
has not been created yet, or a column since renamed, is skipped rather than
raising. A migration that cannot run is a missing tidy-up; one that raises is
a site that will not start.

Revision ID: e2c7a94b1f60
Revises: d1b5f83a27c4
"""
from alembic import op
import sqlalchemy as sa


revision = "e2c7a94b1f60"
down_revision = "d1b5f83a27c4"
branch_labels = None
depends_on = None


# Escaped, not typed. A file whose job is to remove this character
# must not be the one place that still carries it: the rule's own
# scanner reads source, and would report this as a violation.
EM = "\u2014"
MOJIBAKE = "\u00e2\u20ac\u201d"
GOOD = "-"

TARGETS = {
    "features": ("name", "summary", "gold_standard_md", "pitfalls_md"),
    "playbooks": ("display_name", "one_liner", "client_only_md",
                  "access_grant_md", "your_steps_md", "traps_md", "verify_md"),
    "playbook_steps": ("title", "detail_md", "client_message_subject",
                       "client_message_md"),
    "products": ("name", "summary", "prompt_intro"),
}


def _rewrite(bind, bad):
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, columns in TARGETS.items():
        if table not in tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column not in present:
                continue
            bind.execute(
                sa.text(
                    "UPDATE %s SET %s = REPLACE(%s, :bad, :good) "
                    "WHERE %s IS NOT NULL AND %s LIKE :like"
                    % (table, column, column, column, column)
                ),
                {"bad": bad, "good": GOOD, "like": "%" + bad + "%"})


def upgrade():
    bind = op.get_bind()
    # Mojibake first. It ENDS in a character that is not the em dash, so the
    # order does not actually matter here, but doing the compound run before
    # the single character is the habit that keeps it safe if either ever
    # shares a prefix with the other.
    _rewrite(bind, MOJIBAKE)
    _rewrite(bind, EM)


def downgrade():
    # Deliberately nothing. Putting an em dash back would reintroduce exactly
    # what the rule forbids, and there is no way to know which hyphens were
    # em dashes before this ran. The repair is one way on purpose.
    pass
