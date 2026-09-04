"""Cerebro: rules that check themselves, repos held against them

A project gains its repository. A rule gains a scanner - a pattern, the
files it applies to, and the one line it must catch - and the nine rules
that had a grep written for them get those greps as scanners. A new table
holds the result of running every scanner over every repository, one row
per pair, upserted nightly.

Revision ID: e2f07c95a1b4
Revises: d9e16b84f0a3
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "e2f07c95a1b4"
down_revision = "d9e16b84f0a3"
branch_labels = None
depends_on = None


# (slug, pattern, globs, exclude, unless, fixture). Raw strings, because a
# scanner is a regex and a regex is nothing but backslashes. Every fixture
# is a line the pattern must match; audit_repos.health() proves it nightly
# and on every Cerebro page load.
CHECKS = [
    ("teleported-dropdown",
     r'<select\b|<input[^>]*type="checkbox"|\bconfirm\(|\balert\(',
     "templates/**/*.html", "components/", None,
     '<select name="status"></select>'),
    ("timezones",
     r"\bdatetime\.utcnow\(\)|\butcfromtimestamp\(",
     "**/*.py", "migrations/", None,
     "created = datetime.utcnow()"),
    ("secrets-fail-closed",
     r"""environ\.get\(\s*["'][A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|KEY)[A-Z0-9_]*["']\s*,\s*["'][^"']+["']\s*\)""",
     "**/*.py", None, None,
     'SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")'),
    ("jinja-attr-quoting",
     r'="[^"]*\{\{[^}]*\|\s*tojson[^}]*\}\}',
     "templates/**/*.html", None, None,
     '<div x-data="{ n: {{ name|tojson }} }"></div>'),
    ("migrations-with-create-all",
     r"op\.create_table\(",
     "migrations/**/*.py", None, "has_table",
     'op.create_table("things", sa.Column("id", sa.Integer()))'),
    ("redirect-targets-that-stay-home",
     r"redirect\(\s*request\.(?:args|form|values)\.get\(",
     "**/*.py", None, None,
     'return redirect(request.args.get("next"))'),
    ("name-your-user-agent",
     r"\burlopen\(",
     "**/*.py", None, "User-Agent",
     "data = urllib.request.urlopen(url).read()"),
    ("escape-sequences-never-raw-control-bytes",
     r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
     "**/*.py,**/*.html,**/*.js,**/*.md", None, None,
     "x = 'a" + chr(1) + "b'"),
    ("fk-indexes",
     r"db\.ForeignKey\((?![^\n]*index=True)(?![^\n]*primary_key=True)(?![^\n]*unique=True)",
     "models.py,**/models*.py", "migrations/", None,
     'client_id = db.Column(db.Integer, db.ForeignKey("clients.id"))'),
]


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if "repo" not in _columns(bind, "projects"):
        op.add_column("projects", sa.Column("repo", sa.String(length=200), nullable=True))
        op.create_index("ix_projects_repo", "projects", ["repo"])

    have = _columns(bind, "features")
    for name, kind in (("check_pattern", sa.Text()), ("check_globs", sa.String(300)),
                       ("check_exclude", sa.String(300)), ("check_unless", sa.Text()),
                       ("check_fixture", sa.Text())):
        if name not in have:
            op.add_column("features", sa.Column(name, kind, nullable=True))

    if not sa.inspect(bind).has_table("rule_audits"):
        op.create_table(
            "rule_audits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("repo", sa.String(length=200), nullable=False),
            sa.Column("rule_id", sa.Integer(), nullable=False),
            sa.Column("sha", sa.String(length=64), nullable=True),
            sa.Column("violations", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sample_json", sa.Text(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_rule_audits"),
            sa.ForeignKeyConstraint(["rule_id"], ["features.id"],
                                    name="fk_rule_audits_rule_id", ondelete="CASCADE"),
            sa.UniqueConstraint("repo", "rule_id", name="uq_rule_audits_repo_rule"),
        )
        op.create_index("ix_rule_audits_repo", "rule_audits", ["repo"])
        op.create_index("ix_rule_audits_rule_id", "rule_audits", ["rule_id"])

    # Bound parameters, never string-built SQL: these values are regexes.
    update = sa.text(
        "UPDATE features SET check_pattern = :pattern, check_globs = :globs, "
        "check_exclude = :exclude, check_unless = :unless, check_fixture = :fixture "
        "WHERE slug = :slug AND kind = 'rule' AND check_pattern IS NULL")
    for slug, pattern, globs, exclude, unless, fixture in CHECKS:
        bind.execute(update, {"slug": slug, "pattern": pattern, "globs": globs,
                              "exclude": exclude, "unless": unless, "fixture": fixture})


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("rule_audits"):
        op.drop_index("ix_rule_audits_rule_id", table_name="rule_audits")
        op.drop_index("ix_rule_audits_repo", table_name="rule_audits")
        op.drop_table("rule_audits")
    have = _columns(bind, "features")
    with op.batch_alter_table("features") as batch:
        for name in ("check_pattern", "check_globs", "check_exclude", "check_unless",
                     "check_fixture"):
            if name in have:
                batch.drop_column(name)
    if "repo" in _columns(bind, "projects"):
        with op.batch_alter_table("projects") as batch:
            batch.drop_index("ix_projects_repo")
            batch.drop_column("repo")
