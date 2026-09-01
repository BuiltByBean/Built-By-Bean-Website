"""a tile links to the app, its Railway service and its repo

One tile, three places you actually go: the running app, the deploy that
serves it, and the code behind it. Typing those two URLs for every app would
be busywork, so they are filled in from what Railway already knows — it holds
the project and service ids, and the GitHub repo each service deploys from.

Only filled where the column is empty, so nothing typed by hand is
overwritten. Chop Builder has no repo attached in Railway, so it gets a
Railway link and no GitHub one, and its tile simply shows two buttons.

Revision ID: f3a81b0c5e29
Revises: e7c2a9f14d38
Create Date: 2026-09-01 07:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a81b0c5e29'
down_revision = 'e7c2a9f14d38'
branch_labels = None
depends_on = None

# (app url, railway console url, github url or None)
LINKS = [
    ("https://builtbybeans.com",
     "https://railway.com/project/292cf71d-cd2f-43e4-a24f-014fb1bb5c26/service/9f31e963-8816-44a5-b773-8639d11cbdfd",
     "https://github.com/BuiltByBean/Built-By-Bean-Website"),
    ("https://datadungeon.io",
     "https://railway.com/project/0e85f06d-6ba6-4a8f-9ffc-4bb1395852ba/service/b2a4678e-bfce-4acd-abc6-464adf444acd",
     "https://github.com/BuiltByBean/Data-Dungeon"),
    ("https://kuperplumbing.com",
     "https://railway.com/project/0a60d280-1890-4034-a6d2-f66f478c7641/service/9f533f76-fa33-4a9d-a98d-a68e2b84fb55",
     "https://github.com/BuiltByBean/KuperPlumbing"),
    ("https://thewisdomcrucible.com",
     "https://railway.com/project/b6149cb4-fcec-4e34-a06a-5d1fb67b4ebf/service/30ed4bc3-d9d6-4d97-a69a-8f2713090e92",
     "https://github.com/BuiltByBean/Jakob-s-Crucible"),
    ("https://staff.jdentertain.com",
     "https://railway.com/project/b772c559-ca73-42c4-ac3c-f2adbe553df7/service/e35f8395-16de-405c-aa91-207214ab6208",
     "https://github.com/BuiltByBean/Talent-Booker"),
    ("https://covenantchristianchurch-production.up.railway.app",
     "https://railway.com/project/811b89e4-8e75-46c8-8f35-716a41305a26/service/26dd76aa-27b3-4d2e-904b-b0fa5954e76d",
     "https://github.com/BuiltByBean/Christ-Community-Church"),
    ("https://signadoc-production.up.railway.app",
     "https://railway.com/project/3dd5ad13-fc78-4699-b112-596e281ff443/service/64d657c0-6712-4222-bb65-788e99dd2a43",
     "https://github.com/BuiltByBean/Signadoc"),
    ("https://chopbuilder-production.up.railway.app",
     "https://railway.com/project/32718b0a-ae8e-4ecb-8a0d-622a62df6c3f/service/c28179df-0a1e-4516-b962-61014328ef29",
     None),
    ("https://crossfit-games-production.up.railway.app",
     "https://railway.com/project/5c5968cd-a63f-49b6-92db-001fc1fbf5ad/service/ac3ede16-ceef-4efd-af59-386c7469005b",
     "https://github.com/BuiltByBean/CrossFit-Games"),
    ("https://flipping-production.up.railway.app",
     "https://railway.com/project/37808b86-14d6-4b2c-986d-f386270ec20f/service/18f1fe01-af39-402f-b1a4-67706b97f3b0",
     "https://github.com/BuiltByBean/Flipping"),
    ("https://gym-ecosystem-production.up.railway.app",
     "https://railway.com/project/1cc3acfd-f801-4fc2-8c4a-13f4f42945e1/service/d60be102-c870-43bf-88cb-d1b29a05a702",
     "https://github.com/BuiltByBean/gym-ecosystem"),
    ("https://personal-trainer-production-5aa8.up.railway.app",
     "https://railway.com/project/b92c8fd3-7681-4bb8-aa1a-28c6eded811f/service/352c1cf1-f540-4d23-85e2-6ca38f328e71",
     "https://github.com/BuiltByBean/Personal-Trainer"),
]


def upgrade():
    conn = op.get_bind()
    have = {c["name"] for c in sa.inspect(conn).get_columns("app_links")}
    with op.batch_alter_table("app_links", schema=None) as batch_op:
        if "railway_url" not in have:
            batch_op.add_column(sa.Column("railway_url", sa.String(length=500), nullable=True))
        if "github_url" not in have:
            batch_op.add_column(sa.Column("github_url", sa.String(length=500), nullable=True))

    for app_url, railway_url, github_url in LINKS:
        conn.execute(
            sa.text("UPDATE app_links SET railway_url = :rw WHERE url = :u AND railway_url IS NULL"),
            {"rw": railway_url, "u": app_url})
        if github_url:
            conn.execute(
                sa.text("UPDATE app_links SET github_url = :gh WHERE url = :u AND github_url IS NULL"),
                {"gh": github_url, "u": app_url})


def downgrade():
    conn = op.get_bind()
    have = {c["name"] for c in sa.inspect(conn).get_columns("app_links")}
    with op.batch_alter_table("app_links", schema=None) as batch_op:
        for col in ("railway_url", "github_url"):
            if col in have:
                batch_op.drop_column(col)
