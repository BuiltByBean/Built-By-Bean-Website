"""a runbook for GitHub, written from this org's own history

Seventeen repos, eleven of them public, and this one — the board holding
client records and Stripe configuration — among the public ones. That is a
choice, and it works, but only if nothing secret was ever committed. Two
commits in this repo's own history say otherwise, and they are the reason the
traps section leads with git history rather than with access.

Seeded only when the slug is absent, so an edited copy is never overwritten.

Revision ID: d5a3e81f60c2
Revises: c4f7b209ae13
Create Date: 2026-09-01 09:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5a3e81f60c2'
down_revision = 'c4f7b209ae13'
branch_labels = None
depends_on = None


ONE_LINER = (
    "Where the code lives and what deploys from it. The dangerous part is not "
    "access, it is that history keeps what you deleted."
)

CLIENT_ONLY = """\
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

ACCESS_GRANT = """\
**A collaborator invite, or a seat in their organisation.** Settings,
Collaborators, Add people. Write access is enough to work; Admin is only
needed to change branch protection or connect deploys, and it is worth saying
which one you need and why rather than being handed Admin by default.

**For anything automated, a token or a key — never the account.**

    Fine-grained PAT   scoped to named repos, expires, read/write contents
    Deploy key         one repo, read-only unless you say otherwise
    GitHub App         what Railway and the CI providers actually use

Prefer the narrowest that works. A classic token with `repo` scope reads every
private repository the account can see, including the client's other business.

**The gh CLI, once, on this machine.**

    gh auth login
    gh repo list <org> --limit 100

Faster than the web for everything a runbook needs, and it is how you find out
what actually exists rather than what you remember existing.
"""

YOUR_STEPS = """\
**Write .gitignore before the first commit, not after the first mistake.**
`.env`, credential JSON, database files, upload folders, `__pycache__`. The
first commit is the cheapest moment this will ever be fixable.

**Commit an `.env.example` with the keys and no values.** It documents what
the app needs, it survives the repo going public, and it stops the day someone
guesses at variable names from a stack trace.

**Connect the deploy to the repo, not to your laptop.** On Railway that means
attaching the GitHub repo to the service so a push to main deploys. A service
deployed from the CLI works, but nothing afterwards knows where its code came
from — not Railway's dashboard, not anything reading Railway's API, not the
next person.

**Protect main once there is anything worth protecting.** Settings, Branches.
Even alone, requiring a passing check stops a broken deploy that a red CI run
would have caught.

**Add CI early, however small.** A workflow that installs and runs the tests
on every push costs one file and turns "it worked on my machine" into a fact
the repo asserts for itself.
"""

TRAPS = """\
**Deleting a secret does not delete it. This repo proves it.** Two commits
here removed live credentials — a fallback `SECRET_KEY` and hardcoded admin
passwords. Both fixes are correct and both values are still readable by
anybody, because a commit that removes a line is a commit that contains the
line:

    git log -p | grep -i "secret_key"

The repository is public. The fix going forward is not the fix going back. If
a real credential was ever committed to a public repo, treat it as published
and **rotate it** — the only cleanup that works is rewriting history, which
breaks every clone, and it is still a race against whoever already cloned.

**Public is the expensive default.** Eleven of these seventeen repos are
public, including the board that holds client records. That is workable, but
it means every commit is a disclosure decision forever, and it means a default
value written "just for local dev" is a published credential the moment it
lands.

**Untracking is not removing.** `git rm --cached` stops a file changing from
here on. It is already in every earlier commit, and it is still in every clone
and every fork.

**A CLI deploy has no repo behind it.** Railway only knows a service's
repository when the service is connected to GitHub for auto-deploy. Deploy it
by CLI and the API reports no repo at all — not an error, just an empty field,
which is why one project on the apps board had no GitHub button until it was
filled in by hand.

**Private repos are private to your tools too.** `raw.githubusercontent.com`
returns 404 for a private repo without a token, so anything that expects to
fetch an asset straight from the repository quietly fails. Ship the asset, or
authenticate the fetch; do not assume the URL works because it works in your
browser, where you are logged in.

**A fork keeps reading after access is revoked.** Removing a collaborator does
not remove their fork. If somebody left and something sensitive was in there,
revoking is not enough.
"""

VERIFY = """\
**Is it public or private, right now?** Not what you remember choosing.

    gh repo view <org>/<repo> --json visibility,url
    gh repo list <org> --limit 100 --json name,visibility

**Does history contain anything that should not be there?** Search the whole
history, not the working tree:

    git log -p --all | grep -inE "secret|password|api[_-]?key|token"
    git log --diff-filter=A --name-only --pretty=format: --all | sort -u

The second lists every file ever added, including ones deleted long ago.

**Is the deploy really attached to this repo?** In Railway the service should
name the repo and branch. If it is empty, the service is CLI-deployed and
pushing will change nothing, however green the commit looks.

**Did the deploy come from the commit you think?** Compare the SHA the host
reports against the local HEAD. A successful build of the previous commit is
the most convincing wrong answer in this business.

**Is the tree actually clean and pushed?**

    git status --short
    git rev-list --count origin/main..HEAD
"""

FIELDS = {
    "slug": "github",
    "display_name": "GitHub",
    "logo_path": "pm/logos/github.svg",
    "vendor_url": "https://github.com/BuiltByBean",
    "is_active": True,
    "sort_order": 45,
    "one_liner": ONE_LINER,
    "client_only_md": CLIENT_ONLY,
    "access_grant_md": ACCESS_GRANT,
    "your_steps_md": YOUR_STEPS,
    "traps_md": TRAPS,
    "verify_md": VERIFY,
}


def upgrade():
    conn = op.get_bind()
    if "playbooks" not in sa.inspect(conn).get_table_names():
        return
    if conn.execute(sa.text("SELECT 1 FROM playbooks WHERE slug = :s"),
                    {"s": "github"}).first():
        return
    cols = ", ".join(FIELDS)
    vals = ", ".join(f":{k}" for k in FIELDS)
    conn.execute(sa.text(f"INSERT INTO playbooks ({cols}) VALUES ({vals})"), FIELDS)


def downgrade():
    conn = op.get_bind()
    if "playbooks" in sa.inspect(conn).get_table_names():
        conn.execute(sa.text("DELETE FROM playbooks WHERE slug = :s"), {"s": "github"})
