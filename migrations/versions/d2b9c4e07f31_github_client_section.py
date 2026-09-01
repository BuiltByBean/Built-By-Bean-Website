"""the GitHub playbook stops pretending it has a client side

Its checklist lost the one client email in c8e5f1a72b04. The prose still
opened with a section about repo ownership, seat costs and chasing an invite,
which describes an arrangement that has never existed here: every repo is
under the BuiltByBean org, made here, and no client has had a GitHub account
in the loop.

Rewritten rather than emptied. The detail page renders all five section
headings whatever is in them, so an empty one reads "Nothing written here
yet." — an unfinished playbook rather than a deliberate answer. The question
"what does the client have to do for GitHub?" has a real answer, and it is
"nothing, and here is what that costs."

Only rewritten where the section still opens the way it was seeded, so an
edited copy is never overwritten.

Revision ID: d2b9c4e07f31
Revises: c8e5f1a72b04
Create Date: 2026-09-01 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2b9c4e07f31'
down_revision = 'c8e5f1a72b04'
branch_labels = None
depends_on = None


OLD_OPENING = "**Ownership of the repository.**"

OLD = """\
**Ownership of the repository.** Whoever creates it owns it, and moving it
later is a transfer, not a copy: issues, stars and the URL go with it, and
every deploy hook pointed at the old path breaks the moment it lands. Decide
at the start whose account or organisation it lives in, because the tidy
version of this conversation happens before there is anything to move.

**An invitation, and the seat it costs.** Private repos on a paid plan are
billed per seat. Adding you is a line on their bill, and they should know that
before you ask rather than when it arrives.

**Whether it is public or private, and on purpose.** Public is free and fine
for a marketing site. It is not fine for anything that will ever hold a key,
and "we will make it private later" does not work — see the traps. Ask on day
one, and write down the answer.

**Who else already has access.** A previous developer with a fork, a
collaborator invite nobody revoked, an old deploy key. All of them still read
everything, including anything committed by mistake.
"""

NEW = """\
**Nothing, on any build so far.** Every repository lives under the BuiltByBean
organisation, created here, and no client has had a GitHub account in the
loop. That is the arrangement rather than an oversight, and the rest of this
runbook assumes it — which is why the checklist has no message to send.

**What it buys.** No seat on their bill, no invite to chase before work can
start, no access to revoke when the engagement ends, and no repository sitting
in a personal account whose password left with somebody. The deploy is
attached to a repo you control, so a push ships without anybody else being
awake.

**What it costs, and who should hear it once.** They do not hold the code. If
they ever want it — a different developer, an in-house team, a sale — that is
a transfer rather than a copy: issues, stars and the URL move with it, and
every deploy hook pointed at the old path breaks the moment it lands. Say it
early, in whatever the contract says about who owns what. The tidy version of
that conversation happens before there is anything to move.

**The one case that changes this.** A client who already has a repository,
from a previous developer or an agency. Then it is theirs, the old questions
come back — who else still has access, is it public, who is paying for the
seat — and every one of them is answered in the traps, because a repository
you inherit has a history you did not write.
"""


def upgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbooks SET client_only_md = :new "
        "WHERE slug = 'github' AND client_only_md LIKE :guard"),
        {"new": NEW, "guard": OLD_OPENING + "%"})


def downgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbooks SET client_only_md = :old "
        "WHERE slug = 'github' AND client_only_md = :new"),
        {"old": OLD, "new": NEW})
