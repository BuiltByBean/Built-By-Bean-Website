"""Logos for the playbooks that had none, or the wrong one

Issue #25, 2026-11-06. Eleven services on the catalog showed a letter where a
logo belonged, and Signadoc showed GitHub's mark (its icon had been fetched
off a GitHub address). The files ship with the site under
static/images/services; this points each playbook at its file, only where
`logo_path` is empty, except Signadoc, whose fetched icon is the wrong one and
whose logo_path was empty. The downgrade clears exactly the paths it set.

Revision ID: b2d4f6a8c013
Revises: a9c3e5f7b204
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "b2d4f6a8c013"
down_revision = "a9c3e5f7b204"
branch_labels = None
depends_on = None

FILES = {
    "youtube-api": "images/services/youtube.svg",
    "quickbooks-online": "images/services/quickbooks.svg",
    "firebase": "images/services/firebase.svg",
    "apns": "images/services/apple.svg",
    "gmail-smtp": "images/services/gmail.svg",
    "llm-apis": "images/services/openai.svg",
    "mydoma-studio": "images/services/mydoma.png",
    "esv-api": "images/services/esv.png",
    "u-s-congress-public-data": "images/services/congress.png",
    "pwned-passwords": "images/services/pwned.png",
    "signadoc": "images/services/signadoc.svg",
}


def upgrade():
    bind = op.get_bind()
    if "playbooks" not in sa.inspect(bind).get_table_names():
        return
    for slug, path in FILES.items():
        bind.execute(sa.text(
            "UPDATE playbooks SET logo_path = :p WHERE slug = :s "
            "AND (logo_path IS NULL OR logo_path = '')"), {"p": path, "s": slug})


def downgrade():
    bind = op.get_bind()
    if "playbooks" not in sa.inspect(bind).get_table_names():
        return
    for slug, path in FILES.items():
        bind.execute(sa.text("UPDATE playbooks SET logo_path = '' WHERE slug = :s AND logo_path = :p"),
                     {"p": path, "s": slug})
