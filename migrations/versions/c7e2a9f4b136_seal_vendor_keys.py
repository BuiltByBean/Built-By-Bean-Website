"""Seal the vendor keys already in the database

Issue #14 (2026-11-05): every vendor secret in `service_providers.credentials_json`
was plain text. secret_box seals new ones as they are saved; this seals the ones
already there, with the key derived from SECRET_KEY (the web service's, which
cost-sync shares). Only the secret fields change; ids and workspaces stay
readable. Downgrade opens them again.

With no SECRET_KEY (a developer's machine without one) it seals nothing and
says so: a plain key still reads, so nothing breaks, and the next save seals it.

Revision ID: c7e2a9f4b136
Revises: b3e8c1f5d742
Create Date: 2026-11-05
"""
import json
import os

import sqlalchemy as sa
from alembic import op

revision = "c7e2a9f4b136"
down_revision = "b3e8c1f5d742"
branch_labels = None
depends_on = None


def _secret():
    try:
        from flask import current_app
        if current_app.config.get("SECRET_KEY"):
            return str(current_app.config["SECRET_KEY"])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("SECRET_KEY", "")


def _rewrite(change):
    import secret_box
    bind = op.get_bind()
    secret = _secret()
    if not secret:
        print("vendor keys: no SECRET_KEY here, nothing sealed or opened")
        return
    done = 0
    for pid, text in bind.execute(sa.text(
            "SELECT id, credentials_json FROM service_providers WHERE credentials_json IS NOT NULL")).all():
        try:
            creds = json.loads(text or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(creds, dict):
            continue
        new = change(creds, secret)
        if new != creds:
            bind.execute(sa.text("UPDATE service_providers SET credentials_json = :c WHERE id = :id"),
                         {"c": json.dumps(new), "id": pid})
            done += 1
    print(f"vendor keys: {done} account(s) rewritten")


def upgrade():
    import secret_box
    _rewrite(secret_box.seal_creds)


def downgrade():
    import secret_box
    _rewrite(secret_box.unseal_creds)
