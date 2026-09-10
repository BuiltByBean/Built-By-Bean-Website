"""One card per app on My Apps

Two projects had two cards each, because a registration under the same
project with a new name made a new card: Robinson & Co. on its Railway
address and again on its real domain, EntertainHQ on the apex and again on
app. Where a project has more than one card this keeps one, by the rule the
door now applies (a real domain over a platform's temporary one, the
shorter host between two real ones, the older row between equals), folds
the repo, the Railway link, the description and the icon from the others
into it where it lacks them, and deletes the rest. Names that arrived as
HTML ("Robinson &amp; Co.") are unescaped.

Bound parameters throughout: Postgres and SQLite disagree about string
literals, and neither is asked to parse one here.

Revision ID: b6d2e9a41c7f
Revises: a5e83b1d70cf
Create Date: 2026-09-10
"""
import html

import sqlalchemy as sa
from alembic import op

revision = "b6d2e9a41c7f"
down_revision = "a5e83b1d70cf"
branch_labels = None
depends_on = None

TEMP_HOSTS = (".up.railway.app", ".railway.app", ".onrender.com", ".fly.dev",
              ".vercel.app", ".netlify.app", ".herokuapp.com", ".pages.dev")


def _host(url):
    return (url or "").split("//", 1)[-1].split("/", 1)[0].lower()


def _is_temp(url):
    h = _host(url)
    return any(h.endswith(t) for t in TEMP_HOSTS)


def _rank(row):
    """Lower is better: a real domain first, then the shorter host, then age."""
    return (1 if _is_temp(row["url"]) else 0, len(_host(row["url"])), row["id"])


def upgrade():
    bind = op.get_bind()
    rows = [dict(r._mapping) for r in bind.execute(sa.text(
        "SELECT id, project_id, name, url, description, github_url, railway_url, "
        "icon_file, icon_source, icon_fetched_at FROM app_links"))]

    # Names are never HTML.
    for r in rows:
        clean = html.unescape(r["name"] or "")
        if clean != r["name"]:
            bind.execute(sa.text("UPDATE app_links SET name = :n WHERE id = :id"),
                         {"n": clean, "id": r["id"]})
            r["name"] = clean

    by_project = {}
    for r in rows:
        if r["project_id"] is not None:
            by_project.setdefault(r["project_id"], []).append(r)

    fillable = ("description", "github_url", "railway_url", "icon_file", "icon_source", "icon_fetched_at")
    for project_id, cards in by_project.items():
        if len(cards) < 2:
            continue
        cards.sort(key=_rank)
        keep, rest = cards[0], cards[1:]
        # The card keeps the OLDEST name, which is the one the owner has been
        # looking at ("Robinson & Co."), not the one a later session invented
        # for the second card ("Robinson & Co. Studio Manager").
        fills = {}
        oldest = min(cards, key=lambda r: r["id"])
        if oldest["name"] and oldest["name"] != keep["name"]:
            fills["name"] = oldest["name"]
        for other in rest:
            for col in fillable:
                if not keep.get(col) and other.get(col) and col not in fills:
                    fills[col] = other[col]
        if fills:
            sets = ", ".join(f"{col} = :{col}" for col in fills)
            bind.execute(sa.text(f"UPDATE app_links SET {sets} WHERE id = :id"), {**fills, "id": keep["id"]})
        for other in rest:
            bind.execute(sa.text("DELETE FROM app_links WHERE id = :id"), {"id": other["id"]})


def downgrade():
    # The cards folded together cannot be told apart again, and the door no
    # longer makes a second one. Nothing to put back.
    pass
