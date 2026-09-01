"""GitHub has no client side

The one client message in the GitHub checklist asked the client who else had
access to the existing code. That question assumes a repo the client owns and
somebody worked on before you, which is not how any of this runs: every repo
lives under the BuiltByBean org, created here, and no client has ever had a
GitHub account in the loop.

So the step stays and the email goes. What it asks is still worth asking — a
fork, a stale collaborator or an old deploy key all keep reading after you stop
thinking about them — but it is a thing to go and check, not a thing to ask
somebody. And unlike the email, checking it produces an answer the same day.

Rewritten only where the step still carries the seeded title, so an edited copy
is never overwritten.

Revision ID: c8e5f1a72b04
Revises: a1d64f2b90c7
Create Date: 2026-09-01 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8e5f1a72b04'
down_revision = 'a1d64f2b90c7'
branch_labels = None
depends_on = None


OLD_TITLE = "Ask the client who else already has access"
OLD_DETAIL = ("A previous developer's fork, an unrevoked invite, an old deploy key — "
              "all of them still read everything.")
OLD_SUBJECT = "Quick access question before we start"
OLD_MESSAGE = (
    "Hi {client},\n\nBefore I set the repository up, one housekeeping "
    "question: does anyone else currently have access to the existing code "
    "— a previous developer, an agency, or an old integration?\n\nIf so I "
    "will get their access tidied up as part of the handover, so we start "
    "from a clean slate.\n\nThanks,\nMichael\nBuilt by Bean LLC")

NEW_TITLE = "Check who else can already read it"
NEW_DETAIL = (
    "Nobody outside the org should, and the ways they quietly can are a fork, "
    "a collaborator nobody revoked, a deploy key, or a pending invite. All four "
    "survive you forgetting about them, and a fork keeps reading after access "
    "is taken away.\n\n"
    "```\n"
    "gh api repos/<org>/<repo>/forks --jq 'length'\n"
    "gh api repos/<org>/<repo>/collaborators --jq '[.[].login]'\n"
    "gh api repos/<org>/<repo>/keys --jq '[.[].title]'\n"
    "gh api repos/<org>/<repo>/invitations --jq '[.[].invitee.login]'\n"
    "```\n\n"
    "If something comes back that should not be there, and the repo has ever "
    "held a credential, revoking is not enough — see the traps."
)


def upgrade():
    conn = op.get_bind()
    if "playbook_steps" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbook_steps SET title = :nt, detail_md = :nd, "
        "client_channel = NULL, client_message_subject = '', client_message_md = '' "
        "WHERE title = :ot "
        "AND playbook_id IN (SELECT id FROM playbooks WHERE slug = 'github')"),
        {"nt": NEW_TITLE, "nd": NEW_DETAIL, "ot": OLD_TITLE})


def downgrade():
    conn = op.get_bind()
    if "playbook_steps" not in set(sa.inspect(conn).get_table_names()):
        return
    # Puts the email back too. A downgrade that restored the old title and left
    # the step silent would be a third state that never shipped.
    conn.execute(sa.text(
        "UPDATE playbook_steps SET title = :ot, detail_md = :od, "
        "client_channel = 'email', client_message_subject = :os, "
        "client_message_md = :om "
        "WHERE title = :nt "
        "AND playbook_id IN (SELECT id FROM playbooks WHERE slug = 'github')"),
        {"ot": OLD_TITLE, "od": OLD_DETAIL, "os": OLD_SUBJECT,
         "om": OLD_MESSAGE, "nt": NEW_TITLE})
