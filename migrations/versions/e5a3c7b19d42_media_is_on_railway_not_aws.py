"""The media is in a Railway bucket, and this board's AWS is not storage

Michael, 2026-11-02, of the EntertainHQ map: "I'm about 99% certain we do
not use AWS for any file storage." He is right. The seed read AWS_S3_* keys
in EntertainHQ's config as AWS; they are S3-style references to a Railway
bucket (docs/RAILWAY.md: one bucket, media-production, MEDIA_BACKEND=s3).
Built by Bean's AWS keys are the Cost Explorer feed for an old account whose
bucket holds five files nobody reads; uploads live on the volume.

So EntertainHQ's File storage becomes the Railway bucket, on the Railway
runbook, and Built by Bean's AWS row comes off the map. Only a row whose
notes still say it was seeded is touched: one somebody has edited since is
their word, not the seed's.

Revision ID: e5a3c7b19d42
Revises: c7f2a9e41d05
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "e5a3c7b19d42"
down_revision = "c7f2a9e41d05"
branch_labels = None
depends_on = None

SEEDED = "Seeded from the repo on 2026-11-02; confirm it."
ROLE = ("Media in the media-production bucket on Railway: headshots, costume photos, "
        "documents. S3-compatible, not AWS.")


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _aws_row(bind, business_slug):
    """The seeded AWS row on the File storage need for `business_slug`, or None."""
    return bind.execute(sa.text(
        "SELECT s.id FROM business_services s "
        "JOIN businesses b ON b.id = s.business_id "
        "JOIN playbooks p ON p.id = s.playbook_id "
        "WHERE b.slug = :slug AND p.slug = 'aws' AND s.notes = :seeded"),
        {"slug": business_slug, "seeded": SEEDED}).first()


def upgrade():
    if not {"business_services", "businesses", "playbooks"} <= _tables():
        return
    bind = op.get_bind()
    railway = bind.execute(sa.text("SELECT id FROM playbooks WHERE slug = 'railway'")).first()
    row = _aws_row(bind, "entertainhq")
    if row is not None:
        bind.execute(sa.text(
            "UPDATE business_services SET playbook_id = :pb, name = :name, role = :role, "
            "url = '' WHERE id = :id"),
            {"pb": railway[0] if railway else None, "name": "Railway bucket", "role": ROLE,
             "id": row[0]})
    row = _aws_row(bind, "built-by-bean")
    if row is not None:
        bind.execute(sa.text("DELETE FROM business_links WHERE from_service_id = :id OR to_service_id = :id"),
                     {"id": row[0]})
        bind.execute(sa.text("DELETE FROM business_services WHERE id = :id"), {"id": row[0]})


def downgrade():
    # The seed's reading was wrong; nothing puts it back.
    pass
