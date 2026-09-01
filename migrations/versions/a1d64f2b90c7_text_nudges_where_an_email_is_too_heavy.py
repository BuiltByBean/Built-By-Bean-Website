"""text nudges on the three steps where an email is the wrong shape

Every client message so far is an email, because every one of them asks for
something structured — details, access, a decision. These three are not asks.
They are a chase and two status updates, and an email that says "any luck with
the bank details?" is a heavier object than the question deserves; it sits in
an inbox looking like it needs a considered reply, which is exactly why it does
not get one.

Written onto steps that already exist, and only where the step still has no
message, so an edited checklist is never overwritten.

Revision ID: a1d64f2b90c7
Revises: f7a2c93b16de
Create Date: 2026-09-01 10:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1d64f2b90c7'
down_revision = 'f7a2c93b16de'
branch_labels = None
depends_on = None


# (playbook slug, step position, channel, message)
NUDGES = [
    ("stripe", 1, "text",
     "Hi {client}, quick one — Stripe still needs your ID and bank details "
     "before it will let payments through. It is about five minutes in the "
     "dashboard under 'Complete your profile'. Until it is done the account "
     "can only take test payments, so it is the one thing holding this up. "
     "Shout if anything on the form is unclear. — Michael"),

    ("twilio", 6, "text",
     "Hi {client}, the carrier registration for {project} went in today. "
     "Approval usually takes 1-2 weeks and it is entirely on their side, so "
     "there is nothing either of us can do to speed it up. I will let you "
     "know the moment it clears. — Michael"),

    ("cloudflare", 1, "text",
     "Hi {client}, chasing the Cloudflare invite when you get a minute — I "
     "need to be on the account to check two settings that can silently block "
     "the site from being checked properly. It is Manage Account, then "
     "Members, then invite michaelbean21@gmail.com. — Michael"),
]


def upgrade():
    conn = op.get_bind()
    if "playbook_steps" not in set(sa.inspect(conn).get_table_names()):
        return
    for slug, position, channel, message in NUDGES:
        conn.execute(sa.text(
            "UPDATE playbook_steps SET client_channel = :c, client_message_md = :m "
            "WHERE position = :pos "
            "AND playbook_id IN (SELECT id FROM playbooks WHERE slug = :s) "
            "AND (client_message_md IS NULL OR client_message_md = '')"),
            {"c": channel, "m": message, "pos": position, "s": slug})


def downgrade():
    conn = op.get_bind()
    if "playbook_steps" not in set(sa.inspect(conn).get_table_names()):
        return
    for slug, position, channel, message in NUDGES:
        conn.execute(sa.text(
            "UPDATE playbook_steps SET client_channel = NULL, client_message_md = '' "
            "WHERE position = :pos "
            "AND playbook_id IN (SELECT id FROM playbooks WHERE slug = :s) "
            "AND client_message_md = :m"),
            {"pos": position, "s": slug, "m": message})
