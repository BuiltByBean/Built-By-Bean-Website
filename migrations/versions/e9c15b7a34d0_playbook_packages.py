"""playbooks become checklists a project can run

A playbook explained a vendor. It did not help on a Tuesday, when the question
is not "how does Stripe work" but "what is the next thing I have to do, and
what do I have to ask Cason for before I can do it".

So: ordered steps per playbook, playbooks applied to a project, and a tick per
step per project. GitHub and Railway are marked default and attach themselves
to every new project, because they are on every build and asking is a question
with one answer.

Steps carry the message to send when the step is somebody else's to do. The
slow steps are always the ones waiting on a client, and they are slow because
composing the ask is a small unpleasant job at the end of a day. Written once
here, it becomes a copy button.

Revision ID: e9c15b7a34d0
Revises: d5a3e81f60c2
Create Date: 2026-09-01 10:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e9c15b7a34d0'
down_revision = 'd5a3e81f60c2'
branch_labels = None
depends_on = None


# (title, detail, channel, subject, message)
GITHUB_STEPS = [
    ("Decide public or private, and write it down",
     "Public is free and fine for a marketing site. It is not fine for "
     "anything that will ever hold a key. Decide now — \"we will make it "
     "private later\" does not work, because history is already published.",
     None, "", ""),
    ("Create the repo in the right place",
     "Whoever creates it owns it. Moving it later is a transfer that breaks "
     "every deploy hook pointed at the old path.",
     None, "", ""),
    ("Write .gitignore before the first commit",
     "`.env`, credential files, database files, upload folders, "
     "`__pycache__`. The first commit is the cheapest moment this is ever "
     "fixable.",
     None, "", ""),
    ("Commit an .env.example with keys and no values",
     "Documents what the app needs and survives the repo going public.",
     None, "", ""),
    ("Ask the client who else already has access",
     "A previous developer's fork, an unrevoked invite, an old deploy key — "
     "all of them still read everything.",
     "email", "Quick access question before we start",
     "Hi {client},\n\nBefore I set the repository up, one housekeeping "
     "question: does anyone else currently have access to the existing code "
     "— a previous developer, an agency, or an old integration?\n\nIf so I "
     "will get their access tidied up as part of the handover, so we start "
     "from a clean slate.\n\nThanks,\nMichael\nBuilt by Bean LLC"),
    ("Connect the repo to the deploy",
     "Attach the GitHub repo to the Railway service so a push to main "
     "deploys. A CLI deploy works but nothing afterwards knows where the code "
     "came from.",
     None, "", ""),
    ("Add CI, however small",
     "A workflow that installs and runs the tests on every push turns \"it "
     "worked on my machine\" into something the repo asserts for itself.",
     None, "", ""),
    ("Protect main",
     "Settings, Branches. Even working alone, requiring a passing check stops "
     "a broken deploy a red run would have caught.",
     None, "", ""),
]

RAILWAY_STEPS = [
    ("Create the project and the service",
     "One Railway project per client build. Name it what the client calls it, "
     "not what the repo is called.",
     None, "", ""),
    ("Attach a volume if anything is written to disk",
     "Container filesystems are wiped on every deploy. Uploads, generated "
     "PDFs, SQLite files and signing keys all need a volume, and finding that "
     "out after a deploy means the data is already gone.",
     None, "", ""),
    ("Set the environment variables",
     "Everything from .env.example, with real values. A missing one usually "
     "shows up as a crash loop rather than a clear message.",
     None, "", ""),
    ("Run migrations on boot, not by hand",
     "Put `flask db upgrade` ahead of the server in the start command so a "
     "deploy cannot serve a schema it has not migrated.",
     None, "", ""),
    ("Ask the client for the domain, and who controls its DNS",
     "The answer decides whether you add the records or wait a week for "
     "somebody else to.",
     "email", "Domain and DNS for your new site",
     "Hi {client},\n\nWe are ready to point your domain at the new build. Two "
     "things I need:\n\n1. The exact domain you want it live on (with or "
     "without www).\n2. Who manages the DNS — if it is a provider like "
     "GoDaddy, Cloudflare or Squarespace, and whether you can add me or would "
     "rather add two records yourself.\n\nIf you can add me, that is the "
     "fastest route and I will handle it end to end.\n\nThanks,\nMichael\n"
     "Built by Bean LLC"),
    ("Add the custom domain and its DNS records",
     "Railway gives the target; the records go on the client's zone. On "
     "Cloudflare these are DNS only, not proxied.",
     None, "", ""),
    ("Confirm the deploy came from the commit you think",
     "Compare the SHA the dashboard reports against local HEAD. A successful "
     "build of the previous commit is the most convincing wrong answer there "
     "is.",
     None, "", ""),
    ("Tell the client it is live, with the URL",
     "", "email", "Your site is live",
     "Hi {client},\n\nYour site is live at {url}.\n\nHave a look when you get "
     "a minute. If anything reads wrong or looks off on your phone, send me a "
     "screenshot and I will sort it.\n\nThanks,\nMichael\nBuilt by Bean LLC"),
]

STRIPE_STEPS = [
    ("Ask the client to create the Stripe account themselves",
     "It is their money and their legal identity. An account you create for "
     "them is an account they cannot fully control, and moving it later means "
     "re-onboarding every customer.",
     "email", "Setting up payments — one thing only you can do",
     "Hi {client},\n\nTo take card payments we need a Stripe account in your "
     "business's name. This one has to be created by you, because Stripe "
     "verifies the business identity and bank details directly with the "
     "owner — I cannot do that part on your behalf, and you would not want me "
     "to.\n\nIt takes about ten minutes at https://dashboard.stripe.com/register\n\n"
     "Have ready:\n- Your legal business name and EIN\n- Business address and "
     "phone\n- The bank account payouts should land in\n\nOnce it is created, "
     "let me know and I will send the next step.\n\nThanks,\nMichael\n"
     "Built by Bean LLC"),
    ("Have them complete identity and bank details",
     "Until this is done the account can take test payments only. Payouts are "
     "blocked and nothing tells you loudly.",
     None, "", ""),
    ("Ask to be invited to the account",
     "Settings, Team, invite as Developer. Never ask for their login.",
     "email", "Invite me to your Stripe account",
     "Hi {client},\n\nNow the account exists, please add me as a team member "
     "so I can wire up payments:\n\n1. In Stripe, go to Settings, then Team "
     "and security\n2. Click 'New member' and invite michaelbean21@gmail.com\n"
     "3. Choose the 'Developer' role\n\nDeveloper lets me build and test the "
     "integration. It does not let me move money or change your bank details "
     "— those stay with you.\n\nThanks,\nMichael\nBuilt by Bean LLC"),
    ("Create restricted API keys, not the secret key",
     "A restricted key is scoped and revocable on its own. The account secret "
     "key is the account.",
     None, "", ""),
    ("Build against test mode first",
     "Test card 4242 4242 4242 4242, any future expiry. Get the whole flow "
     "working before a real card is anywhere near it.",
     None, "", ""),
    ("Set up the webhook and store its signing secret",
     "Without signature verification anyone who finds the URL can tell your "
     "app a payment succeeded.",
     None, "", ""),
    ("Test the failure paths, not just the happy one",
     "Card declined (4000 0000 0000 0002), authentication required "
     "(4000 0025 0000 3155), and a webhook arriving twice. The last one is "
     "the bug that reaches production.",
     None, "", ""),
    ("Switch to live keys and take one real payment",
     "Charge a small real amount to a real card and confirm it lands. Test "
     "mode proves the code; only a live payment proves the account.",
     None, "", ""),
    ("Confirm the first payout reaches their bank",
     "Stripe holds the first payout for several days. Tell them before they "
     "notice and worry.",
     "email", "Payments are live — what to expect on your first payout",
     "Hi {client},\n\nPayments are live and working.\n\nOne thing worth "
     "knowing so it does not surprise you: Stripe holds the first payout for "
     "roughly 7 days while the account settles. After that payouts arrive on "
     "a rolling basis, usually 2 business days behind the payment.\n\nYou can "
     "see every payment and payout at "
     "https://dashboard.stripe.com\n\nThanks,\nMichael\nBuilt by Bean LLC"),
]

SEED = {"github": GITHUB_STEPS, "railway": RAILWAY_STEPS, "stripe": STRIPE_STEPS}
DEFAULTS = ("github", "railway")


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    if "playbooks" not in tables:
        return

    if "is_default" not in {c["name"] for c in insp.get_columns("playbooks")}:
        with op.batch_alter_table("playbooks", schema=None) as batch_op:
            batch_op.add_column(sa.Column("is_default", sa.Boolean(), nullable=False,
                                          server_default=sa.false()))

    if "playbook_steps" not in tables:
        op.create_table(
            "playbook_steps",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("playbook_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("detail_md", sa.Text(), nullable=True),
            sa.Column("client_channel", sa.String(length=10), nullable=True),
            sa.Column("client_message_subject", sa.String(length=200), nullable=True),
            sa.Column("client_message_md", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_playbook_steps"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"],
                                    name="fk_playbook_steps_playbook", ondelete="CASCADE"),
        )
        op.create_index("ix_playbook_steps_playbook_id", "playbook_steps", ["playbook_id"])

    if "project_playbooks" not in tables:
        op.create_table(
            "project_playbooks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("playbook_id", sa.Integer(), nullable=False),
            sa.Column("added_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_project_playbooks"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                    name="fk_project_playbooks_project", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"],
                                    name="fk_project_playbooks_playbook", ondelete="CASCADE"),
            sa.UniqueConstraint("project_id", "playbook_id", name="uq_project_playbook"),
        )
        op.create_index("ix_project_playbooks_project_id", "project_playbooks", ["project_id"])

    if "project_playbook_steps" not in tables:
        op.create_table(
            "project_playbook_steps",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_playbook_id", sa.Integer(), nullable=False),
            sa.Column("playbook_step_id", sa.Integer(), nullable=False),
            sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_project_playbook_steps"),
            sa.ForeignKeyConstraint(["project_playbook_id"], ["project_playbooks.id"],
                                    name="fk_pps_applied", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["playbook_step_id"], ["playbook_steps.id"],
                                    name="fk_pps_step", ondelete="CASCADE"),
            sa.UniqueConstraint("project_playbook_id", "playbook_step_id",
                                name="uq_project_playbook_step"),
        )
        op.create_index("ix_pps_applied", "project_playbook_steps", ["project_playbook_id"])

    # GitHub and Railway run on every build.
    for slug in DEFAULTS:
        conn.execute(sa.text("UPDATE playbooks SET is_default = :t WHERE slug = :s"),
                     {"t": True, "s": slug})

    # Every active project already uses GitHub and Railway, so they arrive
    # with those two attached rather than with an empty tab that looks broken.
    # Archived work is left alone: nothing there is outstanding, and lighting
    # it up with a 0/16 would say otherwise.
    for slug in DEFAULTS:
        conn.execute(sa.text(
            "INSERT INTO project_playbooks (project_id, playbook_id) "
            "SELECT p.id, b.id FROM projects p, playbooks b "
            "WHERE b.slug = :s AND p.status = 'active' "
            "AND NOT EXISTS (SELECT 1 FROM project_playbooks x "
            "WHERE x.project_id = p.id AND x.playbook_id = b.id)"), {"s": slug})

    # Steps are seeded only into a playbook that has none, so an edited
    # checklist is never overwritten by a redeploy.
    for slug, steps in SEED.items():
        row = conn.execute(sa.text("SELECT id FROM playbooks WHERE slug = :s"),
                           {"s": slug}).first()
        if not row:
            continue
        already = conn.execute(
            sa.text("SELECT COUNT(*) FROM playbook_steps WHERE playbook_id = :p"),
            {"p": row[0]}).scalar()
        if already:
            continue
        for i, (title, detail, channel, subject, message) in enumerate(steps):
            conn.execute(sa.text(
                "INSERT INTO playbook_steps (playbook_id, position, title, detail_md, "
                "client_channel, client_message_subject, client_message_md) "
                "VALUES (:p, :pos, :t, :d, :c, :s, :m)"),
                {"p": row[0], "pos": i, "t": title, "d": detail,
                 "c": channel, "s": subject, "m": message})


def downgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    for name in ("project_playbook_steps", "project_playbooks", "playbook_steps"):
        if name in tables:
            op.drop_table(name)
    if "playbooks" in tables:
        if "is_default" in {c["name"] for c in sa.inspect(conn).get_columns("playbooks")}:
            with op.batch_alter_table("playbooks", schema=None) as batch_op:
                batch_op.drop_column("is_default")
